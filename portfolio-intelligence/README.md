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

## What it does now

**Bring holdings in any form.** Drop several files at once, or paste a Google Sheets link:
CSV/TSV, Excel (`.xlsx`, `.xls`), Numbers/LibreOffice (`.ods`), JSON, PDF statements, Word
(`.docx`) and screenshots. One table detector finds the header row even when a title block sits
above it (like the Google Finance tracker template) and maps columns such as *Symbol*, *# shares*,
*Avg cost / Total cost* and *Date of acquisition*. A “Total Cost” column that really holds a cost
per share is detected from the price and return columns and read correctly. Each row is kept as
its own purchase, so the same ticker bought on two dates stays two lots.

**Review, with dates.** Every purchase has an editable acquisition date; rows without one are
highlighted, because the date unlocks the “since you bought” views.

**One dashboard at a time.** Results are a scrolling story. Each chapter pairs one dashboard with
a plain-language panel: what it shows, how to read it, and what it means for you. Charts draw as
you arrive, the side rail tracks where you are, and the rest dims so there is one thing to read.

| Chapter | What it answers |
|---|---|
| Where you stand | Value, cost, gain and weight of each holding today |
| Your journey | Day by day from your first purchase: value vs money put in vs the same purchases in SPY |
| Each purchase | Return of every lot since its own acquisition date (and per year, for 60+ day holds) |
| Best possible exits | For every lot, the highest price reached after you bought it: what selling at each peak would have given, the gap to today, and how much of the best case you kept |
| Where it’s planted | Sector mix |
| The last 12 months | Current holdings vs SPY over a year |
| Risk health | PRISM score, its four parts, and the correlation grid |
| Range of outcomes | Monte Carlo replays of the next 12 months for your holdings: middle case, chance of a down year, 1-in-20 loss in dollars, fan chart, histogram, and your mix vs the suggested mix |
| Stress test | A link to the stress test page (`/stress`), which opens with your holdings carried over |
| Suggested changes | Its own dashboard: the trades (add / trim / exit, in % , $ and shares) that turn today’s mix into the max-Sharpe mix, expected return and $/year before and after, risk and Sharpe change, and a year replayed with both mixes |
| Every holding | The full table per purchase |

## Architecture

```
app.py                  Flask routes — thin, no business logic
core/
  hindsight.py          since-acquisition returns, peak (best-exit) values, daily timeline
  market_data.py        one download per request; every consumer reads a slice
  ingest.py             any file / Google Sheet -> purchases (ticker, shares, cost, date)
  portfolio.py          values, cost basis, P&L, weights, SPY comparison
  optimizer.py          max-Sharpe allocation, sensitivity, risk-return scatter
  montecarlo.py         simulated return distribution: percentiles, P(loss), VaR/CVaR, drawdowns
  prism.py              four risk sub-scores, benchmarks, callout
templates/ static/      dashboard UI: Overview · Performance · Risk Health · Efficiency · Holdings
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
| Monte Carlo | Full 5 years by default (`lookback_days` to change) |

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
{ "holdings": [ { "ticker": "AAPL", "shares": 40, "avg_cost": 150.00, "acquired": "2024-03-01" } ] }
```

Returns `summary`, `holdings`, `sector_allocation`, `performance`,
`optimization` (now with `trades`, `impact`, `growth`), `prism`, `hindsight`,
`monte_carlo` and `meta`. `monte_carlo` simulates 2,000 one-year paths for the
current mix and the optimizer's suggested mix with a fixed seed, so a refresh
shows the same numbers.

`optimization` and `prism` each carry an `available` flag. Both need at least two
holdings with usable price history, and degrade with a `reason` string rather
than failing the request. Tickers with no price history are listed in
`meta.dropped_tickers`, shown at cost basis in the holdings table, and excluded
from the risk analytics — the dashboard says so explicitly rather than letting
the numbers quietly disagree. `meta` also reports elapsed time and the number of
network fetches the request actually cost.

**`POST /api/simulate`** — the Monte Carlo engine on its own, with every
assumption exposed so a dashboard can turn the knobs:

```json
{ "holdings": [...], "horizon_days": 252, "paths": 5000,
  "method": "normal | student_t | bootstrap", "lookback_days": 1260,
  "block": 5, "df": 5, "seed": 7, "weights": { "AAPL": 60, "BND": 40 } }
```

All fields but `holdings` are optional (`weights` alone also works, to simulate a
hypothetical mix). Each allocation in `results` returns percentiles of total
return (`p1`…`p99`), expected and median return, probability of a loss and of
falling below −10% / −20% or beating +10% / +20%, 95% and 99% VaR and CVaR in
percent and dollars, the median and 1-in-20 worst max drawdown, a fan of
percentile paths for charting, and a histogram of outcomes.

The three methods differ in what they assume. `normal` draws from the historical
mean and covariance. `student_t` keeps that covariance but gives every day a
shared fat-tailed shock, so crashes hit all holdings at once. `bootstrap`
replays whole historical days (in blocks of `block` days if set), keeping the
real tails and correlations with no distributional assumption. Paths are
buy-and-hold, so winners drift to a larger share over the horizon.
**`GET /stress`** — the stress test page. Holdings arrive from the story page through `localStorage`
(or can be typed in). Step 1 checks the holdings, step 2 offers ready-made scenarios and sliders for the stock
market, the 10-year yield, the yield-curve gap, VIX, oil, the dollar and each sector you own, each with a
one-line explanation, and step 3 shows the instant hit per holding, what drives it, your biggest sensitivities,
a Monte Carlo fan chart and an outcome histogram, plus a plain-words summary and a glossary.

