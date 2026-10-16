#!/usr/bin/env python3
"""
PRISM risk-health score.

The four sub-score formulas are carried over from fine-score unchanged:

  F  diversification  inverted Herfindahl-Hirschman index across sectors
  I  correlation      average pairwise correlation of daily returns
  N  volatility       annualised vol, 10% -> 100 and 40% -> 0
  E  exposure         single-name concentration

PRISM score is their unweighted mean, as before.

Two things changed in the merge, neither touching the formulas:

  1. Inputs are read from MarketData. The standalone service downloaded 5y of
     prices, 5y of SPY, and a sector lookup per ticker on every request, then
     downloaded again for each benchmark portfolio it scored.
  2. Benchmark scores are cached. SPY and the 3-fund allocation do not depend on
     the user's holdings, so scoring them on every request was recomputing a
     constant.
"""

import time
from threading import Lock

import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .market_data import MarketData, download_closes, lookup_sectors

TRADING_DAYS = 252

VOL_FLOOR = 0.10    # <= 10% annualised vol scores 100
VOL_CEILING = 0.40  # >= 40% annualised vol scores 0

BENCHMARKS = {
    'spy': {'label': 'S&P 500 (SPY)', 'weights': {'SPY': 1.0}},
    'three_fund': {'label': '3-Fund Portfolio', 'weights': {'VTI': 0.60, 'VXUS': 0.20, 'BND': 0.20}},
}

_BENCHMARK_CACHE: dict = {}
_BENCHMARK_LOCK = Lock()
_BENCHMARK_TTL = 24 * 60 * 60  # scores move slowly; a day is plenty


# ── sub-scores (formulas unchanged from fine-score) ──────────────────────────

def score_diversification(sector_weights: dict) -> float:
    """Inverted HHI across sectors. 100 = spread evenly, 0 = one sector."""
    weights = list(sector_weights.values())
    if not weights:
        return 0.0
    hhi = sum(w ** 2 for w in weights)
    return round(max(0.0, 1.0 - hhi) * 100, 1)


def score_correlation(corr_matrix: pd.DataFrame) -> float:
    """Average pairwise correlation. 100 = uncorrelated, 0 = moves as one."""
    n = len(corr_matrix)
    if n < 2:
        return 100.0
    upper = corr_matrix.where(np.triu(np.ones(corr_matrix.shape), k=1).astype(bool))
    pairs = upper.stack()
    if pairs.empty:
        return 100.0
    return round(max(0.0, 1.0 - float(pairs.mean())) * 100, 1)


def score_volatility(portfolio_returns: pd.Series) -> float:
    """Annualised volatility mapped onto the 10%-40% band."""
    if portfolio_returns.empty:
        return 0.0
    ann_vol = float(portfolio_returns.std() * np.sqrt(TRADING_DAYS))
    raw = (1 - (ann_vol - VOL_FLOOR) / (VOL_CEILING - VOL_FLOOR)) * 100
    return round(max(0.0, min(100.0, raw)), 1)


def score_exposure(weights: dict) -> float:
    """Single-name concentration. Drops sharply once one name dominates."""
    if not weights:
        return 0.0
    max_weight = max(weights.values())
    if max_weight > 0.5:
        return round(max(0.0, (1 - max_weight) * 100), 1)
    score = max(0.0, (1 - (max_weight - (1 / len(weights))) * 3) * 100)
    return round(min(100.0, score), 1)


# ── benchmarks ───────────────────────────────────────────────────────────────

def _score_weight_set(ticker_weights: dict) -> float:
    """PRISM score for a fixed-weight portfolio. One download, then cached."""
    tickers = list(ticker_weights)
    closes = download_closes(tickers, period='5y')
    if closes.empty:
        return 0.0

    valid = [t for t in tickers if t in closes.columns and closes[t].notna().sum() > 10]
    if not valid:
        return 0.0

    closes = closes[valid]
    total_w = sum(ticker_weights[t] for t in valid)
    weights = {t: ticker_weights[t] / total_w for t in valid}

    sectors = lookup_sectors(valid)
    sector_weights: dict = {}
    for t, w in weights.items():
        s = sectors.get(t, 'Other')
        sector_weights[s] = sector_weights.get(s, 0.0) + w

    returns = closes.pct_change().dropna()
    w_arr = np.array([weights[t] for t in valid])
    port_returns = pd.Series(returns[valid].values @ w_arr, index=returns.index)

    corr = (returns[valid].corr() if len(valid) > 1
            else pd.DataFrame([[1.0]], index=valid, columns=valid))

    f = score_diversification(sector_weights)
    i = score_correlation(corr)
    n = score_volatility(port_returns)
    e = score_exposure(weights)
    return round((f + i + n + e) / 4, 1)


