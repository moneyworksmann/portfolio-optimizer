"""Tests for the Monte Carlo engine. No network: MarketData is faked."""

import numpy as np
import pandas as pd
import pytest

from core import montecarlo as mc
from core.market_data import MarketData

DAYS = mc.TRADING_DAYS


# ── helpers ──────────────────────────────────────────────────────────────────

class FakeMD:
    """Just the MarketData surface montecarlo.analyse uses, from a closes frame."""

    BENCHMARK = 'SPY'

    def __init__(self, closes: pd.DataFrame):
        self.closes = closes
        self.valid = [c for c in closes.columns if c != self.BENCHMARK]
        self.dropped = []

    returns_window = MarketData.returns_window


def synthetic_closes(n_days=5 * DAYS, seed=0):
    rng = np.random.default_rng(seed)
    mean = np.array([0.0006, 0.0004, 0.0002])
    vol = np.array([0.02, 0.012, 0.005])
    corr = np.array([[1, 0.6, 0.1], [0.6, 1, 0.2], [0.1, 0.2, 1]])
    cov = corr * np.outer(vol, vol)
    rets = rng.multivariate_normal(mean, cov, size=n_days)
    prices = 100 * np.cumprod(1 + rets, axis=0)
    idx = pd.bdate_range('2021-01-04', periods=n_days)
    return pd.DataFrame(prices, index=idx, columns=['AAA', 'BBB', 'CCC'])


# ── simulate: correctness ────────────────────────────────────────────────────

def test_zero_volatility_is_deterministic_compounding():
    mean = np.array([0.001, 0.001])
    cov = np.zeros((2, 2))
    res = mc.simulate([0.5, 0.5], mean, cov, horizon_days=DAYS, n_paths=50, seed=1)
    expected = 1.001 ** DAYS - 1
    assert np.allclose(res.terminal_returns, expected)
    assert np.allclose(res.max_drawdowns, 0.0)


def test_normal_moments_match_lognormal_theory():
    # Single asset, daily mu/sigma: terminal log-return ~ N(T*m, T*s^2) approx.
    mu, sigma, T = 0.0004, 0.01, DAYS
    res = mc.simulate([1.0], [mu], [[sigma ** 2]], horizon_days=T, n_paths=40_000, seed=2)
    expected_mean = (1 + mu) ** T - 1
    assert res.terminal_returns.mean() == pytest.approx(expected_mean, abs=0.005)
    log_r = np.log1p(res.terminal_returns)
    assert log_r.std() == pytest.approx(sigma * np.sqrt(T), rel=0.03)


def test_seed_is_reproducible_and_different_seeds_differ():
    args = ([0.6, 0.4], [0.0005, 0.0003], [[1e-4, 2e-5], [2e-5, 5e-5]])
    a = mc.simulate(*args, n_paths=500, seed=11)
    b = mc.simulate(*args, n_paths=500, seed=11)
    c = mc.simulate(*args, n_paths=500, seed=12)
    assert np.array_equal(a.terminal_returns, b.terminal_returns)
    assert not np.array_equal(a.terminal_returns, c.terminal_returns)


def test_diversification_lowers_dispersion():
    mean = [0.0004, 0.0004]
    vol = 0.015
    uncorrelated = [[vol ** 2, 0], [0, vol ** 2]]
    single = mc.simulate([1, 0], mean, uncorrelated, n_paths=5000, seed=3)
    split = mc.simulate([1, 1], mean, uncorrelated, n_paths=5000, seed=3)
    assert split.terminal_returns.std() < 0.8 * single.terminal_returns.std()


def test_student_t_has_fatter_tails_than_normal_at_same_variance():
    mean, cov = [0.0], [[0.0002]]
    normal = mc.simulate([1], mean, cov, horizon_days=1, n_paths=50_000, seed=4)
    t = mc.simulate([1], mean, cov, horizon_days=1, n_paths=50_000, seed=4,
                    method='student_t', df=4)
    assert t.terminal_returns.std() == pytest.approx(normal.terminal_returns.std(), rel=0.1)
    _, cvar_n = mc.var_cvar(normal.terminal_returns, 0.99)
    _, cvar_t = mc.var_cvar(t.terminal_returns, 0.99)
    assert cvar_t > cvar_n


def test_bootstrap_only_reuses_historical_days():
    history = np.array([[0.01, -0.02], [0.03, 0.00], [-0.01, 0.01]])
    res = mc.simulate([1, 0], history=history, method='bootstrap',
                      horizon_days=1, n_paths=300, seed=5)
    assert set(np.round(res.terminal_returns, 10)) <= {0.01, 0.03, -0.01}


def test_block_bootstrap_keeps_consecutive_days():
    history = np.arange(1, 11, dtype=float).reshape(-1, 1) / 1000.0
    res = mc.simulate([1], history=history, method='bootstrap', block=10,
                      horizon_days=10, n_paths=200, seed=6)
    # A block of all 10 days in any rotation compounds to the same total.
    assert np.allclose(res.terminal_returns, np.prod(1 + history) - 1)


