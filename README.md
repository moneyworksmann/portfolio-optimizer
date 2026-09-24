# Portfolio Optimizer

A Flask web app that analyses a stock portfolio. You upload your holdings and it values them at live prices, calculates the allocation with the best risk-adjusted return (maximum Sharpe ratio), and gives the portfolio a 0–100 risk score called **PRISM**.

The app lives in [`portfolio-intelligence/`](portfolio-intelligence/). Its [README](portfolio-intelligence/README.md) explains the methods, the data layer and the API.

## What it does

- **Import holdings** from a brokerage CSV (Fidelity, Schwab, Robinhood and Vanguard formats), from a screenshot read with OCR, or by typing them in.
- **Value** each position: market value, cost basis, unrealised P&L, weight and sector split. Performance is compared with what the same money would be worth if it had gone into SPY.
- **Optimise** the allocation using Markowitz mean-variance on one year of daily returns. There's no shorting, the whole portfolio stays invested, and no stock can exceed 25%. The result is shown next to your current allocation and an equal-weight portfolio.
- **Score** the portfolio with PRISM on four risks: sector diversification, correlation between holdings, volatility, and concentration in one stock. It also names your weakest area in plain English.

## Run it

```bash
cd portfolio-intelligence
./run.sh            # pip install -r requirements.txt && python app.py
```

Then open http://localhost:5000.

**Stack:** Python, Flask, pandas, NumPy, SciPy (SLSQP), yfinance, Chart.js