def benchmark_scores() -> dict:
    """Cached PRISM scores for the reference portfolios."""
    now = time.time()

    with _BENCHMARK_LOCK:
        cached = _BENCHMARK_CACHE.get('scores')
        if cached and now - cached['at'] < _BENCHMARK_TTL:
            return cached['value']

    # Computed outside the lock so a slow network call doesn't block readers.
    value = {
        key: {'label': spec['label'], 'score': _score_weight_set(spec['weights'])}
        for key, spec in BENCHMARKS.items()
    }

    with _BENCHMARK_LOCK:
        _BENCHMARK_CACHE['scores'] = {'at': now, 'value': value}

    return value


def clear_benchmark_cache() -> None:
    with _BENCHMARK_LOCK:
        _BENCHMARK_CACHE.pop('scores', None)


# ── main entry point ─────────────────────────────────────────────────────────

def compute(md: MarketData, weights: dict) -> dict:
    """Score a portfolio from already-fetched market data.

    `weights` are the market-value weights computed in core.portfolio, so the
    score describes exactly the book shown on the dashboard.
    """
    tickers = [t for t in md.valid if t in weights and weights[t] > 0]

    if len(tickers) < 2:
        return {
            'available': False,
            'reason': 'PRISM needs at least 2 holdings with price history.',
        }

    total = sum(weights[t] for t in tickers)
    norm = {t: weights[t] / total for t in tickers}

    sector_weights = md.sector_weights(norm)
    portfolio_returns = md.portfolio_returns(norm)
    corr = md.correlation().reindex(index=tickers, columns=tickers)

    f = score_diversification(sector_weights)
    i = score_correlation(corr)
    n = score_volatility(portfolio_returns)
    e = score_exposure(norm)
    prism_score = round((f + i + n + e) / 4, 1)

    return {
        'available': True,
        'prism_score': prism_score,
        'sub_scores': {'F': f, 'I': i, 'N': n, 'E': e},
        'benchmarks': benchmark_scores(),
        'sector_weights': {k: round(v, 4) for k, v in sector_weights.items()},
        'weights': {k: round(v, 4) for k, v in norm.items()},
        'correlation_matrix': {
            'tickers': tickers,
            'values': [[round(float(corr.loc[a, b]), 3) for b in tickers] for a in tickers],
        },
        'backtest': _backtest(md, portfolio_returns),
        'callout': _callout(f, i, n, e, sector_weights, norm, corr),
    }


def _backtest(md: MarketData, portfolio_returns: pd.Series) -> dict:
    """Cumulative growth and drawdown against SPY over the full 5y window."""
    empty = {'dates': [], 'portfolio': [], 'spy': [], 'stats': {}}

    if portfolio_returns.empty or md.benchmark_closes.empty:
        return empty

    spy_returns = md.benchmark_closes.pct_change().dropna()
    port_aligned, spy_aligned = portfolio_returns.align(spy_returns, join='inner')
    if port_aligned.empty:
        return empty

    port_cum = (1 + port_aligned).cumprod()
    spy_cum = (1 + spy_aligned).cumprod()

    port_dd = float((port_cum / port_cum.cummax() - 1).min())
    spy_dd = float((spy_cum / spy_cum.cummax() - 1).min())

    port_ann = float(port_cum.iloc[-1] ** (TRADING_DAYS / len(port_cum)) - 1)
    spy_ann = float(spy_cum.iloc[-1] ** (TRADING_DAYS / len(spy_cum)) - 1)

    monthly_port = port_cum.resample('ME').last()
    monthly_spy = spy_cum.resample('ME').last().reindex(monthly_port.index, method='nearest')

    return {
        'dates': monthly_port.index.strftime('%Y-%m-%d').tolist(),
        'portfolio': [round(float(v), 4) for v in monthly_port],
        'spy': [round(float(v), 4) for v in monthly_spy],
        'stats': {
            'portfolio_max_drawdown': round(port_dd * 100, 2),
            'spy_max_drawdown': round(spy_dd * 100, 2),
            'portfolio_ann_return': round(port_ann * 100, 2),
            'spy_ann_return': round(spy_ann * 100, 2),
        },
    }


