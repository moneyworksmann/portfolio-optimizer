#!/usr/bin/env python3
"""
Markowitz mean-variance optimization.

`optimize` and `stats` are the SLSQP routine and the annualisation from
portfolio-optimizer, unchanged — same 25% position cap, same long-only
fully-invested constraints, same 252-day annualisation.

What changed is reach. In the source repo the optimizer only ran in the CLI
path that wrote a static HTML file (`main()` -> `generate_html_report`); the
Flask route never called it, so the web dashboard showed P&L and sector splits
but no optimal allocation at all. Here it runs on every /api/analyze request.
"""

import numpy as np
import pandas as pd
from scipy.optimize import minimize

TRADING_DAYS = 252
MAX_POSITION = 0.25  # long-only, no single name above 25%


def optimize(tickers, mean_returns, cov_matrix) -> np.ndarray:
    """Weights maximising the Sharpe ratio, via SLSQP."""
    n = len(tickers)
    if n == 0:
        return np.array([])
    if n == 1:
        return np.array([1.0])

    mean_arr = np.array([mean_returns.get(t, 0.0) for t in tickers])
    cov_arr = cov_matrix.loc[tickers, tickers].values

    def neg_sharpe(w):
        ret = np.dot(mean_arr, w) * TRADING_DAYS
        risk = np.sqrt(w @ cov_arr @ w * TRADING_DAYS)
        return -(ret / risk) if risk > 1e-9 else 0.0

    # The cap has to leave room for a feasible solution when the book is small:
    # 3 names cannot each stay under 25% and still sum to 1.
    cap = max(MAX_POSITION, 1.0 / n)

    result = minimize(
        neg_sharpe,
        x0=np.array([1 / n] * n),
        method='SLSQP',
        bounds=[(0.0, cap)] * n,
        constraints={'type': 'eq', 'fun': lambda w: np.sum(w) - 1},
    )

    weights = result.x if result.success else np.array([1 / n] * n)
    weights = np.clip(weights, 0.0, None)
    total = weights.sum()
    return weights / total if total > 0 else np.array([1 / n] * n)


def stats(weights, mean_returns, cov_matrix) -> tuple:
    """(annual return, annual volatility, Sharpe) for a weight vector."""
    weights = np.asarray(weights, dtype=float)
    ret = float(np.sum(mean_returns * weights) * TRADING_DAYS)
    risk = float(np.sqrt(weights.T @ (cov_matrix * TRADING_DAYS) @ weights))
    sharpe = ret / risk if risk > 0 else 0.0
    return ret, risk, sharpe


def analyse(md, current_weights: dict) -> dict:
    """Compare current, optimal and equal-weight allocations on a 1y window."""
    tickers = [t for t in md.valid if t in current_weights]
    if len(tickers) < 2:
        return {
            'available': False,
            'reason': 'Optimization needs at least 2 holdings with price history.',
        }

    mean_returns = md.mean_returns(TRADING_DAYS)
    cov_matrix = md.covariance(TRADING_DAYS)
    if mean_returns.empty or cov_matrix.empty:
        return {'available': False, 'reason': 'Not enough price history to optimize.'}

    mean_returns = mean_returns.reindex(tickers).fillna(0.0)
    cov_matrix = cov_matrix.reindex(index=tickers, columns=tickers).fillna(0.0)

    current = np.array([current_weights[t] for t in tickers], dtype=float)
    total = current.sum()
    current = current / total if total > 0 else np.array([1 / len(tickers)] * len(tickers))

    optimal = optimize(tickers, mean_returns, cov_matrix)
    equal = np.array([1 / len(tickers)] * len(tickers))

    strategies = {}
    for name, w in (('current', current), ('optimal', optimal), ('equal_weight', equal)):
        ret, risk, sharpe = stats(w, mean_returns, cov_matrix)
        strategies[name] = {
            'annual_return': round(ret * 100, 2),
            'annual_risk': round(risk * 100, 2),
            'sharpe': round(sharpe, 3),
            'weights': {t: round(float(x) * 100, 2) for t, x in zip(tickers, w)},
        }

    current_sharpe = strategies['current']['sharpe']
    improvement = (
        round((strategies['optimal']['sharpe'] / current_sharpe - 1) * 100, 1)
        if current_sharpe else 0.0
    )

    # Risk-return scatter for positions worth plotting.
    scatter = []
    for ticker, weight in zip(tickers, current):
        if weight > 0.01:
            ret = float(mean_returns.get(ticker, 0.0)) * TRADING_DAYS * 100
            risk = float(np.sqrt(cov_matrix.loc[ticker, ticker] * TRADING_DAYS)) * 100
            scatter.append({
                'ticker': ticker,
                'ret': round(ret, 2),
                'risk': round(risk, 2),
                'weight': round(float(weight) * 100, 2),
            })

    return {
        'available': True,
        'tickers': tickers,
        'strategies': strategies,
        'sharpe_improvement': improvement,
        'sensitivity': {
            'Current': strategies['current']['annual_return'],
            'Optimal': strategies['optimal']['annual_return'],
            'Equal Weight': strategies['equal_weight']['annual_return'],
        },
        'scatter': scatter,
        'max_position_pct': round(max(MAX_POSITION, 1.0 / len(tickers)) * 100, 1),
    }
