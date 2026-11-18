"""Stress-test model and Monte Carlo, on synthetic data (no network)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import sensitivity as S  # noqa: E402

TRUE = {
    'AAA': {'market': 1.3, 'rates': -0.0004, 'oil': 0.0},   # long-duration growth stock
    'BBB': {'market': 0.6, 'rates': 0.0001, 'oil': 0.35},   # energy-ish
    'CCC': {'market': 0.0, 'rates': -0.0008, 'oil': 0.0},   # bond-like
}


def synthetic_closes(weeks=260, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.date_range('2021-01-01', periods=weeks, freq='W-FRI')
    mkt = rng.normal(0.002, 0.022, weeks)
    d10 = rng.normal(0, 12, weeks)              # bp
    dslope = rng.normal(0, 8, weeks) - 0.3 * d10
    dvix = -60 * mkt + rng.normal(0, 1.2, weeks)
    oil = rng.normal(0, 0.045, weeks) + 0.3 * mkt
    usd = rng.normal(0, 0.008, weeks)

    def lvl(start, moves):
        return start * np.cumprod(1 + moves)

    ten = 1.5 + np.cumsum(d10) / 100
    bill = ten - (1.0 + np.cumsum(dslope) / 100)
    vix = np.cumsum(dvix)
    closes = {
        'SPY': lvl(380, mkt), '^TNX': ten, '^IRX': bill, '^VIX': vix - vix.min() + 10,
        'USO': lvl(70, oil), 'UUP': lvl(27, usd),
    }
    for t, b in TRUE.items():
        r = b['market'] * mkt + b['rates'] * d10 + b['oil'] * oil + rng.normal(0, 0.01, weeks)
        closes[t] = lvl(100, r)
    return pd.DataFrame(closes, index=idx)


@pytest.fixture(scope='module')
def model():
    closes = synthetic_closes()
    m = S.build_model(list(TRUE), {'AAA': 'Technology', 'BBB': 'Energy', 'CCC': 'Utilities'},
                      downloader=lambda syms: closes)
    assert m['available']
    return m


def test_recovers_betas(model):
    by = {a['ticker']: a for a in model['assets']}
    assert set(by) == set(TRUE)
    assert by['AAA']['betas']['market'] == pytest.approx(1.3, abs=0.12)
    assert by['BBB']['betas']['oil'] == pytest.approx(0.35, abs=0.06)
    assert by['CCC']['betas']['rates'] == pytest.approx(-0.0008, abs=0.0002)
    assert all(0 <= a['r2'] <= 1 for a in model['assets'])
    assert model['factor_keys'] == S.FACTOR_KEYS


def test_scenario_is_linear_in_betas(model):
    vals = {'AAA': 10000, 'BBB': 5000, 'CCC': 5000}
    r = S.simulate(model, vals, shocks={'rates': 100}, linked=False, paths=500, horizon_months=1)
    by = {a['ticker']: a for a in model['assets']}
    for h in r['scenario']['holdings']:
        assert h['change_pct'] == pytest.approx(by[h['ticker']]['betas']['rates'] * 100 * 100, rel=1e-6)
    expected = sum(v * by[t]['betas']['rates'] * 100 for t, v in vals.items())
    assert r['scenario']['change'] == pytest.approx(expected, rel=1e-6)
    assert r['scenario']['contributions']['rates'] == pytest.approx(expected, rel=1e-6)


def test_sector_shock_hits_only_that_sector(model):
    vals = {'AAA': 10000, 'BBB': 5000, 'CCC': 5000}
    r = S.simulate(model, vals, sector_shocks={'Energy': -20}, linked=False, paths=500, horizon_months=1)
    by = {h['ticker']: h for h in r['scenario']['holdings']}
    assert by['BBB']['change_pct'] == pytest.approx(-20)
    assert by['AAA']['change_pct'] == pytest.approx(0)
    assert r['scenario']['change'] == pytest.approx(-1000)


def test_linked_mode_fills_in_correlated_factors(model):
    r = S.simulate(model, {'AAA': 1000}, shocks={'market': -20}, linked=True, paths=500, horizon_months=1)
    eff = r['scenario']['effective_shocks']
    assert eff['market'] == pytest.approx(-20)
    assert eff['vol'] > 0          # VIX rises when stocks fall
    assert 'vol' in r['scenario']['implied']


def test_monte_carlo_shapes_and_ordering(model):
    vals = {'AAA': 10000, 'BBB': 5000, 'CCC': 5000}
    r = S.simulate(model, vals, shocks={'market': -25}, horizon_months=12, paths=2000)
    mc = r['mc']
    assert len(mc['months']) == 13 and mc['months'][-1] == pytest.approx(12)
    for side in ('base', 'shock'):
        p = mc[side]['percentiles']
        assert p['5'] < p['25'] < p['50'] < p['75'] < p['95']
        assert 0 <= mc[side]['prob_loss'] <= 1
        assert len(mc[side]['fan']['50']) == 13
        assert mc[side]['cvar95_pct'] <= mc[side]['var95_pct']
    assert mc['shock']['percentiles']['50'] < mc['base']['percentiles']['50']
    assert mc['shock']['prob_loss'] > mc['base']['prob_loss']
    assert sum(mc['hist']['base']) == 2000


def test_vol_slider_widens_the_spread(model):
    vals = {'AAA': 10000, 'BBB': 5000}
    lo = S.simulate(model, vals, vol_mult=0.5, paths=3000)['mc']['base']['percentiles']
    hi = S.simulate(model, vals, vol_mult=2.0, paths=3000)['mc']['base']['percentiles']
    assert (hi['95'] - hi['5']) > 2.5 * (lo['95'] - lo['5'])


def test_runs_on_the_shared_engine(model, monkeypatch):
    from core import montecarlo
    calls = []
    real = montecarlo.simulate
    monkeypatch.setattr(montecarlo, 'simulate', lambda *a, **k: calls.append(k) or real(*a, **k))
    r = S.simulate(model, {'AAA': 1000, 'BBB': 500}, shocks={'market': -10}, horizon_months=2, paths=500)
    assert len(calls) == 2                       # baseline + shocked, same seed
    assert calls[0]['seed'] == calls[1]['seed']
    assert calls[0]['horizon_days'] == 9         # weekly steps under 4 months
    assert r['assumptions']['engine'] == 'student_t' and r['assumptions']['step'] == 'week'
    r = S.simulate(model, {'AAA': 1000}, horizon_months=120, paths=4000, fat_tails=False)
    assert r['assumptions']['engine'] == 'normal' and r['assumptions']['step'] == 'month'
    assert r['mc']['months'][-1] == pytest.approx(120)


def test_missing_factor_is_dropped_not_fatal():
    closes = synthetic_closes()
    closes = closes.drop(columns=['USO', 'UUP'])
    m = S.build_model(['AAA'], downloader=lambda syms: closes)
    assert m['available'] and m['factor_keys'] == ['market', 'rates', 'curve', 'vol']
    r = S.simulate(m, {'AAA': 1000}, shocks={'oil': 50}, paths=500)  # unknown shock ignored
    assert r['available']


def test_flask_routes(model, monkeypatch):
    import app as appmod
    closes = synthetic_closes()
    monkeypatch.setattr(S, '_download_weekly', lambda syms, period='5y': closes)
    appmod._MODEL_CACHE.clear()
    c = appmod.app.test_client()
    m = c.post('/api/sensitivity/model', json={'holdings': [
        {'ticker': 'AAA', 'sector': 'Technology'}, {'ticker': 'zzz', 'sector': 'Other'}]}).get_json()
    assert m['available'] and m['skipped'] == ['ZZZ']
    r = c.post('/api/sensitivity/simulate', json={
        'model': m, 'values': {'AAA': 5000}, 'shocks': {'market': -10}, 'horizon_months': 6, 'paths': 800,
    }).get_json()
    assert r['available'] and r['scenario']['change'] < 0
    bad = c.post('/api/sensitivity/simulate', json={'model': {}, 'values': {}})
    assert bad.status_code == 400