def test_buy_and_hold_lets_winners_drift():
    # Asset A doubles, B is flat. 50/50 buy-and-hold ends at +50%, not +100%.
    daily = 2 ** (1 / DAYS) - 1
    res = mc.simulate([0.5, 0.5], [daily, 0.0], np.zeros((2, 2)), n_paths=10, seed=0)
    assert np.allclose(res.terminal_returns, 0.5)


def test_fan_starts_at_one_and_is_ordered():
    res = mc.simulate([1], [0.0003], [[1e-4]], n_paths=2000, seed=7, fan_points=13)
    assert res.fan_days[0] == 0 and res.fan_days[-1] == DAYS
    for p in mc.FAN_PERCENTILES:
        assert res.fan[p][0] == 1.0
    assert np.all(res.fan[5] <= res.fan[50]) and np.all(res.fan[50] <= res.fan[95])


def test_near_singular_covariance_is_handled():
    # Two identical assets: covariance is rank 1, Cholesky fails.
    cov = np.full((2, 2), 1e-4)
    res = mc.simulate([0.5, 0.5], [0.0, 0.0], cov, n_paths=200, seed=8)
    assert np.all(np.isfinite(res.terminal_returns))


def test_extreme_draws_never_go_below_total_loss():
    res = mc.simulate([1], [0.0], [[1.0]], horizon_days=5, n_paths=500, seed=9)
    assert res.terminal_returns.min() >= -1.0
    assert np.all(np.isfinite(res.terminal_returns))


def test_batching_covers_every_path():
    res = mc.simulate([1], [0.0], [[1e-4]], n_paths=mc._BATCH * 2 + 17, seed=10)
    assert res.terminal_returns.shape == (mc._BATCH * 2 + 17,)
    assert np.all(np.isfinite(res.terminal_returns))


@pytest.mark.parametrize('kwargs', [
    dict(method='magic'),
    dict(horizon_days=0),
    dict(n_paths=mc.MAX_PATHS + 1),
    dict(weights=[-1, 2]),
    dict(weights=[0, 0]),
    dict(mean=[0.0]),
    dict(method='student_t', df=2),
    dict(method='bootstrap'),
])
def test_bad_inputs_raise(kwargs):
    base = dict(weights=[0.5, 0.5], mean=[0.0, 0.0], cov=np.eye(2) * 1e-4)
    base.update(kwargs)
    with pytest.raises(mc.SimulationError):
        mc.simulate(base.pop('weights'), base.pop('mean'), base.pop('cov'), **base)


# ── risk statistics ──────────────────────────────────────────────────────────

def test_var_cvar_on_known_sample():
    r = np.linspace(-0.99, 0.0, 100)  # -99% .. 0%, 1% steps
    var, cvar = mc.var_cvar(r, 0.95)
    assert var == pytest.approx(-np.percentile(r, 5))
    assert cvar == pytest.approx(-r[r <= np.percentile(r, 5)].mean())
    assert cvar >= var


def test_var_is_zero_when_every_outcome_is_a_gain():
    assert mc.var_cvar(np.array([0.05, 0.1, 0.2]), 0.95) == (0.0, 0.0)


def test_summarize_is_consistent():
    res = mc.simulate([1], [0.0003], [[1.5e-4]], n_paths=10_000, seed=12)
    s = mc.summarize(res, total_value=100_000)
    p = s['percentiles_pct']
    assert p['p1'] <= p['p5'] <= p['p25'] <= p['p50'] <= p['p75'] <= p['p95'] <= p['p99']
    assert s['median_return_pct'] == pytest.approx(p['p50'], abs=0.01)
    assert s['prob_loss'] == pytest.approx(np.mean(res.terminal_returns < 0), abs=1e-4)
    assert s['prob_below']['-10'] <= s['prob_loss']
    assert s['cvar_95_pct'] >= s['var_95_pct'] and s['cvar_99_pct'] >= s['var_99_pct']
    assert s['var_99_pct'] >= s['var_95_pct']
    assert s['var_95_dollars'] == pytest.approx(s['var_95_pct'] / 100 * 100_000, abs=10.0)
    assert s['value_percentiles']['p50'] == pytest.approx(100_000 * (1 + p['p50'] / 100), abs=10.0)
    assert sum(b['probability'] for b in s['histogram']) == pytest.approx(1.0, abs=1e-3)
    assert s['max_drawdown_p95_pct'] >= s['max_drawdown_median_pct'] >= 0


def test_summarize_without_value_has_no_dollars():
    res = mc.simulate([1], [0.0], [[1e-4]], n_paths=100, seed=0)
    s = mc.summarize(res)
    assert s['var_95_dollars'] is None and s['value_percentiles'] is None


# ── analyse on MarketData ────────────────────────────────────────────────────