**`POST /api/sensitivity/model`** — `{"holdings": [{"ticker", "sector"?}]}`. One 5-year weekly download of
the holdings plus SPY, ^TNX, ^IRX, ^VIX, USO and UUP, then a ridge-stabilised regression of each holding on
those factors (market return, change in the 10-year yield in bp, change in the 10y − 3m slope in bp, change in
VIX, oil return, dollar return). Returns betas, residual volatility, R², the factor covariance and scenario
presets. A factor that fails to download is dropped rather than failing the request. Cached for 30 minutes.

**`POST /api/sensitivity/simulate`** — the model from above plus `values` ({ticker: $}), `shocks`,
`sector_shocks`, `horizon_months`, `market_return`, `vol_mult`, `target_return`, `linked`, `fat_tails`.
No downloads, so the dashboard calls it on every slider move (about 0.1 s for 40 holdings over a year).
It returns the instant scenario (per holding and per factor), each factor's one-year-move exposure, and a
Monte Carlo run on the shared engine (`core/montecarlo.py`, the same one behind `/api/simulate`) with the
factor model's means and covariance, in monthly steps (weekly under 4 months), up to 4,000 paths, with and
without the shock on the same random draws: percentiles,
chance of loss, chance of hitting the target, VaR/CVaR 95, drawdowns, a fan chart and a histogram. With
`linked` on, factors left at zero take their conditional expected move given the ones you set. Expected
returns are CAPM-style (cash rate + β × market premium); `fat_tails` switches the engine to `student_t` (df 4).

**`POST /api/parse`** — multipart `files` (any number, any supported format) and/or `sheet_url`; returns purchases with `ticker, shares, avg_cost, acquired, name, source`, plus notes.

**`POST /api/parse/csv`** — legacy single-CSV upload.

**`POST /api/parse/screenshot`** — multipart image upload, OCR, returns parsed
holdings with a review warning.

**`GET /api/health`** — liveness probe.

### News signals (watched portfolio)

Portfolio Intelligence can remember one portfolio and keep reading the news for
it. Only the tickers in that saved portfolio (plus its watchlist candidates) are
ever looked up. Nothing here places trades.

- **`POST /api/portfolio`** — `{"holdings": [...], "candidates": ["TICKER", ...]}`.
  Saves the portfolio the dashboard is showing ("Watch this portfolio").
  **`GET /api/portfolio`** returns it (404 if none is saved).
- **`POST /api/intel/run`** — one pass of the loop: fetch news and filings since
  the last run, have Claude score each new story (event type, direction,
  magnitude, a quote it must take from the story), decay scores over time
  (half-life 4 days for news, 7 for filings), check them against today's price
  move, and, if a stock's signal is strong enough, build a suggestion with the
  optimizer, capped at a 5-point move per stock, with PRISM and Monte Carlo
  before and after. Returns 409 if no portfolio is saved. If every news source fails, the run is
  recorded with its errors and no suggestion is made.
- **`GET /api/intel`** — the current signals, recent suggestions and runs, and
  which settings are missing (true/false only, never the values).

These three need the owner key: `Authorization: Bearer $INTEL_TOKEN`. The page
asks for it once and keeps it in the browser. Without `INTEL_TOKEN`, only
requests from the same machine are allowed, and on Vercel nobody is.

The schedule is `.github/workflows/intel.yml`: every 30 minutes while the US
market is open, plus one run before the open and one after the close. It calls
`/api/intel/run` and needs two repository secrets, `INTEL_URL` (for example
`https://portfolio-intelligence-chi.vercel.app`) and `INTEL_TOKEN`. It skips
quietly until both are set.

| Setting | What it does |
|---|---|
| `INTEL_TOKEN` | Owner key for the routes above. Generate a long random string. |
| `ANTHROPIC_API_KEY` | Claude scoring. Without it, stories are collected but not scored. |
| `INTEL_MODEL` | Optional; defaults to the current Claude Opus model. |
| `FINNHUB_API_KEY` | Primary news feed (free tier is enough). Google News is used without it. |
| `SEC_USER_AGENT` | `"portfolio-intelligence you@example.com"`; the SEC requires a contact. Filings are skipped without it. |
| `DATABASE_URL` / `POSTGRES_URL` | Where the saved portfolio and loop state live. Required on Vercel (Storage → Neon sets it). Locally, JSON files under `PI_DATA_DIR` (default `.data/`) are used. |
| `INTEL_MODE` | `shadow` (default): suggestions are recorded and shown, marked as not acted on. `live`: also sends a push. |
| `NTFY_TOPIC` | ntfy.sh topic for pushes in live mode. |

Guard rails: at most 3 suggestions a day, a 4-day cooldown per stock and
direction, no trade under 2% of the portfolio, and a suggestion is dropped if
it lowers the PRISM score by more than 5 points.

---

## Running

```bash
pip install -r requirements.txt
python app.py
```

Then open `http://localhost:5000`.

Tests (no network needed, prices are faked):

```bash
pip install pytest
python3 -m pytest
```
Tests (no network needed): `pip install pytest && python -m pytest tests`.

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
- **Monte Carlo inherits its window.** The simulation is only as good as the
  assumption that the next year looks like a random draw from the lookback
  window. A five-year window that ran mostly up will produce an optimistic
  distribution; use `bootstrap` or `student_t` to see heavier tails.
- **No transaction costs, taxes, or rebalancing drag** are modelled anywhere in
  the optimisation.
