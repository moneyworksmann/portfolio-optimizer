#!/usr/bin/env python3
"""
Portfolio valuation: position values, cost basis, P&L, weights, sector split,
and realised performance against an equivalent SPY investment.

`calculate` and `performance_vs_benchmark` keep the arithmetic from
portfolio-optimizer (calculate_portfolio / fetch_historical_performance). The
difference is that prices now arrive from MarketData instead of each function
issuing its own download.

The weights produced here are the single source of truth for the whole request.
Pre-merge, the dashboard derived weights from a 5d price pull and PRISM derived
them independently from the last row of a 5y pull; the two could disagree on a
day when one feed lagged. Now the optimizer and PRISM both consume this dict.
"""

import pandas as pd

from .market_data import MarketData


def calculate(shares: dict, prices: dict, purchase_prices: dict) -> dict:
    """Per-position values, costs and gains, plus portfolio totals."""
    values, costs, gains = {}, {}, {}

    for ticker, qty in shares.items():
        price = prices.get(ticker, purchase_prices.get(ticker, 0.0))
        avg_cost = purchase_prices.get(ticker, price)
        value = qty * price
        cost = qty * avg_cost
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


def resolve_prices(md: MarketData, shares: dict, purchase_prices: dict) -> tuple:
    """Fill gaps both ways: live price falls back to cost, missing cost to price.

    Same fallback ladder the Flask route used, so a ticker with no live quote
    still appears in the table at 0% gain rather than vanishing.
    """
    prices = dict(md.latest)
    purchase = dict(purchase_prices)

    for ticker in shares:
        if ticker not in prices:
            prices[ticker] = purchase.get(ticker, 0.0)
    for ticker in shares:
        if ticker not in purchase:
            purchase[ticker] = prices[ticker]

    return prices, purchase


def weights_from(book: dict) -> dict:
    """Market-value weights (fractions, summing to 1.0)."""
    total = book['total_value']
    if not total:
        return {t: 0.0 for t in book['values']}
    return {t: v / total for t, v in book['values'].items()}


def sector_allocation(book: dict, sectors: dict) -> dict:
    """Dollar value per sector."""
    alloc: dict = {}
    for ticker, value in book['values'].items():
        sector = sectors.get(ticker, 'Other')
        alloc[sector] = alloc.get(sector, 0.0) + value
    return alloc


def holdings_detail(shares, prices, purchase_prices, book, sectors) -> list:
    """Rows for the holdings table, largest position first."""
    total_value = book['total_value']
    rows = []

    for ticker, qty in shares.items():
        value = book['values'][ticker]
        cost = book['costs'][ticker]
        gain = book['gains'][ticker]

        rows.append({
            'ticker': ticker,
            'shares': qty,
            'avg_cost': round(purchase_prices.get(ticker, 0.0), 2),
            'current_price': round(prices.get(ticker, 0.0), 2),
            'value': round(value, 2),
            'gain': round(gain, 2),
            'gain_pct': round((gain / cost * 100) if cost else 0.0, 2),
            'weight': round((value / total_value * 100) if total_value else 0.0, 2),
            'sector': sectors.get(ticker, 'Other'),
        })

    rows.sort(key=lambda r: r['value'], reverse=True)
    return rows


def performance_vs_benchmark(md: MarketData, shares: dict, purchase_prices: dict,
                             days: int = 252, max_points: int = 80) -> dict:
    """Actual dollar P&L against the same cost basis invested in SPY.

    Deliberately not a normalised backtest: it tracks what the holdings are worth
    each day versus what SPY would have been worth if the identical cost basis had
    gone in at the start of the window.
    """
    empty = {'dates': [], 'portfolio': [], 'spy': [],
             'portfolio_value': [], 'spy_value': [], 'total_cost': 0}

    if md.closes.empty or md.benchmark_closes.empty:
        return empty

    window = md.closes.tail(days)
    if window.empty:
        return empty

    position_values = pd.Series(0.0, index=window.index)
    for ticker, qty in shares.items():
        if ticker in window.columns:
            position_values += window[ticker].ffill() * qty

    position_values = position_values[position_values > 0]
    if position_values.empty:
        return empty

    spy_prices = window.loc[position_values.index, md.BENCHMARK].ffill()

    total_cost = sum(qty * purchase_prices.get(t, 0.0) for t, qty in shares.items())
    if total_cost <= 0:
        total_cost = float(position_values.iloc[0])

    spy_start = float(spy_prices.iloc[0])
    if spy_start <= 0:
        return empty

    spy_values = spy_prices * (total_cost / spy_start)

    portfolio_pnl = ((position_values - total_cost) / total_cost) * 100
    spy_pnl = ((spy_values - total_cost) / total_cost) * 100

    # Downsample so the chart payload stays small regardless of window length.
    step = max(1, len(position_values) // max_points)

    return {
        'dates': position_values.index.strftime('%Y-%m-%d').tolist()[::step],
        'portfolio': [round(float(v), 2) for v in portfolio_pnl][::step],
        'spy': [round(float(v), 2) for v in spy_pnl][::step],
        'portfolio_value': [round(float(v), 2) for v in position_values][::step],
        'spy_value': [round(float(v), 2) for v in spy_values][::step],
        'total_cost': round(total_cost, 2),
    }
