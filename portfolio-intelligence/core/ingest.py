#!/usr/bin/env python3
"""
Holdings ingest: brokerage CSV and brokerage screenshot (OCR).

Lifted from portfolio-optimizer/app.py with the parsing logic unchanged. It
moves out of the route handlers so both the CSV and screenshot paths return the
same holdings shape, and so the parsers can be tested without a Flask request.

Holdings shape: [{'ticker': str, 'shares': float, 'avg_cost': float | None}]
"""

import io
import re

import pandas as pd

# Column aliases seen across Fidelity / Schwab / Robinhood / Vanguard exports.
_TICKER_COLUMNS = {'ticker', 'symbol', 'stock', 'security', 'name'}
_SHARES_COLUMNS = {'shares', 'quantity', 'qty', 'units', 'amount', 'position'}
_COST_COLUMNS = {
    'avg_cost', 'avg_price', 'purchase_price', 'cost_basis',
    'price', 'cost', 'average_cost', 'average_price',
}

# Words an OCR pass will surface that look like tickers but are not.
_EXCLUDE_WORDS = {
    'A', 'I', 'AM', 'PM', 'USD', 'CAD', 'ETF', 'INC', 'LLC', 'LTD', 'PLC',
    'ADR', 'CORP', 'CO', 'NA', 'NV', 'SE', 'AG', 'SA', 'THE', 'AND', 'FOR',
    'NEW', 'NET', 'EST', 'AVG', 'TOTAL', 'GAIN', 'LOSS', 'PRICE', 'VALUE',
    'RETURN', 'COST', 'BASIS', 'MARKET', 'ACCOUNT', 'BALANCE', 'SHARES',
    'STOCK', 'PORTFOLIO', 'TODAY', 'OPEN', 'CLOSE', 'HIGH', 'LOW', 'BUY',
    'SELL', 'TRADE', 'ORDER', 'TYPE', 'QTY', 'SYMBOL', 'NAME', 'MY', 'OF',
    'IN', 'AT', 'BY', 'NO', 'ON', 'UP', 'OR', 'TO', 'IT',
}


class IngestError(ValueError):
    """Raised when a file cannot be turned into holdings."""


def parse_csv(content: str) -> list:
    """Parse a brokerage CSV export into holdings."""
    df = pd.read_csv(io.StringIO(content))
    df.columns = [str(c).strip().lower().replace(' ', '_') for c in df.columns]

    rename = {}
    for col in df.columns:
        if col in _TICKER_COLUMNS:
            rename[col] = 'ticker'
        elif col in _SHARES_COLUMNS:
            rename[col] = 'shares'
        elif col in _COST_COLUMNS:
            rename[col] = 'avg_cost'
    df = df.rename(columns=rename)

    if 'ticker' not in df.columns:
        raise IngestError('CSV must contain a ticker or symbol column')

    holdings = []
    for _, row in df.iterrows():
        ticker = str(row['ticker']).upper().strip()
        if not ticker or ticker in ('NAN', 'TICKER', 'SYMBOL'):
            continue

        shares = (
            float(row['shares'])
            if 'shares' in df.columns and pd.notna(row.get('shares'))
            else 0.0
        )
        avg_cost = (
            float(row['avg_cost'])
            if 'avg_cost' in df.columns and pd.notna(row.get('avg_cost'))
            else None
        )

        if shares > 0:
            holdings.append({'ticker': ticker, 'shares': shares, 'avg_cost': avg_cost})

    if not holdings:
        raise IngestError('No valid holdings found in CSV')

    return holdings


def parse_screenshot(image_bytes: bytes) -> list:
    """OCR a brokerage screenshot into holdings. Requires pytesseract + pillow."""
    try:
        import pytesseract
        from PIL import Image, ImageEnhance, ImageFilter
    except ImportError as exc:
        raise IngestError(
            'Tesseract is not installed. Run: pip install pytesseract pillow '
            'and install Tesseract OCR (brew install tesseract on Mac). '
            'Or use CSV upload instead.'
        ) from exc

    img = Image.open(io.BytesIO(image_bytes)).convert('RGB')
    # Brokerage UIs are usually dark; contrast + sharpen lifts OCR accuracy.
    img = ImageEnhance.Contrast(img).enhance(1.8)
    img = img.filter(ImageFilter.SHARPEN)

    text = pytesseract.image_to_string(img, config='--psm 6')
    return parse_brokerage_text(text)


def parse_brokerage_text(text: str) -> list:
    """Heuristic extraction of ticker / shares / avg_cost from OCR output."""
    holdings, seen = [], set()

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        tickers = re.findall(r'\b([A-Z]{1,5})\b', line)
        raw_nums = re.findall(r'[\d,]+\.?\d*', line)

        valid = [t for t in tickers if t not in _EXCLUDE_WORDS and 1 < len(t) <= 5]
        if not valid or not raw_nums:
            continue

        ticker = valid[0]
        if ticker in seen:
            continue

        nums = []
        for n in raw_nums:
            try:
                nums.append(float(n.replace(',', '')))
            except ValueError:
                pass

        if not nums:
            continue

        seen.add(ticker)
        shares = nums[0]
        avg_cost = nums[1] if len(nums) >= 2 else None

        if shares > 0:
            holdings.append({'ticker': ticker, 'shares': shares, 'avg_cost': avg_cost})

    return holdings


def normalise(holdings_list: list) -> tuple:
    """Turn a raw holdings payload into (shares, purchase_prices) keyed by ticker."""
    shares, purchase_prices = {}, {}

    for h in holdings_list:
        ticker = str(h.get('ticker', '')).upper().strip()
        if not ticker:
            continue
        try:
            qty = float(h.get('shares', 0))
        except (TypeError, ValueError):
            continue
        if qty <= 0:
            continue

        shares[ticker] = qty
        if h.get('avg_cost') is not None:
            try:
                purchase_prices[ticker] = float(h['avg_cost'])
            except (TypeError, ValueError):
                pass

    return shares, purchase_prices
