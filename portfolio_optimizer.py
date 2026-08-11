#!/usr/bin/env python3
"""
Portfolio Optimizer & Dashboard Generator
Fetches real-time prices, performs optimization, and generates an HTML dashboard.
Also provides shared functions for the Flask web app.
"""

import json
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.optimize import minimize

import warnings
warnings.filterwarnings('ignore')

# ============ CONFIGURATION ============

SECTORS = {
    'IWM': 'Diversified', 'AAPL': 'Technology', 'AMZN': 'Consumer', 'JEPI': 'Fixed Income',
    'SLG': 'Real Estate', 'ORCL': 'Technology', 'MSFT': 'Technology', 'C': 'Financials',
    'JPM': 'Financials', 'MU': 'Technology', 'WBD': 'Consumer', 'LYG': 'Financials',
    'BAC': 'Financials', 'DAL': 'Industrials', 'NVDA': 'Technology', 'WMT': 'Consumer',
    'NTGR': 'Technology', 'T': 'Utilities'
}

HOLDINGS = {
    'IWM': 0.379, 'AAPL': 0.023, 'AMZN': 0.02, 'JEPI': 0.841,
    'SLG': 1, 'ORCL': 1, 'MSFT': 0.8, 'C': 1,
    'JPM': 1, 'MU': 0.55, 'WBD': 5, 'LYG': 10,
    'BAC': 1, 'DAL': 1, 'NVDA': 1, 'WMT': 1,
    'NTGR': 1, 'T': 1
}

PURCHASE_PRICES = {
    'IWM': 263.83, 'AAPL': 255.87, 'AMZN': 248.20, 'JEPI': 59.46,
    'SLG': 43.39, 'ORCL': 175.84, 'MSFT': 326.38, 'C': 95.95,
    'JPM': 304.68, 'MU': 153.54, 'WBD': 27.75, 'LYG': 3.70,
    'BAC': 45.88, 'DAL': 43.81, 'NVDA': 126.56, 'WMT': 66.99,
    'NTGR': 14.27, 'T': 16.49
}

HTML_OUTPUT = 'Portfolio_Dashboard.html'

# ============ SHARED FUNCTIONS (used by web app) ============

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


