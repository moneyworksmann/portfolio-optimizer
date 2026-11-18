#!/usr/bin/env python3
"""
Monte Carlo return engine.

The optimizer reports one number per allocation ("expected return 14.2%"). That
reads like a forecast, and it isn't one: it is the mean of a wide distribution.
This module simulates thousands of possible futures for a set of holdings and
reports the distribution itself, so the dashboard can say "a 1-in-20 bad year
costs about $8,400" or "there is a 31% chance of being down after 12 months"
instead of quoting a single point estimate.

Inputs come from the same MarketData object the rest of a request uses, so a
simulation costs no extra downloads:

    mean / covariance   md.mean_returns(days) / md.covariance(days)
    bootstrap history   md.returns_window(days)

Three ways to draw daily returns:

    normal      multivariate normal with the historical mean and covariance.
                Fast, smooth, and the textbook baseline. Understates crashes.
    student_t   multivariate Student-t with the same mean and covariance but
                fat tails (df=5 by default). One shared shock per day, so bad
                days hit every holding at once, as they do in a selloff.
    bootstrap   resample whole historical days (optionally in blocks), which
                keeps the real fat tails, skew and cross-asset correlation
                without assuming any distribution at all.

Paths are buy-and-hold: each holding compounds on its own and the portfolio is
the weighted sum, so winners drift to a bigger share over the horizon, exactly
as they would in a real account that is never rebalanced.

Nothing here is a prediction. Every figure is "if the next N days look like a
random draw from the lookback window, this is how often each outcome happens".
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TRADING_DAYS = 252

METHODS = ('normal', 'student_t', 'bootstrap')

DEFAULT_PATHS = 5000
MAX_PATHS = 50_000
MAX_HORIZON_DAYS = TRADING_DAYS * 30
PERCENTILES = (1, 5, 10, 25, 50, 75, 90, 95, 99)
FAN_PERCENTILES = (5, 25, 50, 75, 95)

# Paths are generated in batches so memory stays at batch * horizon * assets
# floats no matter how many paths are asked for (1000 x 252 x 40 = ~80 MB peak).
_BATCH = 1000

# A simple return below -100% is impossible; a normal draw can still produce one
# on a very volatile name. Clamp just above it so log1p stays finite.
_FLOOR = -0.9999


class SimulationError(ValueError):
    """Inputs that cannot be simulated (no assets, bad horizon, bad matrix)."""


@dataclass
class SimulationResult:
    """Raw simulation output; `summarize` turns it into dashboard numbers."""

    terminal_returns: np.ndarray   # (n_paths,) total return over the horizon
    max_drawdowns: np.ndarray      # (n_paths,) worst peak-to-trough, as a positive fraction
    fan_days: np.ndarray           # (k,) trading-day checkpoints, starting at 0
    fan: dict                      # {percentile: (k,) growth of $1 at each checkpoint}
    horizon_days: int
    method: str
    n_paths: int


# ── draws ────────────────────────────────────────────────────────────────────

def _cov_factor(cov: np.ndarray) -> np.ndarray:
    """A matrix L with L @ L.T == cov, tolerant of the near-singular covariances
    that short histories and near-duplicate holdings (QQQ + QQQM) produce."""
    cov = (cov + cov.T) / 2.0
    try:
        return np.linalg.cholesky(cov)
    except np.linalg.LinAlgError:
        vals, vecs = np.linalg.eigh(cov)
        vals = np.clip(vals, 0.0, None)
        return vecs * np.sqrt(vals)


def _draw_parametric(rng, mean, factor, size, horizon, method, df):
    n = mean.shape[0]
    z = rng.standard_normal((size, horizon, n))
    if method == 'student_t':
        # Multivariate t: one chi-square per (path, day), shared by every asset,
        # scaled so the covariance still equals `cov` (needs df > 2).
        w = rng.chisquare(df, size=(size, horizon, 1))
        z = z * np.sqrt((df - 2.0) / w)
    return mean + z @ factor.T


def _draw_bootstrap(rng, history, size, horizon, block):
    n_hist = history.shape[0]
    if block <= 1:
        idx = rng.integers(0, n_hist, size=(size, horizon))
    else:
        # Stationary-enough block bootstrap: random starts, consecutive days,
        # wrapping at the end so every day is equally likely to be drawn.
        n_blocks = -(-horizon // block)
        starts = rng.integers(0, n_hist, size=(size, n_blocks, 1))
        idx = (starts + np.arange(block)).reshape(size, -1)[:, :horizon] % n_hist
    return history[idx]


# ── core simulation ──────────────────────────────────────────────────────────

def simulate(
    weights,
    mean=None,
    cov=None,
    *,
    history=None,
    horizon_days: int = TRADING_DAYS,
    n_paths: int = DEFAULT_PATHS,
    method: str = 'normal',
    df: float = 5.0,
    block: int = 1,
    fan_points: int = 13,
    seed=None,
) -> SimulationResult:
    """Simulate buy-and-hold portfolio paths.

    weights   (n,) starting weights; normalised to sum to 1
    mean      (n,) daily mean simple returns          (normal / student_t)
    cov       (n, n) daily covariance of simple returns (normal / student_t)
    history   (T, n) daily simple returns to resample  (bootstrap)
    """
    if method not in METHODS:
        raise SimulationError(f'Unknown method {method!r}; use one of {", ".join(METHODS)}.')
    horizon_days = int(horizon_days)
    n_paths = int(n_paths)
    if not 1 <= horizon_days <= MAX_HORIZON_DAYS:
        raise SimulationError(f'horizon_days must be between 1 and {MAX_HORIZON_DAYS}.')
    if not 1 <= n_paths <= MAX_PATHS:
        raise SimulationError(f'n_paths must be between 1 and {MAX_PATHS}.')

    w = np.asarray(weights, dtype=float).ravel()
    if w.size == 0 or not np.all(np.isfinite(w)) or np.any(w < 0) or w.sum() <= 0:
        raise SimulationError('weights must be non-negative with a positive total.')
    w = w / w.sum()
    n = w.size

    if method == 'bootstrap':
        if history is None:
            raise SimulationError('bootstrap needs a history of daily returns.')
        history = np.asarray(history, dtype=float)
        if history.ndim != 2 or history.shape[1] != n or history.shape[0] < 2:
            raise SimulationError('history must be (days, assets) with at least 2 days.')
        history = np.nan_to_num(history, nan=0.0)
        block = max(1, int(block))
    else:
        if mean is None or cov is None:
            raise SimulationError(f'{method} needs a mean vector and covariance matrix.')
        mean = np.asarray(mean, dtype=float).ravel()
        cov = np.asarray(cov, dtype=float)
        if mean.shape != (n,) or cov.shape != (n, n):
            raise SimulationError('mean and cov must match the number of weights.')
        if not (np.all(np.isfinite(mean)) and np.all(np.isfinite(cov))):
            raise SimulationError('mean and cov must be finite.')
        if method == 'student_t' and df <= 2:
            raise SimulationError('df must be greater than 2 for a finite variance.')
        factor = _cov_factor(cov)

    rng = np.random.default_rng(seed)

    fan_points = max(2, min(int(fan_points), horizon_days + 1))
    fan_days = np.unique(np.linspace(0, horizon_days, fan_points).round().astype(int))
    fan_cols = fan_days[1:] - 1  # column index into the per-day value array

    terminal = np.empty(n_paths)
    drawdown = np.empty(n_paths)
    fan_values = np.empty((n_paths, fan_days.size))
    fan_values[:, 0] = 1.0

    for start in range(0, n_paths, _BATCH):
        size = min(_BATCH, n_paths - start)
        if method == 'bootstrap':
            r = _draw_bootstrap(rng, history, size, horizon_days, block)
        else:
            r = _draw_parametric(rng, mean, factor, size, horizon_days, method, df)

        # Each holding compounds independently (buy-and-hold), then weight.
        growth = np.exp(np.cumsum(np.log1p(np.maximum(r, _FLOOR)), axis=1))
        value = growth @ w                                   # (size, horizon)

        sl = slice(start, start + size)
        terminal[sl] = value[:, -1] - 1.0
        fan_values[sl, 1:] = value[:, fan_cols]

        full = np.concatenate([np.ones((size, 1)), value], axis=1)  # start at $1
        drawdown[sl] = np.max(1.0 - full / np.maximum.accumulate(full, axis=1), axis=1)

    fan = {p: np.percentile(fan_values, p, axis=0) for p in FAN_PERCENTILES}
    return SimulationResult(
        terminal_returns=terminal,
        max_drawdowns=drawdown,
        fan_days=fan_days,
        fan=fan,
        horizon_days=horizon_days,
        method=method,
        n_paths=n_paths,
    )


# ── risk statistics ──────────────────────────────────────────────────────────

def var_cvar(returns, confidence: float = 0.95) -> tuple:
    """(VaR, CVaR) of a return sample, both as positive loss fractions.

    VaR is the loss not exceeded with probability `confidence`; CVaR (expected
    shortfall) is the average loss in the tail beyond it. A result of 0 means
    even the tail outcome is a gain.
    """
    returns = np.asarray(returns, dtype=float)
    if returns.size == 0:
        return 0.0, 0.0
    cutoff = np.percentile(returns, (1.0 - confidence) * 100.0)
    tail = returns[returns <= cutoff]
    var = max(0.0, -float(cutoff))
    cvar = max(0.0, -float(tail.mean())) if tail.size else var
    return var, cvar


def _pct(x) -> float:
    return round(float(x) * 100.0, 2)


def _money(x, total_value):
    return round(float(x) * total_value, 2) if total_value else None


def summarize(result: SimulationResult, total_value: float = 0.0, bins: int = 40) -> dict:
    """Dashboard-ready distribution. Percent fields are in percent (12.3 = 12.3%),
    matching the optimizer's units; dollar fields are None without a value."""
    r = result.terminal_returns
    years = result.horizon_days / TRADING_DAYS

    var95, cvar95 = var_cvar(r, 0.95)
    var99, cvar99 = var_cvar(r, 0.99)

    median = float(np.median(r))
    median_annual = (1.0 + median) ** (1.0 / years) - 1.0 if years > 0 and median > -1 else -1.0

    counts, edges = np.histogram(r, bins=bins)
    histogram = [
        {'from_pct': _pct(lo), 'to_pct': _pct(hi), 'probability': round(float(c) / r.size, 5)}
        for lo, hi, c in zip(edges[:-1], edges[1:], counts)
    ]

    fan = [
        {'day': int(d), **{f'p{p}': round(float(result.fan[p][i]), 4) for p in FAN_PERCENTILES}}
        for i, d in enumerate(result.fan_days)
    ]

    thresholds = (-0.20, -0.10, 0.0, 0.10, 0.20)
    return {
        'method': result.method,
        'paths': result.n_paths,
        'horizon_days': result.horizon_days,
        'horizon_years': round(years, 3),
        'expected_return_pct': _pct(r.mean()),
        'median_return_pct': _pct(median),
        'median_annualized_pct': _pct(median_annual),
        'std_pct': _pct(r.std(ddof=1) if r.size > 1 else 0.0),
        'percentiles_pct': {f'p{p}': _pct(np.percentile(r, p)) for p in PERCENTILES},
        'prob_loss': round(float(np.mean(r < 0.0)), 4),
        'prob_below': {f'{int(t * 100)}': round(float(np.mean(r < t)), 4) for t in thresholds if t < 0},
        'prob_above': {f'{int(t * 100)}': round(float(np.mean(r > t)), 4) for t in thresholds if t > 0},
        'var_95_pct': _pct(var95),
        'cvar_95_pct': _pct(cvar95),
        'var_99_pct': _pct(var99),
        'cvar_99_pct': _pct(cvar99),
        'var_95_dollars': _money(var95, total_value),
        'cvar_95_dollars': _money(cvar95, total_value),
        'var_99_dollars': _money(var99, total_value),
        'cvar_99_dollars': _money(cvar99, total_value),
        'value_percentiles': (
            {f'p{p}': round(total_value * (1.0 + float(np.percentile(r, p))), 2) for p in PERCENTILES}
            if total_value else None
        ),
        'max_drawdown_median_pct': _pct(np.median(result.max_drawdowns)),
        'max_drawdown_p95_pct': _pct(np.percentile(result.max_drawdowns, 95)),
        'fan': fan,
        'histogram': histogram,
    }


