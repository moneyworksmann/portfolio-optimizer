"""
Live sensitivity analysis and Monte Carlo for the "Stress test" dashboard.

Two steps, so the sliders can stay live without re-downloading anything:

  build_model(tickers)      one download (5y weekly) of the holdings plus a
                            handful of macro factors, then a factor regression
                            per holding. Slow-ish (network), done once.

  simulate(model, ...)      pure NumPy. Applies the slider shocks to the
                            factor betas for an instant "what if" P&L, then
                            runs a Monte Carlo of the portfolio over the
                            chosen horizon, with and without the shock, on the
                            same random draws. Fast enough to call on every
                            slider move.

The model travels to the browser and back, so the server stays stateless (it
runs on Vercel, where requests don't share memory reliably).

Factor model (weekly data, 5 years)

    r_i = a_i + b_mkt*SPY + b_rate*d10y + b_curve*d(10y-3m) + b_vol*dVIX
              + b_oil*USO + b_usd*UUP + e_i

Rate and curve factors are in basis points, VIX in index points, the rest are
returns. Betas are estimated jointly, so b_vol is the extra sensitivity to fear
over and above the market move, and b_rate is the response to yields with the
market held still.

Monte Carlo

    Runs on the app's shared engine (core/montecarlo.py). The factor model
    supplies the inputs: the holdings' covariance is B * factor_cov * B' plus
    each holding's own residual variance, scaled by the volatility slider, and
    expected returns are CAPM-style: cash rate + b_mkt * (market return
    assumption - cash rate). Fat tails switch the engine to a multivariate
    Student-t (df=4). The shock is a jump at day 0: the shocked run starts
    from the post-shock dollars, with the same random draws as the baseline.

None of this is a forecast. It gives the spread of outcomes the past five
years' relationships imply, under the assumptions on the sliders.
"""

from __future__ import annotations

import math
from typing import Callable

import numpy as np
import pandas as pd

from . import montecarlo

WEEKS_PER_YEAR = 52
MIN_WEEKS = 26

# key, label, yahoo symbol(s), kind, unit, slider range, standard move for the
# tornado chart (roughly a one-sigma annual move).
FACTORS = [
    {'key': 'market', 'label': 'Stock market (S&P 500)', 'kind': 'return', 'unit': '%',
     'min': -50, 'max': 30, 'step': 1, 'standard': 15},
    {'key': 'rates', 'label': '10-year Treasury yield', 'kind': 'level_bp', 'unit': 'bp',
     'min': -300, 'max': 300, 'step': 10, 'standard': 100},
    {'key': 'curve', 'label': 'Yield curve slope (10y − 3m)', 'kind': 'level_bp', 'unit': 'bp',
     'min': -200, 'max': 200, 'step': 10, 'standard': 75},
    {'key': 'vol', 'label': 'Volatility (VIX)', 'kind': 'level_pts', 'unit': 'pts',
     'min': -15, 'max': 50, 'step': 1, 'standard': 8},
    {'key': 'oil', 'label': 'Oil price', 'kind': 'return', 'unit': '%',
     'min': -60, 'max': 100, 'step': 5, 'standard': 30},
    {'key': 'usd', 'label': 'US dollar', 'kind': 'return', 'unit': '%',
     'min': -20, 'max': 20, 'step': 1, 'standard': 8},
]
FACTOR_KEYS = [f['key'] for f in FACTORS]

SYMBOLS = {'market': 'SPY', 'ten': '^TNX', 'bill': '^IRX', 'vol': '^VIX', 'oil': 'USO', 'usd': 'UUP'}