def _callout(f, i, n, e, sector_weights, weights, corr) -> str:
    """Plain-language description of the weakest dimension."""
    lowest = min({'F': f, 'I': i, 'N': n, 'E': e}.items(), key=lambda kv: kv[1])[0]

    if lowest == 'F' and sector_weights:
        top = max(sector_weights, key=sector_weights.get)
        pct = round(sector_weights[top] * 100)
        return (f'Your portfolio is {pct}% concentrated in {top}. '
                f'If this sector drops, your whole portfolio feels it.')

    if lowest == 'I' and len(corr) > 1:
        upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
        pairs = upper.stack()
        if not pairs.empty:
            a, b = pairs.idxmax()
            val = round(float(pairs.max()) * 100)
            return (f"{a} and {b} move together {val}% of the time — "
                    f"they're not giving you real diversification.")

    if lowest == 'N':
        return ('Your portfolio is significantly more volatile than the S&P 500. '
                'Expect larger swings in both directions.')

    if lowest == 'E' and weights:
        top = max(weights, key=weights.get)
        pct = round(weights[top] * 100)
        return (f'{top} makes up {pct}% of your portfolio. '
                f'A bad quarter for this stock hits you hard.')

    return 'Your portfolio looks reasonably balanced.'


# ── perfect score description ───────────────────────────────────────────────

PERFECT_SCORE_DESCRIPTION = (
    'A perfect 100 PRISM score would require a portfolio that is equally spread '
    'across many sectors (no sector dominance), holds completely uncorrelated '
    'assets (each moves independently), has annualised volatility at or below '
    '10%, and has no single holding above an equal-weight share. In practice, '
    'real stock portfolios rarely score above 80 because equities are inherently '
    'correlated and volatile. A mix of stocks, bonds, commodities and real '
    'estate across global markets comes closest.'
)


# ── max achievable score ────────────────────────────────────────────────────

def _prism_from_weights(w_arr, tickers, returns_matrix, corr, sectors):
    """Compute PRISM sub-scores from a weight array (used by the optimizer)."""
    weights = {t: float(w_arr[i]) for i, t in enumerate(tickers)}

    # sector weights
    sector_w: dict = {}
    for t, w in weights.items():
        s = sectors.get(t, 'Other')
        sector_w[s] = sector_w.get(s, 0.0) + w

    # portfolio returns
    port_ret = pd.Series(returns_matrix @ w_arr, dtype=float)

    f = score_diversification(sector_w)
    i_score = score_correlation(corr)  # correlation is fixed for given tickers
    n = score_volatility(port_ret)
    e = score_exposure(weights)

    return (f + i_score + n + e) / 4, {'F': f, 'I': i_score, 'N': n, 'E': e}


