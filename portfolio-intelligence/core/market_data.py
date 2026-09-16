#!/usr/bin/env python3
"""
Shared market-data layer.

Before the merge, a single dashboard request hit Yahoo Finance five times:

    portfolio-optimizer  fetch_prices()                 5d  tickers
                         fetch_historical_performance() 1y  tickers + SPY
                         get_sectors()                      one .info per ticker
    fine-score (PRISM)   fetch_prices()                 5y  tickers
                         fetch_prices(["SPY"])          5y  SPY
                         get_sector()                       one .info per ticker (again)
                         score_benchmark() x2           5y  SPY, then VTI/VXUS/BND

MarketData replaces all of that with one 5y download covering the user's tickers
plus SPY. Everything downstream is a slice of that frame:

    latest prices   -> last row                (was: separate 5d download)
    P&L vs SPY      -> trailing 1y slice       (was: separate 1y download)
    optimizer       -> trailing 1y of returns  (matches the original 1y window)
    PRISM           -> full 5y of returns      (matches the original 5y window)

The windows are deliberately unchanged from the originals: the optimizer still
sees one year, PRISM still sees five. Only the transport is shared, so neither
project's numbers move.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Lock

import numpy as np
import pandas as pd
import yfinance as yf

TRADING_DAYS = 252

# Sector lookups are stable and expensive (one HTTP call each), so they are
# cached process-wide rather than per request. Both source projects looked these
# up independently, which meant every ticker was fetched twice per analysis.
_SECTOR_CACHE: dict = {}
_SECTOR_LOCK = Lock()

# Incremented on every network round trip so tests and /api/analyze can report
# how many downloads a request actually cost.
_COUNTERS = {'downloads': 0, 'sector_lookups': 0}
_COUNTER_LOCK = Lock()


def counters() -> dict:
    with _COUNTER_LOCK:
        return dict(_COUNTERS)


def reset_counters() -> None:
    with _COUNTER_LOCK:
        _COUNTERS['downloads'] = 0
        _COUNTERS['sector_lookups'] = 0


def _bump(key: str, n: int = 1) -> None:
    with _COUNTER_LOCK:
        _COUNTERS[key] += n


def download_closes(symbols, period: str = '5y') -> pd.DataFrame:
    """Download adjusted closes for `symbols`, always returning a ticker-keyed frame."""
    symbols = list(dict.fromkeys(symbols))
    if not symbols:
        return pd.DataFrame()

    _bump('downloads')
    raw = yf.download(symbols, period=period, auto_adjust=True, progress=False)

    if raw is None or len(raw) == 0:
        return pd.DataFrame()

    if isinstance(raw.columns, pd.MultiIndex):
        closes = raw['Close'].copy()
    else:
        # Single-ticker downloads come back with plain OHLCV columns.
        if 'Close' not in raw.columns:
            return pd.DataFrame()
        closes = raw[['Close']].copy()
        closes.columns = [symbols[0]]

    closes = closes.ffill().dropna(how='all')
    return closes


def lookup_sectors(tickers) -> dict:
    """GICS sector per ticker, cached across requests, fetched in parallel on a miss."""
    tickers = list(dict.fromkeys(tickers))

    with _SECTOR_LOCK:
        known = {t: _SECTOR_CACHE[t] for t in tickers if t in _SECTOR_CACHE}
    missing = [t for t in tickers if t not in known]

    if missing:
        def _one(ticker):
            try:
                info = yf.Ticker(ticker).info
                return ticker, info.get('sector') or 'Other'
            except Exception:
                return ticker, 'Other'

        _bump('sector_lookups', len(missing))
        with ThreadPoolExecutor(max_workers=8) as ex:
            fetched = dict(ex.map(_one, missing))

        with _SECTOR_LOCK:
            _SECTOR_CACHE.update(fetched)
        known.update(fetched)

    return known


class MarketData:
    """One download; every downstream consumer reads a slice of it.

    Attributes
      valid       tickers that came back with usable history
      dropped     tickers that did not
      closes      adjusted close frame, `period` long, valid tickers + SPY
      latest      {ticker: last close}
      returns     daily returns over the full window (PRISM's 5y view)
      sectors     {ticker: GICS sector}
    """

    BENCHMARK = 'SPY'
    MIN_OBSERVATIONS = 10

    def __init__(self, tickers, period: str = '5y'):
        self.requested = [str(t).upper().strip() for t in tickers]
        self.period = period

        frame = download_closes(self.requested + [self.BENCHMARK], period=period)

        if frame.empty:
            self.closes = pd.DataFrame()
            self.valid, self.dropped = [], list(self.requested)
            self.latest, self.sectors = {}, {}
            self.returns = pd.DataFrame()
            self.benchmark_closes = pd.Series(dtype=float)
            return

        self.valid = [
            t for t in self.requested
            if t in frame.columns and frame[t].notna().sum() > self.MIN_OBSERVATIONS
        ]
        self.dropped = [t for t in self.requested if t not in self.valid]

        keep = self.valid + ([self.BENCHMARK] if self.BENCHMARK in frame.columns else [])
        self.closes = frame[keep].dropna(how='all')

        self.benchmark_closes = (
            self.closes[self.BENCHMARK] if self.BENCHMARK in self.closes.columns
            else pd.Series(dtype=float)
        )

        self.latest = {t: float(self.closes[t].ffill().iloc[-1]) for t in self.valid}
        self.returns = self.closes[self.valid].pct_change().dropna() if self.valid else pd.DataFrame()
        self.sectors = lookup_sectors(self.valid) if self.valid else {}

    # ── windows ──────────────────────────────────────────────────────────────

    def returns_window(self, days: int = TRADING_DAYS) -> pd.DataFrame:
        """The optimizer's 1y view.

        Derived from the trailing `days` of *closes*, not the trailing `days` of
        returns. yf.download(period='1y') returns 252 closes, which pct_change()
        turns into 251 returns; slicing 252 returns instead would quietly shift
        the mean and covariance off the original repo's values.
        """
        if self.closes.empty or not self.valid:
            return pd.DataFrame()
        return self.closes[self.valid].tail(days).pct_change().dropna()

    def closes_window(self, days: int = TRADING_DAYS) -> pd.DataFrame:
        if self.closes.empty:
            return self.closes
        return self.closes.tail(days)

    # ── derived statistics ───────────────────────────────────────────────────

    def mean_returns(self, days: int = TRADING_DAYS) -> pd.Series:
        window = self.returns_window(days)
        return window.mean() if not window.empty else pd.Series(dtype=float)

    def covariance(self, days: int = TRADING_DAYS) -> pd.DataFrame:
        window = self.returns_window(days)
        return window.cov() if not window.empty else pd.DataFrame()

    def correlation(self) -> pd.DataFrame:
        """Full-window correlation — PRISM scores on 5y, as the original did."""
        if self.returns.empty:
            return pd.DataFrame()
        if len(self.valid) == 1:
            t = self.valid[0]
            return pd.DataFrame([[1.0]], index=[t], columns=[t])
        return self.returns.corr()

    def sector_weights(self, weights: dict) -> dict:
        out: dict = {}
        for ticker, w in weights.items():
            sector = self.sectors.get(ticker, 'Other')
            out[sector] = out.get(sector, 0.0) + w
        return out

    def portfolio_returns(self, weights: dict) -> pd.Series:
        """Weighted daily return series over the full window."""
        if self.returns.empty:
            return pd.Series(dtype=float)
        cols = [t for t in self.valid if t in weights]
        if not cols:
            return pd.Series(dtype=float)
        w = np.array([weights[t] for t in cols], dtype=float)
        total = w.sum()
        if total > 0:
            w = w / total
        return pd.Series(self.returns[cols].values @ w, index=self.returns.index)