PRESETS = [
    {'key': 'rate_shock', 'label': '2022-style rate shock',
     'shocks': {'rates': 250, 'curve': -100, 'market': -20, 'vol': 10, 'usd': 10}, 'sectors': {}},
    {'key': 'recession', 'label': 'Recession',
     'shocks': {'market': -30, 'rates': -150, 'curve': 100, 'vol': 25, 'oil': -40}, 'sectors': {}},
    {'key': 'stagflation', 'label': 'Stagflation',
     'shocks': {'market': -15, 'rates': 100, 'curve': -50, 'oil': 50, 'vol': 10}, 'sectors': {}},
    {'key': 'soft_landing', 'label': 'Soft landing',
     'shocks': {'market': 10, 'rates': -75, 'curve': 50, 'vol': -5}, 'sectors': {}},
    {'key': 'tech_selloff', 'label': 'Tech sell-off',
     'shocks': {'market': -8, 'vol': 8}, 'sectors': {'Technology': -25, 'Communication Services': -15}},
]


# ══════════════════════════════════════════════════════════════════════════
#  Model
# ══════════════════════════════════════════════════════════════════════════

def _download_weekly(symbols, period='5y') -> pd.DataFrame:
    import yfinance as yf  # imported lazily so tests run without network
    raw = yf.download(list(dict.fromkeys(symbols)), period=period, interval='1wk',
                      auto_adjust=True, progress=False)
    if raw is None or len(raw) == 0:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw['Close'].copy()
    else:
        closes = raw[['Close']].copy()
        closes.columns = [symbols[0]]
    return closes.ffill().dropna(how='all')


def _yield_pct(s: pd.Series) -> pd.Series:
    """Yahoo has quoted ^TNX both as 4.25 and as 42.5; normalise to percent."""
    s = s.astype(float)
    return s / 10.0 if s.dropna().median() > 20 else s