# ── MarketData glue ──────────────────────────────────────────────────────────

def _weights_vector(tickers, weights: dict) -> np.ndarray:
    return np.array([max(0.0, float(weights.get(t, 0.0) or 0.0)) for t in tickers])


def analyse(
    md,
    weights: dict,
    total_value: float = 0.0,
    *,
    horizon_days: int = TRADING_DAYS,
    n_paths: int = DEFAULT_PATHS,
    method: str = 'normal',
    lookback_days: int | None = None,
    compare: dict | None = None,
    seed=None,
    **kwargs,
) -> dict:
    """Simulate the current weights (and any `compare` allocations) on `md`.

    lookback_days  history used for the mean, covariance and bootstrap pool.
                   None uses the whole MarketData window (5y on /api/analyze):
                   one year of means extrapolated forward is mostly noise, and a
                   longer window includes at least one real drawdown.
    compare        {name: {ticker: weight}} extra allocations to run on the same
                   inputs and seed, e.g. the optimizer's suggested weights.
    """
    tickers = [t for t in md.valid if (weights.get(t) or 0) > 0]
    if not tickers:
        return {'available': False, 'reason': 'No holdings with price history to simulate.'}

    days = lookback_days or (len(md.closes) if not md.closes.empty else TRADING_DAYS)
    history = md.returns_window(days)
    if history.empty or len(history) < 20:
        return {'available': False, 'reason': 'Not enough price history to simulate.'}

    # Allocations can name tickers the current book doesn't hold (a candidate the
    # optimizer wants to add), so the asset universe is the union.
    allocations = {'current': weights, **(compare or {})}
    universe = [t for t in md.valid if any((a.get(t) or 0) > 0 for a in allocations.values())]
    history = history.reindex(columns=universe).dropna(how='all').fillna(0.0)
    mean = history.mean().values
    cov = history.cov().values

    covered = sum(weights.get(t, 0.0) or 0.0 for t in tickers)
    total_w = sum(v or 0.0 for v in weights.values())
    uncovered = 1.0 - covered / total_w if total_w > 0 else 0.0

    results = {}
    for name, alloc in allocations.items():
        w = _weights_vector(universe, alloc)
        if w.sum() <= 0:
            continue
        sim = simulate(
            w, mean, cov, history=history.values, horizon_days=horizon_days,
            n_paths=n_paths, method=method, seed=seed, **kwargs,
        )
        # Dollars scale with the simulated portion of the book only.
        value = total_value * (1.0 - uncovered) if name == 'current' else total_value
        results[name] = summarize(sim, value)

    return {
        'available': True,
        'tickers': universe,
        'method': method,
        'paths': n_paths,
        'horizon_days': int(horizon_days),
        'lookback_days': int(len(history)) + 1,
        'lookback_start': history.index[0].strftime('%Y-%m-%d') if isinstance(history.index, pd.DatetimeIndex) else None,
        'lookback_end': history.index[-1].strftime('%Y-%m-%d') if isinstance(history.index, pd.DatetimeIndex) else None,
        'unsimulated_weight_pct': _pct(uncovered),
        'results': results,
        'note': (
            'Probabilities, not predictions: each figure is how often an outcome occurred '
            f'across {n_paths:,} simulated paths drawn from the lookback window.'
        ),
    }
