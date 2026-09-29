#!/usr/bin/env python3
"""
"Since you bought": every lot measured from its own acquisition date.

For each lot
    cost          shares × average cost (or the close on the day, if no cost given)
    today         shares × latest close
    peak          the highest intraday price reached on or after the acquisition
                  day, i.e. the best exit that was actually available
    missed        peak value − today's value: what selling at that high would have added
    SPY twin      the same money put into SPY on the same day

For the whole portfolio, a daily timeline from the first acquisition date:
    value         what you held each day (a lot joins on its acquisition day)
    invested      cumulative cost of the lots bought so far
    spy           the SPY twin of every lot, summed
    best_exit     each lot's best price so far, summed: the ceiling hindsight allows

Hindsight is not a strategy. Nobody can pick every top; this measures how much the
path offered compared with what you kept.
"""

import numpy as np
import pandas as pd
import yfinance as yf

from .market_data import _bump

BENCHMARK = 'SPY'
MAX_POINTS = 260


def download_ohlc(symbols, start: str) -> tuple:
    """(closes, highs) from `start` to today, ticker-keyed."""
    symbols = list(dict.fromkeys(symbols))
    _bump('downloads')
    raw = yf.download(symbols, start=start, auto_adjust=True, progress=False)
    if raw is None or len(raw) == 0:
        return pd.DataFrame(), pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        closes, highs = raw['Close'].copy(), raw['High'].copy()
    else:
        closes, highs = raw[['Close']].copy(), raw[['High']].copy()
        closes.columns = highs.columns = [symbols[0]]
    return closes.ffill().dropna(how='all'), highs


