# Portfolio Intelligence Platform

A full-stack portfolio analytics application. Upload your holdings, and it values
them against live market data, solves for a maximum-Sharpe allocation, and scores
the book's risk health across four dimensions.

Built with Flask, Chart.js, NumPy, pandas and SciPy. Prices come from Yahoo
Finance.

---

## What it does

**Ingest.** Holdings arrive three ways: a brokerage CSV export (column names are
normalised across Fidelity, Schwab, Robinhood and Vanguard formats), a screenshot
of a brokerage app parsed with Tesseract OCR, or manual entry.

**Value.** Live prices produce per-position market value, cost basis, unrealised
P&L and portfolio weight, aggregated into a sector breakdown. Performance is
tracked as actual dollars against a control: what the identical cost basis would
be worth had it gone into SPY on day one. Not a normalised backtest — real money
against a real alternative.

**Optimise.** Markowitz mean-variance optimisation over one year of daily returns,
solved with SLSQP under long-only, fully-invested constraints and a 25% cap on
any single name. The result is compared against the current allocation and an
equal-weight control, with expected return, volatility and Sharpe for each.

**Score.** PRISM grades the portfolio 0–100 on four risk dimensions, measured over
five years:

| | Dimension | Measure |
|---|---|---|
| **F** | Diversification | Inverted Herfindahl-Hirschman index across GICS sectors |
| **I** | Correlation | Average pairwise correlation of daily returns |
| **N** | Volatility | Annualised volatility, mapped across a 10%–40% band |
| **E** | Concentration | Largest single-position weight |

The composite is their unweighted mean. The dashboard also renders the full
correlation matrix as a heatmap, benchmarks the score against SPY and a 60/20/20
three-fund portfolio, and surfaces a plain-language callout naming the weakest
dimension — "NVDA makes up 38% of your portfolio. A bad quarter for this stock
hits you hard."

---

## Architecture

```
app.py                  Flask routes — thin, no business logic
core/
  market_data.py        one download per request; every consumer reads a slice
  ingest.py             CSV + screenshot OCR -> holdings
  portfolio.py          values, cost basis, P&L, weights, SPY comparison
  optimizer.py          max-Sharpe allocation, sensitivity, risk-return scatter
  prism.py              four risk sub-scores, benchmarks, callout
templates/ static/      dashboard UI
```

### The market-data layer

`MarketData` issues a single five-year download covering the user's tickers plus
SPY. Every downstream consumer reads a slice of that one frame:

| Consumer | Window |
|---|---|
| Latest prices | Last row |
| P&L vs SPY | Trailing 1 year |
| Optimiser | Trailing 1 year of closes → 251 daily returns |
| PRISM | Full 5 years of daily returns |

This matters for more than speed. Because valuation, optimisation and scoring all
read the same frame and the same weights dictionary, the three panels of the
dashboard cannot disagree about what you own — they are three views of one
computation, not three independent ones.

Sector lookups are cached process-wide. Benchmark PRISM scores don't depend on
user holdings, so they're computed once and cached for 24 hours rather than
recomputed per request.

---

## Provenance

This project merges two earlier repositories:

| Was | Stack | Became |
|---|---|---|
| `portfolio-optimizer` | Flask + Chart.js | `core/portfolio.py`, `core/optimizer.py`, `core/ingest.py` |
| `fine-score` (PRISM) | FastAPI + React/Vite | `core/prism.py` |

They overlapped heavily — both ingested a holdings list, both downloaded prices,
both derived market-value weights, both computed a correlation structure, both
benchmarked against SPY. Running them separately produced three problems:

1. **Redundant network calls.** Six downloads and sixteen sector lookups per
   analysis, most of them fetching data the other service already had. The merged
   version costs three downloads cold and one warm.

2. **Two sources of truth for weights.** The dashboard derived weights from a
   five-day price pull; PRISM derived them independently from the last row of a
   five-year pull. On a day when one feed lagged, the risk score described a
   subtly different portfolio than the table above it. Weights are now computed
   once, in `core/portfolio.py`.

3. **An optimiser the web app never called.** `optimize_portfolio()` existed but
   ran only in a command-line path that wrote a static HTML file; the Flask route
   returned P&L and sector splits with no optimal allocation. It now runs on every
   request.

The analytical windows are deliberately unchanged by the merge — the optimiser
still sees one year, PRISM still sees five. Only the transport is shared. The
merged modules were run head-to-head against both original codebases on identical
inputs: all four PRISM sub-scores, the composite, the callout and the correlation
matrix reproduce exactly, and optimal weights match to within 2e-15.

---

## API

**`POST /api/analyze`**

```json
{ "holdings": [ { "ticker": "AAPL", "shares": 40, "avg_cost": 150.00 } ] }
```

Returns `summary`, `holdings`, `sector_allocation`, `performance`,
`optimization`, `prism` and `meta`.

`optimization` and `prism` each carry an `available` flag. Both need at least two
holdings with usable price history, and degrade with a `reason` string rather
than failing the request. Tickers with no price history are listed in
`meta.dropped_tickers`, shown at cost basis in the holdings table, and excluded
from the risk analytics — the dashboard says so explicitly rather than letting
the numbers quietly disagree. `meta` also reports elapsed time and the number of
network fetches the request actually cost.

**`POST /api/parse/csv`** — multipart upload, returns parsed holdings.

**`POST /api/parse/screenshot`** — multipart image upload, OCR, returns parsed
holdings with a review warning.

**`GET /api/health`** — liveness probe.

---

## Running

```bash
pip install -r requirements.txt
python app.py
```

Then open `http://localhost:5000`.

Screenshot ingest additionally needs `pytesseract`, `pillow`, and a system
Tesseract install (`brew install tesseract` on macOS). Without them, CSV and
manual entry work normally and the screenshot route returns an explanatory error
rather than crashing.

---

## Limitations

Worth stating plainly, since every one of these is a real constraint on how the
output should be read.

- **Single price source.** Yahoo Finance with no fallback feed, so an outage takes
  down analysis entirely.
- **Expected returns are historical means.** One year of trailing daily returns is
  a weak forecast of the next year. The optimal weights describe what would have
  been efficient in hindsight, not a recommendation.
- **PRISM's thresholds are judgment calls.** The 10–40% volatility band and the
  30%/50% concentration breakpoints were chosen for interpretability, not
  calibrated against outcome data.
- **The four dimensions are not independent.** Correlation and diversification
  overlap substantially, so an unweighted mean double-counts that overlap.
- **No transaction costs, taxes, or rebalancing drag** are modelled anywhere in
  the optimisation.
