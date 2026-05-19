#!/usr/bin/env python3
"""
Portfolio core computation module.
Provides data fetching and calculation functions for the web app.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from scipy.optimize import minimize
from concurrent.futures import ThreadPoolExecutor
import warnings
warnings.filterwarnings('ignore')


def fetch_prices(tickers):
    """Fetch latest closing prices from Yahoo Finance."""
    if not tickers:
        return {}
    tickers = list(tickers)
    try:
        raw = yf.download(tickers, period='5d', progress=False, auto_adjust=True)
        if len(tickers) == 1:
            return {tickers[0]: float(raw['Close'].ffill().iloc[-1])}
        closes = raw['Close'].ffill()
        return {str(col): float(closes[col].iloc[-1]) for col in closes.columns}
    except Exception as e:
        print(f"fetch_prices error: {e}")
        return {}


def get_sectors(tickers):
    """Fetch GICS sector for each ticker in parallel via yfinance."""
    def _one(ticker):
        try:
            info = yf.Ticker(ticker).info
            return ticker, info.get('sector', 'Other')
        except Exception:
            return ticker, 'Other'

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(_one, tickers))
    return dict(results)


def calculate_portfolio(holdings, prices, purchase_prices):
    """Return per-position values, costs, gains, and portfolio totals."""
    values, costs, gains = {}, {}, {}
    for ticker, shares in holdings.items():
        price = prices.get(ticker, purchase_prices.get(ticker, 0))
        avg_cost = purchase_prices.get(ticker, price)
        value = shares * price
        cost = shares * avg_cost
        values[ticker] = value
        costs[ticker] = cost
        gains[ticker] = value - cost

    total_value = sum(values.values())
    total_cost = sum(costs.values())
    return {
        'values': values,
        'costs': costs,
        'gains': gains,
        'total_value': total_value,
        'total_cost': total_cost,
        'total_gain': total_value - total_cost,
    }


def fetch_historical_performance(holdings, period='1y'):
    """
    Return daily % returns for the portfolio vs SPY over the given period.
    Uses current share counts applied backwards — shows how these positions
    would have performed, not actual historical trades.
    """
    tickers = list(holdings.keys())
    all_tickers = tickers + ['SPY']
    try:
        raw = yf.download(all_tickers, period=period, progress=False, auto_adjust=True)

        if isinstance(raw.columns, pd.MultiIndex):
            data = raw['Close'].ffill()
        else:
            data = raw[['Close']].rename(columns={'Close': all_tickers[0]}).ffill()

        data = data.dropna(how='all')

        portfolio_values = pd.Series(0.0, index=data.index)
        for ticker, shares in holdings.items():
            if ticker in data.columns:
                portfolio_values += data[ticker].ffill() * shares

        # Drop leading zeros
        portfolio_values = portfolio_values[portfolio_values > 0]
        if portfolio_values.empty or 'SPY' not in data.columns:
            return {'dates': [], 'portfolio': [], 'spy': []}

        common_idx = portfolio_values.index.intersection(data.index)
        pv = portfolio_values.loc[common_idx]
        spy = data.loc[common_idx, 'SPY'].ffill()

        pv_pct = ((pv / pv.iloc[0]) - 1) * 100
        spy_pct = ((spy / spy.iloc[0]) - 1) * 100

        return {
            'dates': pv_pct.index.strftime('%Y-%m-%d').tolist(),
            'portfolio': [round(float(v), 2) for v in pv_pct],
            'spy': [round(float(v), 2) for v in spy_pct],
        }
    except Exception as e:
        print(f"fetch_historical_performance error: {e}")
        return {'dates': [], 'portfolio': [], 'spy': []}


def optimize_portfolio(tickers, mean_returns, cov_matrix):
    """Find weights maximizing Sharpe ratio via SLSQP (max 25% per position)."""
    n = len(tickers)
    mean_arr = np.array([mean_returns.get(t, 0) for t in tickers])
    cov_arr = cov_matrix.loc[tickers, tickers].values

    def neg_sharpe(w):
        ret = np.dot(mean_arr, w) * 252
        risk = np.sqrt(w @ cov_arr @ w * 252)
        return -(ret / risk) if risk > 1e-9 else 0.0

    result = minimize(
        neg_sharpe,
        x0=[1 / n] * n,
        method='SLSQP',
        bounds=[(0, 0.25)] * n,
        constraints={'type': 'eq', 'fun': lambda w: np.sum(w) - 1},
    )
    return result.x