def fetch_historical_performance(holdings, purchase_prices=None, period='1y'):
    """Return actual portfolio P&L vs equivalent SPY investment over the period.

    Instead of hypothetical normalized returns, this tracks:
    - Portfolio: actual dollar value of holdings each day
    - SPY: what the same total cost basis would be worth if invested in SPY
    - P&L for both relative to the total cost basis
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

        portfolio_values = portfolio_values[portfolio_values > 0]
        if portfolio_values.empty or 'SPY' not in data.columns:
            return {'dates': [], 'portfolio': [], 'spy': [],
                    'portfolio_value': [], 'spy_value': [], 'total_cost': 0}

        common_idx = portfolio_values.index.intersection(data.index)
        pv = portfolio_values.loc[common_idx]
        spy_prices = data.loc[common_idx, 'SPY'].ffill()

        total_cost = 0.0
        if purchase_prices:
            for ticker, shares in holdings.items():
                avg = purchase_prices.get(ticker, 0)
                total_cost += shares * avg

        if total_cost <= 0:
            total_cost = float(pv.iloc[0])

        spy_start_price = float(spy_prices.iloc[0])
        spy_shares = total_cost / spy_start_price
        spy_values = spy_prices * spy_shares

        portfolio_pnl = ((pv - total_cost) / total_cost) * 100
        spy_pnl = ((spy_values - total_cost) / total_cost) * 100

        return {
            'dates': pv.index.strftime('%Y-%m-%d').tolist(),
            'portfolio': [round(float(v), 2) for v in portfolio_pnl],
            'spy': [round(float(v), 2) for v in spy_pnl],
            'portfolio_value': [round(float(v), 2) for v in pv],
            'spy_value': [round(float(v), 2) for v in spy_values],
            'total_cost': round(total_cost, 2),
        }
    except Exception as e:
        print(f"fetch_historical_performance error: {e}")
        return {'dates': [], 'portfolio': [], 'spy': [],
                'portfolio_value': [], 'spy_value': [], 'total_cost': 0}


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


# ============ HTML REPORT GENERATION ============

def _portfolio_stats(weights, mean_returns, cov_matrix):
    ret = np.sum(mean_returns * weights) * 252
    risk = np.sqrt(np.dot(weights.T, np.dot(cov_matrix * 252, weights)))
    sharpe = ret / risk if risk > 0 else 0
    return ret, risk, sharpe


def generate_html_report(portfolio_data, prices, current_weights, optimal_weights,
                         tickers, mean_returns, cov_matrix, hist_data, sectors,
                         performance=None):
    """Generate a self-contained HTML dashboard with interactive charts."""

    # --- Build data payloads for JS ---
    # Sector allocation
    sector_values = {}
    for ticker, value in portfolio_data['values'].items():
        s = sectors.get(ticker, 'Other')
        sector_values[s] = round(sector_values.get(s, 0) + value, 2)

    # Current vs optimal (top 10)
    current_sorted = sorted(zip(tickers, current_weights), key=lambda x: x[1], reverse=True)[:10]
    optimal_sorted = sorted(zip(tickers, optimal_weights), key=lambda x: x[1], reverse=True)[:10]

    # Individual stock growth (top 8)
    cumulative = (hist_data / hist_data.iloc[0] - 1) * 100
    step = max(1, len(cumulative) // 80)
    growth_dates = cumulative.index[::step].strftime('%Y-%m-%d').tolist()
    growth_series = {}
    for ticker in tickers[:8]:
        if ticker in cumulative.columns:
            growth_series[ticker] = [round(float(v), 2) for v in cumulative[ticker].iloc[::step]]

    # Actual portfolio vs SPY performance
    if performance is None:
        performance = {'dates': [], 'portfolio': [], 'spy': [],
                       'portfolio_value': [], 'spy_value': [], 'total_cost': 0}
    perf_step = max(1, len(performance['dates']) // 80)
    perf_data = {
        'dates': performance['dates'][::perf_step],
        'portfolio': performance['portfolio'][::perf_step],
        'spy': performance['spy'][::perf_step],
        'portfolio_value': performance.get('portfolio_value', [])[::perf_step],
        'spy_value': performance.get('spy_value', [])[::perf_step],
        'total_cost': performance.get('total_cost', 0),
    }

    # Sensitivity analysis
    scenarios = {
        'Current': current_weights,
        'Optimal': optimal_weights,
        'Equal Weight': np.array([1 / len(tickers)] * len(tickers)),
    }
    scenario_returns = {name: round(float(np.sum(mean_returns * w) * 252 * 100), 2)
                        for name, w in scenarios.items()}

    # Risk-return scatter
    scatter_points = []
    for ticker, weight in zip(tickers, current_weights):
        if weight > 0.01:
            ret = float(mean_returns.get(ticker, 0)) * 252 * 100
            risk = float(np.sqrt(cov_matrix.loc[ticker, ticker] * 252)) * 100
            scatter_points.append({
                'ticker': ticker, 'ret': round(ret, 2),
                'risk': round(risk, 2), 'weight': round(float(weight) * 100, 2)
            })

    # Holdings table
    holdings_rows = []
    for ticker, weight in zip(tickers, current_weights):
        value = portfolio_data['values'][ticker]
        cost = portfolio_data['costs'][ticker]
        gain = portfolio_data['gains'][ticker]
        gain_pct = (gain / cost * 100) if cost else 0
        holdings_rows.append({
            'ticker': ticker,
            'sector': sectors.get(ticker, 'Other'),
            'shares': HOLDINGS[ticker],
            'avg_cost': round(PURCHASE_PRICES[ticker], 2),
            'price': round(prices.get(ticker, 0), 2),
            'value': round(value, 2),
            'gain': round(gain, 2),
            'gain_pct': round(gain_pct, 2),
            'weight': round(float(weight) * 100, 2),
        })
    holdings_rows.sort(key=lambda x: x['value'], reverse=True)

    # Portfolio stats
    c_ret, c_risk, c_sharpe = _portfolio_stats(current_weights, mean_returns, cov_matrix)
    o_ret, o_risk, o_sharpe = _portfolio_stats(optimal_weights, mean_returns, cov_matrix)

    data_payload = json.dumps({
        'summary': {
            'total_value': round(portfolio_data['total_value'], 2),
            'total_cost': round(portfolio_data['total_cost'], 2),
            'total_gain': round(portfolio_data['total_gain'], 2),
            'total_gain_pct': round(portfolio_data['total_gain'] / portfolio_data['total_cost'] * 100, 2),
            'positions': len(tickers),
        },
        'metrics': {
            'current': {'ret': round(c_ret * 100, 2), 'risk': round(c_risk * 100, 2), 'sharpe': round(c_sharpe, 2)},
            'optimal': {'ret': round(o_ret * 100, 2), 'risk': round(o_risk * 100, 2), 'sharpe': round(o_sharpe, 2)},
            'sharpe_improvement': round((o_sharpe / c_sharpe - 1) * 100, 1) if c_sharpe else 0,
        },
        'sector_allocation': sector_values,
        'current_alloc': {'labels': [t[0] for t in current_sorted], 'values': [round(t[1] * 100, 2) for t in current_sorted]},
        'optimal_alloc': {'labels': [t[0] for t in optimal_sorted], 'values': [round(t[1] * 100, 2) for t in optimal_sorted]},
        'growth': {'dates': growth_dates, 'series': growth_series},
        'performance': perf_data,
        'sensitivity': scenario_returns,
        'scatter': scatter_points,
        'holdings': holdings_rows,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    })

    html = _build_html(data_payload)

    with open(HTML_OUTPUT, 'w') as f:
        f.write(html)

    return HTML_OUTPUT


def _build_html(data_payload):
    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Portfolio Optimization Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#07090f;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;font-size:14px;line-height:1.5;min-height:100vh}}
header{{background:#0e1320;border-bottom:1px solid #1c2d45;padding:16px 24px;position:sticky;top:0;z-index:200}}
.header-inner{{max-width:1360px;margin:0 auto;display:flex;align-items:center;justify-content:space-between}}
.logo{{display:flex;align-items:center;gap:10px;font-size:17px;font-weight:700}}
.timestamp{{color:#94a3b8;font-size:12px}}
.container{{max-width:1360px;margin:0 auto;padding:28px 24px 60px}}
.cards-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:20px}}
.card{{background:#0e1320;border:1px solid #1c2d45;border-radius:10px;padding:20px}}
.kpi-label{{font-size:11px;text-transform:uppercase;letter-spacing:.6px;color:#94a3b8;margin-bottom:8px}}
.kpi-val{{font-size:26px;font-weight:700}}
.kpi-sub{{font-size:13px;color:#94a3b8;margin-top:4px}}
.section-title{{font-size:16px;font-weight:700;margin-bottom:16px;margin-top:28px}}
.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:20px}}
.chart-card h3{{font-size:14px;font-weight:600;margin-bottom:14px}}
.chart-box{{position:relative;height:300px}}
.metrics-grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:20px}}
.metric-card{{padding:20px}}
.metric-card h3{{font-size:14px;font-weight:600;margin-bottom:12px;color:#94a3b8}}
.metric-row{{display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid rgba(28,45,69,.5)}}
.metric-row:last-child{{border-bottom:none}}
.metric-label{{color:#94a3b8;font-size:13px}}
.metric-value{{font-weight:600;font-size:13px}}
.green{{color:#10b981}}.red{{color:#ef4444}}
.tbl-wrap{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;padding:9px 12px;color:#94a3b8;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid #1c2d45;white-space:nowrap}}
td{{padding:11px 12px;border-bottom:1px solid rgba(28,45,69,.6);white-space:nowrap}}
tr:last-child td{{border-bottom:none}}
tbody tr:hover td{{background:rgba(255,255,255,.02)}}
.sect{{font-size:11px;padding:2px 7px;border-radius:20px;background:#151d2e;color:#94a3b8}}
.badge{{font-size:10px;font-weight:500;background:#151d2e;border:1px solid #1c2d45;border-radius:4px;padding:2px 6px;color:#94a3b8;vertical-align:middle}}
@media(max-width:900px){{.cards-grid,.two-col,.metrics-grid{{grid-template-columns:1fr 1fr}}.two-col{{grid-template-columns:1fr}}}}
@media(max-width:520px){{.cards-grid{{grid-template-columns:1fr 1fr}}.kpi-val{{font-size:20px}}}}
@media print{{body{{background:#fff;color:#111}}header{{background:#f8f9fa;border-color:#ddd}}.card,.chart-card{{background:#fff;border-color:#ddd}}.kpi-label,.metric-label,.timestamp{{color:#666}}th{{color:#666}}td{{border-color:#eee}}.sect{{background:#f0f0f0;color:#555}}}}
</style>
</head>
<body>
<header>
<div class="header-inner">
<div class="logo"><span>&#128200;</span> Portfolio Optimization Dashboard</div>
<span class="timestamp" id="ts"></span>
</div>
</header>
<div class="container">

<!-- KPI Cards -->
<div class="cards-grid">
<div class="card"><div class="kpi-label">Total Value</div><div class="kpi-val" id="kpi-value"></div></div>
<div class="card"><div class="kpi-label">Total Cost</div><div class="kpi-val" id="kpi-cost"></div></div>
<div class="card"><div class="kpi-label">Total P&amp;L</div><div class="kpi-val" id="kpi-gain"></div><div class="kpi-sub" id="kpi-gain-pct"></div></div>
<div class="card"><div class="kpi-label">Positions</div><div class="kpi-val" id="kpi-count"></div></div>
</div>

<!-- Portfolio Metrics -->
<div class="metrics-grid">
<div class="card metric-card">
<h3>Current Portfolio Metrics</h3>
<div class="metric-row"><span class="metric-label">Annual Return</span><span class="metric-value" id="m-c-ret"></span></div>
<div class="metric-row"><span class="metric-label">Volatility</span><span class="metric-value" id="m-c-risk"></span></div>
<div class="metric-row"><span class="metric-label">Sharpe Ratio</span><span class="metric-value" id="m-c-sharpe"></span></div>
</div>
<div class="card metric-card">
<h3>Optimal Portfolio Metrics</h3>
<div class="metric-row"><span class="metric-label">Annual Return</span><span class="metric-value" id="m-o-ret"></span></div>
<div class="metric-row"><span class="metric-label">Volatility</span><span class="metric-value" id="m-o-risk"></span></div>
<div class="metric-row"><span class="metric-label">Sharpe Ratio</span><span class="metric-value" id="m-o-sharpe"></span></div>
<div class="metric-row"><span class="metric-label">Sharpe Improvement</span><span class="metric-value green" id="m-improve"></span></div>
</div>
</div>

<!-- Row 1: Sector + Allocation -->
<div class="two-col">
<div class="card chart-card"><h3>Sector Allocation</h3><div class="chart-box"><canvas id="chart-sector"></canvas></div></div>
<div class="card chart-card"><h3>Current vs Optimal Allocation (Top 10)</h3><div class="chart-box"><canvas id="chart-alloc"></canvas></div></div>
</div>

<!-- Row 2: Actual Performance vs SPY -->
<div class="two-col">
<div class="card chart-card"><h3>Actual Portfolio P&amp;L vs SPY &nbsp;<span class="badge">1 Year</span></h3><div class="chart-box"><canvas id="chart-perf"></canvas></div></div>
<div class="card chart-card"><h3>Actual Portfolio Value vs SPY &nbsp;<span class="badge">Dollar Value</span></h3><div class="chart-box"><canvas id="chart-perf-dollar"></canvas></div></div>
</div>

<!-- Row 3: Growth + Sensitivity -->
<div class="two-col">
<div class="card chart-card"><h3>Individual Stock Performance (1 Year) &nbsp;<span class="badge">Top 8</span></h3><div class="chart-box"><canvas id="chart-growth"></canvas></div></div>
<div class="card chart-card"><h3>Sensitivity Analysis: Expected Annual Return</h3><div class="chart-box"><canvas id="chart-sensitivity"></canvas></div></div>
</div>

<!-- Row 4: Risk-Return Scatter -->
<div class="two-col">
<div class="card chart-card"><h3>Risk-Return Profile &nbsp;<span class="badge">bubble size = weight</span></h3><div class="chart-box"><canvas id="chart-scatter"></canvas></div></div>
<div class="card chart-card" style="display:flex;align-items:center;justify-content:center;flex-direction:column;gap:12px">
<h3 style="margin-bottom:8px">Report Summary</h3>
<p style="color:#94a3b8;font-size:13px;text-align:center;max-width:320px">This dashboard was generated by the Portfolio Optimizer script using live data from Yahoo Finance. Re-run the script to refresh with the latest prices.</p>
<p style="color:#94a3b8;font-size:12px;margin-top:8px" id="report-ts"></p>
</div>
</div>

<!-- Holdings Table -->
<div class="card" style="margin-top:20px">
<h3 style="font-size:14px;font-weight:600;margin-bottom:14px">All Positions</h3>
<div class="tbl-wrap">
<table>
<thead><tr>
<th>Ticker</th><th>Sector</th><th>Shares</th><th>Avg Cost</th><th>Price</th><th>Value</th><th>P&amp;L ($)</th><th>P&amp;L (%)</th><th>Weight</th>
</tr></thead>
<tbody id="tbody-holdings"></tbody>
</table>
</div>
</div>

</div>

<script>
const D = {data_payload};

const PALETTE = ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#06b6d4','#f97316','#84cc16','#ec4899','#14b8a6','#a855f7','#eab308','#6366f1','#22d3ee','#fb923c'];

function fmtUSD(n) {{ return '$' + (+n).toLocaleString('en-US', {{minimumFractionDigits:2, maximumFractionDigits:2}}); }}
function fmtGain(n) {{ var a = Math.abs(n).toLocaleString('en-US', {{minimumFractionDigits:2, maximumFractionDigits:2}}); return (n >= 0 ? '+$' : '-$') + a; }}
function fmtPct(n) {{ return (n >= 0 ? '+' : '') + (+n).toFixed(2) + '%'; }}
function cc(n) {{ return n >= 0 ? 'green' : 'red'; }}
function ctx(id) {{ return document.getElementById(id).getContext('2d'); }}

// KPIs
document.getElementById('kpi-value').textContent = fmtUSD(D.summary.total_value);
document.getElementById('kpi-cost').textContent = fmtUSD(D.summary.total_cost);
var ge = document.getElementById('kpi-gain');
ge.textContent = fmtGain(D.summary.total_gain);
ge.className = 'kpi-val ' + cc(D.summary.total_gain);
var gp = document.getElementById('kpi-gain-pct');
gp.textContent = fmtPct(D.summary.total_gain_pct);
gp.className = 'kpi-sub ' + cc(D.summary.total_gain_pct);
document.getElementById('kpi-count').textContent = D.summary.positions;
document.getElementById('ts').textContent = 'Generated: ' + D.timestamp;
document.getElementById('report-ts').textContent = 'Generated: ' + D.timestamp;

// Metrics
document.getElementById('m-c-ret').textContent = D.metrics.current.ret.toFixed(2) + '%';
document.getElementById('m-c-risk').textContent = D.metrics.current.risk.toFixed(2) + '%';
document.getElementById('m-c-sharpe').textContent = D.metrics.current.sharpe.toFixed(2);
document.getElementById('m-o-ret').textContent = D.metrics.optimal.ret.toFixed(2) + '%';
document.getElementById('m-o-risk').textContent = D.metrics.optimal.risk.toFixed(2) + '%';
document.getElementById('m-o-sharpe').textContent = D.metrics.optimal.sharpe.toFixed(2);
document.getElementById('m-improve').textContent = '+' + D.metrics.sharpe_improvement + '%';

// 1. Sector doughnut
new Chart(ctx('chart-sector'), {{
  type: 'doughnut',
  data: {{
    labels: Object.keys(D.sector_allocation),
    datasets: [{{ data: Object.values(D.sector_allocation), backgroundColor: PALETTE, borderColor: '#0e1320', borderWidth: 2 }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{
      legend: {{ position: 'right', labels: {{ color: '#94a3b8', font: {{ size: 11 }}, padding: 10 }} }},
      tooltip: {{ callbacks: {{ label: function(c) {{ var t = Object.values(D.sector_allocation).reduce(function(a,b){{return a+b}},0); return ' ' + c.label + ': ' + ((c.raw/t)*100).toFixed(1) + '%  (' + fmtUSD(c.raw) + ')'; }} }} }}
    }}
  }}
}});

// 2. Current vs Optimal allocation
new Chart(ctx('chart-alloc'), {{
  type: 'bar',
  data: {{
    labels: D.current_alloc.labels,
    datasets: [
      {{ label: 'Current', data: D.current_alloc.values, backgroundColor: 'rgba(239,68,68,.7)', borderColor: '#ef4444', borderWidth: 1, borderRadius: 4 }},
      {{ label: 'Optimal', data: D.optimal_alloc.values, backgroundColor: 'rgba(16,185,129,.7)', borderColor: '#10b981', borderWidth: 1, borderRadius: 4 }}
    ]
  }},
  options: {{
    indexAxis: 'y', responsive: true, maintainAspectRatio: false,
    plugins: {{
      legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 12 }} }} }},
      tooltip: {{ callbacks: {{ label: function(c){{ return ' ' + c.dataset.label + ': ' + c.raw.toFixed(2) + '%'; }} }} }}
    }},
    scales: {{
      x: {{ grid: {{ color: '#1c2d45' }}, ticks: {{ color: '#94a3b8', callback: function(v){{ return v + '%'; }} }} }},
      y: {{ grid: {{ display: false }}, ticks: {{ color: '#e2e8f0', font: {{ weight: '600' }} }} }}
    }}
  }}
}});

// 3. Actual Portfolio P&L vs SPY (percentage)
(function() {{
  if (!D.performance || !D.performance.dates || !D.performance.dates.length) return;
  var dates = D.performance.dates.map(function(d){{ var dt = new Date(d); return dt.toLocaleDateString('en-US', {{month:'short',day:'numeric'}}); }});
  new Chart(ctx('chart-perf'), {{
    type: 'line',
    data: {{
      labels: dates,
      datasets: [
        {{
          label: 'My Portfolio P&L',
          data: D.performance.portfolio,
          borderColor: '#3b82f6',
          backgroundColor: 'rgba(59,130,246,.08)',
          fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2.5,
        }},
        {{
          label: 'SPY (Same Investment)',
          data: D.performance.spy,
          borderColor: '#94a3b8',
          borderDash: [5, 4],
          fill: false, tension: 0.3, pointRadius: 0, borderWidth: 1.5,
        }},
      ],
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 12 }}, boxWidth: 16 }} }},
        tooltip: {{ callbacks: {{ label: function(c) {{ return ' ' + c.dataset.label + ': ' + (c.raw >= 0 ? '+' : '') + c.raw.toFixed(2) + '%'; }} }} }},
      }},
      scales: {{
        x: {{ grid: {{ color: '#1c2d45' }}, ticks: {{ color: '#94a3b8', maxTicksLimit: 8 }} }},
        y: {{ grid: {{ color: '#1c2d45' }}, ticks: {{ color: '#94a3b8', callback: function(v){{ return (v>=0?'+':'') + v.toFixed(1) + '%'; }} }} }},
      }},
    }},
  }});
}})();

// 3b. Actual Portfolio Value vs SPY (dollar)
(function() {{
  if (!D.performance || !D.performance.dates || !D.performance.dates.length) return;
  var dates = D.performance.dates.map(function(d){{ var dt = new Date(d); return dt.toLocaleDateString('en-US', {{month:'short',day:'numeric'}}); }});
  var costLine = D.performance.portfolio_value.map(function(){{ return D.performance.total_cost; }});
  new Chart(ctx('chart-perf-dollar'), {{
    type: 'line',
    data: {{
      labels: dates,
      datasets: [
        {{
          label: 'Portfolio Value',
          data: D.performance.portfolio_value,
          borderColor: '#3b82f6',
          backgroundColor: 'rgba(59,130,246,.08)',
          fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2.5,
        }},
        {{
          label: 'If Invested in SPY',
          data: D.performance.spy_value,
          borderColor: '#f59e0b',
          borderDash: [5, 4],
          fill: false, tension: 0.3, pointRadius: 0, borderWidth: 1.5,
        }},
        {{
          label: 'Total Cost Basis',
          data: costLine,
          borderColor: '#ef4444',
          borderDash: [2, 3],
          fill: false, tension: 0, pointRadius: 0, borderWidth: 1,
        }},
      ],
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 12 }}, boxWidth: 16 }} }},
        tooltip: {{ callbacks: {{ label: function(c) {{ return ' ' + c.dataset.label + ': ' + fmtUSD(c.raw); }} }} }},
      }},
      scales: {{
        x: {{ grid: {{ color: '#1c2d45' }}, ticks: {{ color: '#94a3b8', maxTicksLimit: 8 }} }},
        y: {{ grid: {{ color: '#1c2d45' }}, ticks: {{ color: '#94a3b8', callback: function(v){{ return '$' + v.toLocaleString(); }} }} }},
      }},
    }},
  }});
}})();

// 4. Individual stock growth
(function() {{
  var datasets = [];
  var i = 0;
  for (var ticker in D.growth.series) {{
    datasets.push({{
      label: ticker,
      data: D.growth.series[ticker],
      borderColor: PALETTE[i % PALETTE.length],
      fill: false, tension: 0.3, pointRadius: 0, borderWidth: 2
    }});
    i++;
  }}
  new Chart(ctx('chart-growth'), {{
    type: 'line',
    data: {{ labels: D.growth.dates.map(function(d){{ var dt = new Date(d); return dt.toLocaleDateString('en-US', {{month:'short',day:'numeric'}}); }}), datasets: datasets }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 11 }}, boxWidth: 14 }} }},
        tooltip: {{ callbacks: {{ label: function(c){{ return ' ' + c.dataset.label + ': ' + (c.raw >= 0 ? '+' : '') + c.raw.toFixed(2) + '%'; }} }} }}
      }},
      scales: {{
        x: {{ grid: {{ color: '#1c2d45' }}, ticks: {{ color: '#94a3b8', maxTicksLimit: 8 }} }},
        y: {{ grid: {{ color: '#1c2d45' }}, ticks: {{ color: '#94a3b8', callback: function(v){{ return (v>=0?'+':'') + v.toFixed(1) + '%'; }} }} }}
      }}
    }}
  }});
}})();

// 4. Sensitivity
new Chart(ctx('chart-sensitivity'), {{
  type: 'bar',
  data: {{
    labels: Object.keys(D.sensitivity),
    datasets: [{{
      data: Object.values(D.sensitivity),
      backgroundColor: ['rgba(239,68,68,.7)','rgba(16,185,129,.7)','rgba(59,130,246,.7)'],
      borderColor: ['#ef4444','#10b981','#3b82f6'],
      borderWidth: 1, borderRadius: 6
    }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{ callbacks: {{ label: function(c){{ return ' ' + c.raw.toFixed(2) + '%'; }} }} }}
    }},
    scales: {{
      x: {{ grid: {{ display: false }}, ticks: {{ color: '#e2e8f0', font: {{ weight: '600' }} }} }},
      y: {{ grid: {{ color: '#1c2d45' }}, ticks: {{ color: '#94a3b8', callback: function(v){{ return v + '%'; }} }} }}
    }}
  }}
}});

// 5. Risk-Return scatter
new Chart(ctx('chart-scatter'), {{
  type: 'bubble',
  data: {{
    datasets: D.scatter.map(function(p, i) {{
      return {{
        label: p.ticker,
        data: [{{ x: p.risk, y: p.ret, r: Math.max(p.weight * 1.5, 4) }}],
        backgroundColor: PALETTE[i % PALETTE.length] + 'aa',
        borderColor: PALETTE[i % PALETTE.length],
        borderWidth: 1.5
      }};
    }})
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{
      legend: {{ labels: {{ color: '#94a3b8', font: {{ size: 10 }}, boxWidth: 10 }} }},
      tooltip: {{ callbacks: {{ label: function(c){{ var d = c.raw; return ' ' + c.dataset.label + ': Return ' + d.y.toFixed(1) + '%, Risk ' + d.x.toFixed(1) + '%'; }} }} }}
    }},
    scales: {{
      x: {{ title: {{ display: true, text: 'Risk (Volatility %)', color: '#94a3b8' }}, grid: {{ color: '#1c2d45' }}, ticks: {{ color: '#94a3b8' }} }},
      y: {{ title: {{ display: true, text: 'Return (Annual %)', color: '#94a3b8' }}, grid: {{ color: '#1c2d45' }}, ticks: {{ color: '#94a3b8' }} }}
    }}
  }}
}});

// Holdings table
var tbody = document.getElementById('tbody-holdings');
D.holdings.forEach(function(h) {{
  var tr = document.createElement('tr');
  tr.innerHTML =
    '<td><strong>' + h.ticker + '</strong></td>' +
    '<td><span class="sect">' + h.sector + '</span></td>' +
    '<td>' + h.shares + '</td>' +
    '<td>' + fmtUSD(h.avg_cost) + '</td>' +
    '<td>' + fmtUSD(h.price) + '</td>' +
    '<td>' + fmtUSD(h.value) + '</td>' +
    '<td class="' + cc(h.gain) + '">' + fmtGain(h.gain) + '</td>' +
    '<td class="' + cc(h.gain_pct) + '">' + fmtPct(h.gain_pct) + '</td>' +
    '<td>' + h.weight.toFixed(2) + '%</td>';
  tbody.appendChild(tr);
}});
</script>
</body>
</html>'''


# ============ STANDALONE ENTRY POINT ============

def main():
    print("\n" + "=" * 60)
    print("  PORTFOLIO OPTIMIZER & DASHBOARD GENERATOR")
    print("=" * 60)

    tickers = list(HOLDINGS.keys())

    # Fetch prices
    print("\nFetching real-time prices from Yahoo Finance...")
    prices = fetch_prices(tickers)
    if not prices:
        print("Live prices unavailable, using purchase prices as fallback.")
        prices = PURCHASE_PRICES.copy()
    else:
        print("Prices fetched successfully.")

    for t in tickers:
        if t not in prices:
            prices[t] = PURCHASE_PRICES[t]

    # Calculate portfolio
    portfolio_data = calculate_portfolio(HOLDINGS, prices, PURCHASE_PRICES)
    total_gain_pct = (portfolio_data['total_gain'] / portfolio_data['total_cost'] * 100)
    print(f"\nPortfolio Value: ${portfolio_data['total_value']:,.2f}")
    print(f"Total Gain: ${portfolio_data['total_gain']:,.2f} ({total_gain_pct:.2f}%)")

    # Historical data for optimization
    print("\nFetching historical data for optimization...")
    try:
        raw = yf.download(tickers, period='1y', progress=False, auto_adjust=True)
        if isinstance(raw.columns, pd.MultiIndex):
            hist_data = raw['Close'].ffill()
        else:
            hist_data = raw[['Close']].rename(columns={'Close': tickers[0]}).ffill()
        returns = hist_data.pct_change().dropna()
        mean_returns = returns.mean()
        cov_matrix = returns.cov()
    except Exception as e:
        print(f"Using mock historical data: {e}")
        mean_returns = pd.Series({t: 0.001 for t in tickers})
        cov_matrix = pd.DataFrame(np.eye(len(tickers)) * 0.0004, index=tickers, columns=tickers)
        hist_data = pd.DataFrame(np.random.randn(252, len(tickers)), columns=tickers).cumsum() + 100

    # Weights
    current_weights = np.array([
        portfolio_data['values'][t] / portfolio_data['total_value'] for t in tickers
    ])

    print("Running portfolio optimization...")
    optimal_weights = optimize_portfolio(tickers, mean_returns, cov_matrix)

    # Actual performance comparison
    print("Calculating actual portfolio performance vs SPY...")
    performance = fetch_historical_performance(HOLDINGS, PURCHASE_PRICES)

    # Generate HTML
    print("\nGenerating HTML dashboard...")
    output = generate_html_report(
        portfolio_data, prices, current_weights, optimal_weights,
        tickers, mean_returns, cov_matrix, hist_data, SECTORS,
        performance=performance,
    )

    print(f"\nDashboard saved: {output}")
    print("\n" + "=" * 60)
    print("  PORTFOLIO UPDATE COMPLETE!")
    print("=" * 60)
    print(f"\nYour dashboard includes:")
    print("  - Real-time prices from Yahoo Finance")
    print("  - Actual portfolio P&L vs SPY comparison")
    print("  - Portfolio optimization analysis")
    print("  - Sector concentration chart")
    print("  - Current vs optimal allocation")
    print("  - Individual stock performance (1 year)")
    print("  - Sensitivity analysis")
    print("  - Risk-return profile")
    print("  - Full holdings table")
    print(f"\nOpening {output} in your browser...")

    webbrowser.open(output)


if __name__ == '__main__':
    main()