def test_analyse_uses_market_data_and_compares_allocations():
    md = FakeMD(synthetic_closes())
    out = mc.analyse(
        md, {'AAA': 0.7, 'BBB': 0.3}, 50_000, n_paths=2000, seed=1,
        compare={'safer': {'CCC': 0.8, 'BBB': 0.2}},
    )
    assert out['available']
    assert set(out['results']) == {'current', 'safer'}
    assert out['tickers'] == ['AAA', 'BBB', 'CCC']
    assert out['lookback_days'] == len(md.closes)
    cur, safe = out['results']['current'], out['results']['safer']
    assert safe['std_pct'] < cur['std_pct']
    assert safe['max_drawdown_p95_pct'] < cur['max_drawdown_p95_pct']


@pytest.mark.parametrize('method', mc.METHODS)
def test_analyse_every_method(method):
    md = FakeMD(synthetic_closes())
    out = mc.analyse(md, {'AAA': 0.5, 'CCC': 0.5}, 10_000, n_paths=500,
                     method=method, seed=2, lookback_days=DAYS)
    assert out['available'] and out['method'] == method
    assert out['lookback_days'] == DAYS
    assert 0.0 <= out['results']['current']['prob_loss'] <= 1.0


def test_analyse_scales_dollars_to_simulated_portion():
    md = FakeMD(synthetic_closes())
    # ZZZ has no history: a quarter of the book can't be simulated.
    out = mc.analyse(md, {'AAA': 0.75, 'ZZZ': 0.25}, 100_000, n_paths=500, seed=3)
    cur = out['results']['current']
    assert out['unsimulated_weight_pct'] == pytest.approx(25.0)
    assert cur['var_95_dollars'] == pytest.approx(cur['var_95_pct'] / 100 * 75_000, abs=10.0)


def test_analyse_unavailable_without_history():
    md = FakeMD(synthetic_closes(n_days=10))
    assert not mc.analyse(md, {'AAA': 1.0})['available']
    assert not mc.analyse(FakeMD(synthetic_closes()), {'QQQ': 1.0})['available']


# ── Flask routes ─────────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch):
    import app as app_module

    closes = synthetic_closes()
    closes['SPY'] = closes.mean(axis=1)

    def fake_market_data(tickers, period='5y'):
        md = object.__new__(MarketData)
        md.requested = list(tickers)
        md.valid = [t for t in tickers if t in closes.columns and t != 'SPY']
        md.dropped = [t for t in tickers if t not in md.valid]
        md.closes = closes[md.valid + ['SPY']]
        md.benchmark_closes = closes['SPY']
        md.latest = {t: float(closes[t].iloc[-1]) for t in md.valid}
        md.returns = md.closes[md.valid].pct_change().dropna()
        md.sectors = {t: 'Technology' for t in md.valid}
        return md

    monkeypatch.setattr(app_module, 'MarketData', fake_market_data)
    return app_module.app.test_client()


HOLDINGS = [{'ticker': 'AAA', 'shares': 10, 'avg_cost': 90},
            {'ticker': 'BBB', 'shares': 20, 'avg_cost': 95}]


def test_simulate_route(client):
    r = client.post('/api/simulate', json={
        'holdings': HOLDINGS, 'paths': 800, 'horizon_days': 126,
        'method': 'student_t', 'seed': 5,
    })
    assert r.status_code == 200, r.get_json()
    body = r.get_json()
    assert body['available'] and body['horizon_days'] == 126
    cur = body['results']['current']
    assert cur['paths'] == 800 and cur['var_95_dollars'] is not None
    # Same seed, same answer.
    again = client.post('/api/simulate', json={
        'holdings': HOLDINGS, 'paths': 800, 'horizon_days': 126,
        'method': 'student_t', 'seed': 5,
    }).get_json()
    assert again['results'] == body['results']


def test_simulate_route_weight_override(client):
    r = client.post('/api/simulate', json={'weights': {'CCC': 100}, 'paths': 300, 'seed': 1})
    body = r.get_json()
    assert r.status_code == 200 and body['tickers'] == ['CCC']
    assert body['results']['current']['var_95_dollars'] is None


@pytest.mark.parametrize('payload', [
    {'holdings': []},
    {'holdings': HOLDINGS, 'method': 'magic'},
    {'holdings': HOLDINGS, 'paths': 'lots'},
    {'holdings': HOLDINGS, 'horizon_days': -5},
])
def test_simulate_route_rejects_bad_input(client, payload):
    assert client.post('/api/simulate', json=payload).status_code == 400


def test_analyze_includes_monte_carlo(client, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module.prism, 'benchmark_scores', lambda: {})
    monkeypatch.setattr(app_module, '_hindsight', lambda lots, md: {'available': False})
    r = client.post('/api/analyze', json={'holdings': HOLDINGS})
    assert r.status_code == 200, r.get_json()
    mcout = r.get_json()['monte_carlo']
    assert mcout['available'], mcout
    assert 'current' in mcout['results'] and 'optimal' in mcout['results']