def factor_frame(closes: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Weekly factor moves in model units, plus the latest levels."""
    out, levels = {}, {}
    c = closes
    if SYMBOLS['market'] in c:
        out['market'] = c[SYMBOLS['market']].pct_change()
    if SYMBOLS['ten'] in c:
        ten = _yield_pct(c[SYMBOLS['ten']])
        out['rates'] = ten.diff() * 100.0
        levels['rates'] = float(ten.dropna().iloc[-1])
        if SYMBOLS['bill'] in c:
            bill = _yield_pct(c[SYMBOLS['bill']])
            slope = ten - bill
            out['curve'] = slope.diff() * 100.0
            levels['curve'] = float(slope.dropna().iloc[-1] * 100.0)
            levels['cash'] = float(bill.dropna().iloc[-1])
    if SYMBOLS['vol'] in c:
        out['vol'] = c[SYMBOLS['vol']].astype(float).diff()
        levels['vol'] = float(c[SYMBOLS['vol']].dropna().iloc[-1])
    if SYMBOLS['oil'] in c:
        out['oil'] = c[SYMBOLS['oil']].pct_change()
    if SYMBOLS['usd'] in c:
        out['usd'] = c[SYMBOLS['usd']].pct_change()
    frame = pd.DataFrame(out)
    # Keep factors with enough history; a missing one is dropped, not fatal.
    frame = frame[[k for k in FACTOR_KEYS if k in frame and frame[k].notna().sum() >= MIN_WEEKS]]
    return frame, levels


def estimate(asset_returns: pd.DataFrame, factors: pd.DataFrame, ridge: float = 1e-3) -> dict:
    """OLS (lightly ridged) of each holding on the factors.

    Factors are standardised before the fit so the ridge treats them equally,
    then the betas are mapped back to raw units.
    """
    keys = list(factors.columns)
    fx = factors.dropna()
    result = {}
    for t in asset_returns.columns:
        df = pd.concat([asset_returns[t].rename('_y'), fx], axis=1, join='inner').dropna()
        if len(df) < MIN_WEEKS:
            continue
        y = df['_y'].to_numpy()
        X = df[keys].to_numpy()
        mu, sd = X.mean(0), X.std(0)
        sd[sd == 0] = 1.0
        Z = (X - mu) / sd
        A = np.column_stack([np.ones(len(Z)), Z])
        reg = np.eye(A.shape[1]) * ridge * len(Z)
        reg[0, 0] = 0.0
        coef = np.linalg.solve(A.T @ A + reg, A.T @ y)
        betas = coef[1:] / sd
        fitted = A @ coef
        resid = y - fitted
        ss_tot = float(((y - y.mean()) ** 2).sum()) or 1.0
        result[t] = {
            'betas': {k: float(b) for k, b in zip(keys, betas)},
            'resid_sd_w': float(resid.std(ddof=len(keys) + 1)),
            'r2': float(1 - (resid ** 2).sum() / ss_tot),
            'vol_ann': float(y.std(ddof=1) * math.sqrt(WEEKS_PER_YEAR)),
            'weeks': int(len(df)),
        }
    return result


def model_from_closes(closes: pd.DataFrame, tickers, sectors: dict | None = None) -> dict:
    """Build the model from a weekly close frame (holdings + factor symbols)."""
    sectors = sectors or {}
    fac, levels = factor_frame(closes)
    if fac.empty or 'market' not in fac:
        return {'available': False, 'reason': 'Could not load the market factor data (SPY). Try again in a minute.'}

    held = [t for t in tickers if t in closes.columns]
    rets = closes[held].pct_change() if held else pd.DataFrame()
    fits = estimate(rets, fac) if held else {}

    fx = fac.dropna()
    cov = fx.cov().to_numpy()
    keys = list(fac.columns)

    assets = []
    for t in tickers:
        if t not in fits:
            continue
        px = closes[t].dropna()
        assets.append({
            'ticker': t,
            'sector': sectors.get(t, 'Other'),
            'price': float(px.iloc[-1]),
            **fits[t],
        })

    meta = [dict(f, current=levels.get(f['key'])) for f in FACTORS if f['key'] in keys]
    return {
        'available': bool(assets),
        'reason': None if assets else 'None of the holdings had enough weekly history to model.',
        'factors': meta,
        'factor_keys': keys,
        'factor_cov_w': cov.tolist(),
        'factor_sd_ann': [float(math.sqrt(cov[i, i] * WEEKS_PER_YEAR)) for i in range(len(keys))],
        'cash_rate': levels.get('cash', 4.0) / 100.0 if levels.get('cash') is not None else 0.04,
        'assets': assets,
        'skipped': [t for t in tickers if t not in fits],
        'presets': PRESETS,
        'window': {'start': str(fx.index[0].date()), 'end': str(fx.index[-1].date()), 'weeks': int(len(fx))},
    }


def build_model(tickers, sectors: dict | None = None,
                downloader: Callable | None = None) -> dict:
    tickers = list(dict.fromkeys(str(t).upper().strip() for t in tickers if str(t).strip()))
    if not tickers:
        return {'available': False, 'reason': 'No holdings provided.'}
    closes = (downloader or _download_weekly)(tickers + list(SYMBOLS.values()))
    if closes.empty:
        return {'available': False, 'reason': 'Could not download price history. Try again in a minute.'}
    return model_from_closes(closes, tickers, sectors)


# ══════════════════════════════════════════════════════════════════════════
#  Scenario + Monte Carlo
# ══════════════════════════════════════════════════════════════════════════

def _to_model_units(key: str, v: float) -> float:
    """Slider value -> factor-move units used in the regression."""
    kind = next((f['kind'] for f in FACTORS if f['key'] == key), 'return')
    return v / 100.0 if kind == 'return' else float(v)


def _to_slider_units(key: str, v: float) -> float:
    kind = next((f['kind'] for f in FACTORS if f['key'] == key), 'return')
    return v * 100.0 if kind == 'return' else float(v)


def linked_shocks(keys, cov, shocks: dict) -> dict:
    """Fill in factors the user left at zero with their expected move given the
    ones they set, from the historical covariance (a conditional mean)."""
    s_idx = [i for i, k in enumerate(keys) if abs(shocks.get(k, 0.0)) > 1e-12]
    if not s_idx or len(s_idx) == len(keys):
        return {k: shocks.get(k, 0.0) for k in keys}
    u_idx = [i for i in range(len(keys)) if i not in s_idx]
    C = np.asarray(cov)
    s = np.array([shocks[keys[i]] for i in s_idx])
    Css = C[np.ix_(s_idx, s_idx)]
    Cus = C[np.ix_(u_idx, s_idx)]
    implied = Cus @ np.linalg.pinv(Css) @ s
    out = {k: shocks.get(k, 0.0) for k in keys}
    for j, i in enumerate(u_idx):
        out[keys[i]] = float(implied[j])
    return out


def simulate(model: dict, values: dict, shocks: dict | None = None,
             sector_shocks: dict | None = None, vol_mult: float = 1.0,
             horizon_months: int = 12, market_return: float = 0.07,
             linked: bool = True, fat_tails: bool = True,
             target_return: float = 0.0, paths: int = 4000, seed: int = 7) -> dict:
    """Scenario P&L and Monte Carlo for `values` ({ticker: dollars}).

    `shocks` are in slider units (% for returns, bp for rates/curve, points for
    VIX). `sector_shocks` are % moves applied on top to every holding in that
    sector. `market_return` and `target_return` are annual decimals.
    """
    shocks = shocks or {}
    sector_shocks = sector_shocks or {}
    keys = list(model['factor_keys'])
    cov_w = np.asarray(model['factor_cov_w'], dtype=float)
    assets = [a for a in model['assets'] if values.get(a['ticker'], 0) > 0]
    if not assets:
        return {'available': False, 'reason': 'Give at least one modelled holding a value above zero.'}

    tick = [a['ticker'] for a in assets]
    v0 = np.array([float(values[t]) for t in tick])
    V0 = float(v0.sum())
    B = np.array([[a['betas'].get(k, 0.0) for k in keys] for a in assets])  # N x K
    sig_e = np.array([a['resid_sd_w'] for a in assets])
    vol_mult = float(np.clip(vol_mult, 0.25, 4.0))
    horizon_months = int(np.clip(horizon_months, 1, 120))
    paths = int(np.clip(paths, 500, 20000))

    # ── instant scenario ────────────────────────────────────────────────
    raw = {k: _to_model_units(k, float(shocks.get(k, 0.0) or 0.0)) for k in keys}
    eff = linked_shocks(keys, cov_w, raw) if linked else raw
    s = np.array([eff[k] for k in keys])
    sec = np.array([float(sector_shocks.get(a['sector'], 0.0) or 0.0) / 100.0 for a in assets])
    jump = np.clip(B @ s + sec, -0.99, None)  # per-holding % move
    contrib_factor = {k: float((v0 * B[:, i] * s[i]).sum()) for i, k in enumerate(keys)}
    contrib_sector = float((v0 * sec).sum())
    V_shock = float((v0 * (1 + jump)).sum())

    # ── exposures: portfolio move for a standard move in each factor ─────
    w = v0 / V0
    exposures = []
    for i, k in enumerate(keys):
        f = next(f for f in FACTORS if f['key'] == k)
        unit = _to_model_units(k, f['standard'])
        exposures.append({
            'key': k, 'label': f['label'], 'unit': f['unit'], 'standard': f['standard'],
            'beta': float(w @ B[:, i]),
            'pct_up': float(w @ B[:, i] * unit * 100),
            'pct_down': float(-w @ B[:, i] * unit * 100),
        })

    # ── Monte Carlo (shared engine in core/montecarlo.py) ────────────────
    # The factor model gives each holding's daily mean and the holdings'
    # daily covariance; the engine does the path simulation. The shocked run
    # starts from the post-shock dollars with the same seed, so the two
    # distributions differ only by the shock.
    cash = float(model.get('cash_rate', 0.04))
    k_mkt = keys.index('market')
    mu_ann = cash + B[:, k_mkt] * (market_return - cash)
    cov_asset_w = B @ cov_w @ B.T + np.diag(sig_e ** 2)
    # The engine is unit-agnostic: it compounds whatever step it is given.
    # Monthly steps (weekly under 4 months) keep a slider move well under a
    # second even for 40 holdings over 10 years; daily steps would take ~4 s.
    step_weeks = WEEKS_PER_YEAR / 12 if horizon_months > 3 else 1.0
    steps_per_year = WEEKS_PER_YEAR / step_weeks
    n_steps = max(1, int(round(horizon_months / 12 * steps_per_year)))
    paths = int(max(1000, min(paths, 8_000_000 // (n_steps * len(tick)))))
    mean_s = mu_ann / steps_per_year
    cov_s = cov_asset_w * step_weeks * vol_mult ** 2
    run = dict(horizon_days=n_steps, n_paths=paths,
               method='student_t' if fat_tails else 'normal', df=4.0,
               fan_points=min(n_steps, 24) + 1, seed=seed)
    res_base = montecarlo.simulate(v0, mean_s, cov_s, **run)
    v_after = v0 * (1 + jump)
    res_shock = montecarlo.simulate(v_after, mean_s, cov_s, **run)

    q = [5, 25, 50, 75, 95]
    months = [round(d / steps_per_year * 12, 2) for d in res_base.fan_days]
    yrs = horizon_months / 12
    target_end = V0 * (1 + target_return) ** yrs

    def stats(res, start):
        end = start * (1 + res.terminal_returns)
        ret = end / V0 - 1                       # measured from today's value
        var, cvar = montecarlo.var_cvar(ret, 0.95)
        return {
            'end': end,
            'percentiles': {str(p): float(np.percentile(end, p)) for p in q},
            'mean': float(end.mean()),
            'prob_loss': float((end < V0).mean()),
            'prob_target': float((end >= target_end).mean()),
            'var95_pct': -var * 100,
            'cvar95_pct': -cvar * 100,
            'median_drawdown_pct': float(-np.median(res.max_drawdowns) * 100),
            'prob_drawdown20': float((res.max_drawdowns >= 0.20).mean()),
            'fan': {str(p): (start * np.asarray(res.fan[p])).round(2).tolist() for p in q},
        }

    sb, ss = stats(res_base, V0), stats(res_shock, V_shock)
    eb, es = sb.pop('end'), ss.pop('end')
    lo = float(min(np.percentile(eb, 0.5), np.percentile(es, 0.5)))
    hi = float(max(np.percentile(eb, 99.5), np.percentile(es, 99.5)))
    edges = np.linspace(lo, hi, 41)
    hist = {
        'edges': edges.round(2).tolist(),
        'base': np.histogram(np.clip(eb, lo, hi), edges)[0].tolist(),
        'shock': np.histogram(np.clip(es, lo, hi), edges)[0].tolist(),
    }

    port_vol = float(math.sqrt(w @ (B @ (cov_w * WEEKS_PER_YEAR) @ B.T) @ w
                               + (w ** 2 * sig_e ** 2 * WEEKS_PER_YEAR).sum()))

    return {
        'available': True,
        'value_now': V0,
        'scenario': {
            'value_after': V_shock,
            'change': V_shock - V0,
            'change_pct': (V_shock / V0 - 1) * 100,
            'effective_shocks': {k: _to_slider_units(k, eff[k]) for k in keys},
            'implied': [k for k in keys if linked and abs(raw[k]) < 1e-12 and abs(eff[k]) > 1e-12],
            'contributions': {**contrib_factor, 'sector': contrib_sector},
            'holdings': [{
                'ticker': t, 'sector': a['sector'], 'value': float(v0[i]),
                'change_pct': float(jump[i] * 100), 'change': float(v0[i] * jump[i]),
            } for i, (t, a) in enumerate(zip(tick, assets))],
        },
        'exposures': exposures,
        'assumptions': {
            'expected_return_pct': float(w @ mu_ann * 100),
            'volatility_pct': port_vol * vol_mult * 100,
            'cash_rate_pct': cash * 100,
            'market_return_pct': market_return * 100,
            'horizon_months': horizon_months,
            'paths': paths,
            'engine': res_base.method,
            'step': 'month' if step_weeks > 1 else 'week',
            'fat_tails': bool(fat_tails),
        },
        'mc': {'months': months, 'base': sb, 'shock': ss, 'hist': hist},
    }