def max_achievable(md: MarketData, tickers: list, current_weights: dict) -> dict:
    """Find the weight allocation that maximises the PRISM score.

    Only changes weights — the set of tickers stays fixed.
    Returns max_score, max_sub_scores, max_weights, improvements, and
    perfect_score_description.
    """
    n = len(tickers)
    if n < 2:
        return {'available': False}

    sectors = md.sectors
    corr = md.correlation().reindex(index=tickers, columns=tickers)
    returns_df = md.returns[tickers] if hasattr(md, 'returns') and not md.returns.empty else None
    if returns_df is None or returns_df.empty:
        return {'available': False}
    returns_matrix = returns_df.values

    # Objective: minimise negative PRISM score
    def neg_prism(w):
        score, _ = _prism_from_weights(w, tickers, returns_matrix, corr, sectors)
        return -score

    bounds = [(0.01 / n, 1.0)] * n  # every holding keeps a tiny sliver
    constraints = [{'type': 'eq', 'fun': lambda w: np.sum(w) - 1.0}]

    # Start from equal weight and from current weights, pick the better result
    best_score = -np.inf
    best_w = None
    for x0 in [np.ones(n) / n, np.array([current_weights.get(t, 1/n) for t in tickers])]:
        x0 = x0 / x0.sum()  # normalise
        result = minimize(neg_prism, x0, method='SLSQP',
                          bounds=bounds, constraints=constraints,
                          options={'maxiter': 500, 'ftol': 1e-9})
        if result.success or True:  # use result even if not converged
            score_val = -result.fun
            if score_val > best_score:
                best_score = score_val
                best_w = result.x

    if best_w is None:
        return {'available': False}

    # Normalise and round
    best_w = best_w / best_w.sum()
    max_score = round(best_score, 1)
    _, max_sub = _prism_from_weights(best_w, tickers, returns_matrix, corr, sectors)
    max_weights = {t: round(float(best_w[i]), 4) for i, t in enumerate(tickers)}

    # Current sub-scores for comparison
    cur_sw = md.sector_weights(current_weights)
    cur_pr = md.portfolio_returns(current_weights)
    cur_f = score_diversification(cur_sw)
    cur_i = score_correlation(corr)
    cur_n = score_volatility(cur_pr)
    cur_e = score_exposure(current_weights)
    cur_sub = {'F': cur_f, 'I': cur_i, 'N': cur_n, 'E': cur_e}

    # Build improvement tips
    improvements = _build_improvements(
        cur_sub, max_sub, current_weights, max_weights,
        tickers, sectors, md, corr,
    )

    return {
        'available': True,
        'max_score': max_score,
        'max_sub_scores': {k: round(v, 1) for k, v in max_sub.items()},
        'max_weights': max_weights,
        'improvements': improvements,
        'perfect_score_description': PERFECT_SCORE_DESCRIPTION,
    }


def _build_improvements(cur_sub, max_sub, cur_w, max_w, tickers, sectors, md, corr):
    """Generate specific actionable tips for each improvable dimension."""
    tips = []
    threshold = 2.0  # only mention if improvement is >= 2 points

    # F — Diversification
    if max_sub['F'] - cur_sub['F'] >= threshold:
        cur_sw = md.sector_weights(cur_w)
        max_sw = md.sector_weights(max_w)
        if cur_sw:
            top_sector = max(cur_sw, key=cur_sw.get)
            cur_pct = round(cur_sw[top_sector] * 100)
            new_pct = round(max_sw.get(top_sector, 0) * 100)
            tips.append(
                f'Rebalance to spread more evenly across sectors — reduce '
                f'{top_sector} from {cur_pct}% to {new_pct}%.'
            )

    # I — Correlation (weights cannot change the correlation matrix, but they
    # affect which pairs dominate; the score itself is fixed for these tickers,
    # so we only note it if there is a meaningful gap vs perfect)
    if max_sub['I'] - cur_sub['I'] >= threshold:
        upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
        pairs = upper.stack()
        if not pairs.empty:
            a, b = pairs.idxmax()
            tips.append(
                f'Reduce correlation by shifting weight from {a}/{b} '
                f'(highly correlated) to less correlated holdings.'
            )

    # N — Volatility
    if max_sub['N'] - cur_sub['N'] >= threshold:
        # Find lowest and highest vol tickers
        if hasattr(md, 'returns') and not md.returns.empty:
            vols = {t: float(md.returns[t].std() * np.sqrt(TRADING_DAYS))
                    for t in tickers if t in md.returns.columns}
            if vols:
                low_vol = min(vols, key=vols.get)
                high_vol = max(vols, key=vols.get)
                tips.append(
                    f'Lower portfolio volatility by increasing weight in '
                    f'{low_vol} (lowest vol) and reducing {high_vol} (highest vol).'
                )

    # E — Exposure
    if max_sub['E'] - cur_sub['E'] >= threshold:
        top = max(cur_w, key=cur_w.get)
        cur_pct = round(cur_w[top] * 100)
        new_pct = round(max_w.get(top, 0) * 100)
        tips.append(
            f'Reduce concentration — {top} at {cur_pct}% is too dominant, '
            f'bring it to {new_pct}%.'
        )

    if not tips:
        tips.append('Your current weights are already near the best achievable PRISM score for these holdings.')

    return tips