def analyse(lots: list, sectors=None) -> dict:
    dated = [l for l in lots if l.get('acquired')]
    undated = [l['ticker'] for l in lots if not l.get('acquired')]
    if not dated:
        return {'available': False, 'reason': 'Add acquisition dates to your holdings to see how each position did since you bought it.', 'undated': undated}

    first = min(l['acquired'] for l in dated)
    start = (pd.Timestamp(first) - pd.Timedelta(days=7)).strftime('%Y-%m-%d')
    tickers = sorted({l['ticker'] for l in dated})
    closes, highs = download_ohlc(tickers + [BENCHMARK], start)
    if closes.empty:
        return {'available': False, 'reason': 'Could not download price history for these dates.', 'undated': undated}

    idx = closes.index
    spy = closes[BENCHMARK].ffill() if BENCHMARK in closes else None
    last_day = idx[-1]

    rows, missing = [], []
    value_t = pd.Series(0.0, index=idx)
    invested_t = pd.Series(0.0, index=idx)
    spy_t = pd.Series(0.0, index=idx)
    best_t = pd.Series(0.0, index=idx)

    for lot in dated:
        t = lot['ticker']
        if t not in closes or closes[t].notna().sum() < 2:
            missing.append(t)
            continue
        c = closes[t].ffill()
        h = highs[t].reindex(idx).fillna(c) if t in highs else c
        pos = idx.searchsorted(pd.Timestamp(lot['acquired']))
        if pos >= len(idx):
            pos = len(idx) - 1
        d0 = idx[pos]
        entry_close = float(c.iloc[pos])
        if np.isnan(entry_close):
            missing.append(t)
            continue
        sh = float(lot['shares'])
        unit_cost = float(lot['avg_cost']) if lot.get('avg_cost') else entry_close
        cost = sh * unit_cost
        now_px = float(c.iloc[-1])
        window_h = h.iloc[pos:]
        peak_px = float(window_h.max())
        peak_day = window_h.idxmax()
        low_px = float(c.iloc[pos:].min())

        today = sh * now_px
        peak_val = sh * peak_px
        days = max(1, (last_day - d0).days)
        ret = today / cost - 1 if cost else None
        ann = ((today / cost) ** (365 / days) - 1) if cost and days >= 60 else None
        spy_val = cost / float(spy.iloc[pos]) * float(spy.iloc[-1]) if spy is not None else None
        capture = (today - cost) / (peak_val - cost) if peak_val > cost else None

        rows.append({
            'ticker': t, 'sector': (sectors or {}).get(t, 'Other'),
            'acquired': lot['acquired'], 'entry_day': d0.strftime('%Y-%m-%d'), 'days_held': days,
            'shares': sh, 'unit_cost': round(unit_cost, 4), 'cost': round(cost, 2),
            'price_now': round(now_px, 2), 'value_now': round(today, 2),
            'return_pct': round(ret * 100, 2) if ret is not None else None,
            'annualised_pct': round(ann * 100, 2) if ann is not None else None,
            'peak_price': round(peak_px, 2), 'peak_date': peak_day.strftime('%Y-%m-%d'),
            'peak_value': round(peak_val, 2), 'peak_return_pct': round((peak_val / cost - 1) * 100, 2) if cost else None,
            'missed': round(max(0.0, peak_val - today), 2),
            'off_peak_pct': round((now_px / peak_px - 1) * 100, 2) if peak_px else None,
            'lowest_price': round(low_px, 2),
            'capture_pct': round(capture * 100, 1) if capture is not None else None,
            'spy_value': round(spy_val, 2) if spy_val is not None else None,
            'vs_spy': round(today - spy_val, 2) if spy_val is not None else None,
        })

        mask = idx >= d0
        value_t[mask] += (c[mask] * sh).values
        invested_t[mask] += cost
        if spy is not None:
            spy_t[mask] += (spy[mask] / float(spy.iloc[pos]) * cost).values
        best_t[mask] += (h[mask].cummax() * sh).values

    if not rows:
        return {'available': False, 'reason': 'None of the dated positions had price history.', 'undated': undated, 'missing': missing}

    start_mask = idx >= pd.Timestamp(min(r['entry_day'] for r in rows))
    value_t, invested_t, spy_t, best_t = value_t[start_mask], invested_t[start_mask], spy_t[start_mask], best_t[start_mask]
    step = max(1, len(value_t) // MAX_POINTS)
    take = lambda s: [round(float(v), 2) for v in s.iloc[::step]] + ([round(float(s.iloc[-1]), 2)] if (len(s) - 1) % step else [])
    dates = list(value_t.index[::step].strftime('%Y-%m-%d')) + ([value_t.index[-1].strftime('%Y-%m-%d')] if (len(value_t) - 1) % step else [])

    total_cost = sum(r['cost'] for r in rows)
    total_now = sum(r['value_now'] for r in rows)
    total_peak = sum(r['peak_value'] for r in rows)
    total_spy = sum(r['spy_value'] or 0 for r in rows)
    pf_peak_day = value_t.idxmax()
    rows.sort(key=lambda r: r['missed'], reverse=True)

    return {
        'available': True,
        'first_date': min(r['entry_day'] for r in rows),
        'as_of': last_day.strftime('%Y-%m-%d'),
        'lots': rows,
        'undated': undated,
        'missing': missing,
        'totals': {
            'cost': round(total_cost, 2),
            'value_now': round(total_now, 2),
            'gain_now': round(total_now - total_cost, 2),
            'return_pct': round((total_now / total_cost - 1) * 100, 2) if total_cost else None,
            'peak_exit_value': round(total_peak, 2),
            'peak_exit_gain': round(total_peak - total_cost, 2),
            'peak_exit_return_pct': round((total_peak / total_cost - 1) * 100, 2) if total_cost else None,
            'missed': round(sum(r['missed'] for r in rows), 2),
            'spy_value': round(total_spy, 2),
            'vs_spy': round(total_now - total_spy, 2),
            'portfolio_peak_value': round(float(value_t.max()), 2),
            'portfolio_peak_date': pf_peak_day.strftime('%Y-%m-%d'),
            'capture_pct': round((total_now - total_cost) / (total_peak - total_cost) * 100, 1) if total_peak > total_cost else None,
        },
        'timeline': {
            'dates': dates,
            'value': take(value_t),
            'invested': take(invested_t),
            'spy': take(spy_t),
            'best_exit': take(best_t),
        },
    }
