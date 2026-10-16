#!/usr/bin/env python3
"""
Portfolio Tracker — Flask web server.
Routes: / (UI)  |  /api/parse/csv  |  /api/parse/screenshot  |  /api/analyze
"""

import io
import re

import pandas as pd
from flask import Flask, jsonify, render_template, request

try:
    import pdfplumber
except ImportError:
    pdfplumber = None

from portfolio_optimizer import (
    calculate_portfolio,
    fetch_historical_performance,
    fetch_prices,
    get_sectors,
)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32 MB


# ─── UI ───────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


# ─── CSV PARSE ────────────────────────────────────────────────────────────────

@app.route('/api/parse/csv', methods=['POST'])
def parse_csv():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    f = request.files['file']
    try:
        content = f.read().decode('utf-8', errors='replace')
        df = pd.read_csv(io.StringIO(content))
        df.columns = [c.strip().lower().replace(' ', '_') for c in df.columns]

        # Normalise column names to ticker / shares / avg_cost / date
        rename = {}
        for col in df.columns:
            if col in ('ticker', 'symbol', 'stock', 'security', 'name'):
                rename[col] = 'ticker'
            elif col in ('shares', 'quantity', 'qty', 'units', 'amount', 'position',
                         '#_shares'):
                rename[col] = 'shares'
            elif col in ('avg_cost', 'avg_price', 'purchase_price', 'cost_basis',
                         'price', 'cost', 'average_cost', 'average_price',
                         'average_cost/share_($)', 'avg_cost/share',
                         'average_cost/share'):
                rename[col] = 'avg_cost'
            elif col in ('date', 'date_acquired', 'date_of_acquisition',
                         'purchase_date', 'acquisition_date', 'bought',
                         'trade_date', 'buy_date'):
                rename[col] = 'date'
        df = df.rename(columns=rename)

        if 'ticker' not in df.columns:
            return jsonify({'error': 'CSV must contain a ticker or symbol column'}), 400

        holdings = []
        for _, row in df.iterrows():
            ticker = str(row['ticker']).upper().strip()
            if not ticker or ticker in ('NAN', 'TICKER', 'SYMBOL', '-', ''):
                continue
            shares = float(row['shares']) if 'shares' in df.columns and pd.notna(row.get('shares')) else 0
            avg_cost = (float(row['avg_cost'])
                        if 'avg_cost' in df.columns and pd.notna(row.get('avg_cost'))
                        else None)
            date = _parse_date(row.get('date')) if 'date' in df.columns else None
            if shares > 0:
                h = {'ticker': ticker, 'shares': shares, 'avg_cost': avg_cost}
                if date:
                    h['date'] = date
                holdings.append(h)

        if not holdings:
            return jsonify({'error': 'No valid holdings found in CSV'}), 400

        return jsonify({'holdings': holdings})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


def _parse_date(val):
    """Try to convert a value to YYYY-MM-DD string."""
    if pd.isna(val) or val is None:
        return None
    s = str(val).strip()
    if not s or s == '-':
        return None
    for fmt in ('%m/%d/%Y', '%Y-%m-%d', '%m-%d-%Y', '%d/%m/%Y',
                '%m/%d/%y', '%Y/%m/%d', '%d-%m-%Y', '%b %d, %Y',
                '%B %d, %Y', '%d %b %Y', '%d %B %Y'):
        try:
            return pd.Timestamp(s).strftime('%Y-%m-%d')
        except Exception:
            pass
        try:
            from datetime import datetime
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    try:
        return pd.to_datetime(s, dayfirst=False).strftime('%Y-%m-%d')
    except Exception:
        return None


# ─── PDF PARSE ───────────────────────────────────────────────────

_TICKER_KEYS = {'symbol', 'ticker', 'stock', 'security'}
_SHARES_KEYS = {'shares', 'quantity', 'qty', '#_shares', '#shares',
                'units', 'amount', 'position'}
_COST_KEYS = {'avg_cost', 'avg_price', 'purchase_price', 'cost_basis',
              'average_cost/share_($)', 'average_cost/share',
              'average_cost', 'average_price', 'cost', 'price',
              'cost_basis_($)'}
_DATE_KEYS = {'date', 'date_acquired', 'date_of_acquisition',
              'purchase_date', 'acquisition_date', 'bought',
              'trade_date', 'buy_date'}


def _classify_header(text):
    """Return field name if text looks like a known column header."""
    t = text.lower().strip().replace(' ', '_')
    if t in _TICKER_KEYS:
        return 'ticker'
    if t in _SHARES_KEYS:
        return 'shares'
    if t in _COST_KEYS:
        return 'avg_cost'
    if t in _DATE_KEYS:
        return 'date'
    return None


def _build_col_map(table):
    """Scan the first few rows to find column indices for known fields.

    Handles PDFs where headers span multiple rows or are merged with
    the first data value via newlines (e.g. "Symbol\\nAAPL").
    """
    col_map = {}
    for row_idx in range(min(4, len(table))):
        row = table[row_idx]
        for col_idx, cell in enumerate(row):
            if col_idx in col_map.values():
                continue
            if cell is None:
                continue
            parts = str(cell).split('\n')
            for part in parts:
                field = _classify_header(part)
                if field and field not in col_map:
                    col_map[field] = col_idx
    return col_map


def _extract_cell(row, col_map, field):
    """Get the data value from a cell, stripping any header line."""
    idx = col_map.get(field)
    if idx is None or idx >= len(row):
        return None
    val = row[idx]
    if val is None:
        return None
    parts = str(val).split('\n')
    # If multi-line, the header is the first line; data is the last.
    return parts[-1].strip() if parts else None


@app.route('/api/parse/pdf', methods=['POST'])
def parse_pdf():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    if pdfplumber is None:
        return jsonify({'error': 'PDF parsing not available — install pdfplumber'}), 400

    f = request.files['file']
    try:
        pdf = pdfplumber.open(io.BytesIO(f.read()))
        holdings = []
        seen = set()

        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue

                col_map = _build_col_map(table)
                if 'ticker' not in col_map:
                    continue

                for row in table:
                    ticker_raw = _extract_cell(row, col_map, 'ticker')
                    if not ticker_raw:
                        continue
                    ticker = ticker_raw.upper().strip()
                    if not ticker or ticker in ('-', 'NAN', 'TICKER', 'SYMBOL',
                                                '(OPTIONAL)', ''):
                        continue
                    if not re.match(r'^[A-Z]{1,5}$', ticker):
                        continue
                    if ticker in seen:
                        continue

                    shares_raw = _extract_cell(row, col_map, 'shares')
                    shares = 0
                    if shares_raw:
                        try:
                            shares = float(shares_raw.replace(',', ''))
                        except ValueError:
                            pass

                    cost_raw = _extract_cell(row, col_map, 'avg_cost')
                    avg_cost = None
                    if cost_raw:
                        try:
                            avg_cost = float(cost_raw.replace(',', '')
                                             .replace('$', ''))
                        except ValueError:
                            pass

                    date_raw = _extract_cell(row, col_map, 'date')
                    date = _parse_date(date_raw) if date_raw else None

                    if shares > 0:
                        seen.add(ticker)
                        h = {'ticker': ticker, 'shares': shares,
                             'avg_cost': avg_cost}
                        if date:
                            h['date'] = date
                        holdings.append(h)

        pdf.close()

        if not holdings:
            return jsonify({'error': 'No holdings found in PDF. '
                            'Make sure it contains a table with ticker/symbol '
                            'and shares columns.'}), 400

        return jsonify({'holdings': holdings})
    except Exception as e:
        return jsonify({'error': f'Error parsing PDF: {e}'}), 400


# ─── SCREENSHOT PARSE ─────────────────────────────────────────────────────────

@app.route('/api/parse/screenshot', methods=['POST'])
def parse_screenshot():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    f = request.files['file']
    try:
        import pytesseract
        from PIL import Image, ImageEnhance, ImageFilter

        img = Image.open(io.BytesIO(f.read())).convert('RGB')
        # Boost contrast for cleaner OCR on dark brokerage UIs
        img = ImageEnhance.Contrast(img).enhance(1.8)
        img = img.filter(ImageFilter.SHARPEN)

        text = pytesseract.image_to_string(img, config='--psm 6')
        holdings = _parse_brokerage_text(text)

        if not holdings:
            return jsonify({
                'holdings': [],
                'note': 'Could not extract holdings automatically. Please add them manually.'
            })

        return jsonify({
            'holdings': holdings,
            'note': 'Review and correct the parsed data — OCR may have errors.'
        })

    except ImportError:
        return jsonify({
            'error': (
                'Tesseract is not installed. '
                'Run: pip install pytesseract pillow  and install Tesseract OCR '
                '(brew install tesseract on Mac). '
                'Or use CSV upload instead.'
            )
        }), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 400


_EXCLUDE_WORDS = {
    'A', 'I', 'AM', 'PM', 'USD', 'CAD', 'ETF', 'INC', 'LLC', 'LTD', 'PLC',
    'ADR', 'CORP', 'CO', 'NA', 'NV', 'SE', 'AG', 'SA', 'THE', 'AND', 'FOR',
    'NEW', 'NET', 'EST', 'AVG', 'TOTAL', 'GAIN', 'LOSS', 'PRICE', 'VALUE',
    'RETURN', 'COST', 'BASIS', 'MARKET', 'ACCOUNT', 'BALANCE', 'SHARES',
    'STOCK', 'PORTFOLIO', 'TODAY', 'OPEN', 'CLOSE', 'HIGH', 'LOW', 'BUY',
    'SELL', 'TRADE', 'ORDER', 'TYPE', 'QTY', 'SYMBOL', 'NAME', 'MY', 'OF',
    'IN', 'AT', 'BY', 'NO', 'ON', 'UP', 'OR', 'TO', 'IT',
}


def _parse_brokerage_text(text: str) -> list:
    """Heuristic extraction of ticker / shares / avg_cost from OCR output."""
    holdings, seen = [], set()

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        tickers = re.findall(r'\b([A-Z]{1,5})\b', line)
        raw_nums = re.findall(r'[\d,]+\.?\d*', line)

        valid_tickers = [t for t in tickers if t not in _EXCLUDE_WORDS and 1 < len(t) <= 5]
        if not valid_tickers or not raw_nums:
            continue

        ticker = valid_tickers[0]
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


# ─── ANALYZE ──────────────────────────────────────────────────────────────────

@app.route('/api/analyze', methods=['POST'])
def analyze():
    body = request.get_json(force=True)
    holdings_list = body.get('holdings', [])

    if not holdings_list:
        return jsonify({'error': 'No holdings provided'}), 400

    holdings = {h['ticker']: float(h['shares']) for h in holdings_list}
    purchase_prices = {
        h['ticker']: float(h['avg_cost'])
        for h in holdings_list if h.get('avg_cost') is not None
    }
    tickers = list(holdings.keys())

    # Live prices
    prices = fetch_prices(tickers)

    # Fall back to purchase price if live price unavailable
    for ticker in tickers:
        if ticker not in prices:
            prices[ticker] = purchase_prices.get(ticker, 0)
    # Fill missing purchase prices with current price (0 % gain shown)
    for ticker in tickers:
        if ticker not in purchase_prices:
            purchase_prices[ticker] = prices[ticker]

    portfolio = calculate_portfolio(holdings, prices, purchase_prices)
    sectors = get_sectors(tickers)
    performance = fetch_historical_performance(holdings)

    total_value = portfolio['total_value']
    total_cost = portfolio['total_cost']
    total_gain = portfolio['total_gain']

    # Sector allocation by dollar value
    sector_alloc = {}
    for ticker, value in portfolio['values'].items():
        s = sectors.get(ticker, 'Other')
        sector_alloc[s] = sector_alloc.get(s, 0) + value

    # Per-position detail
    holdings_detail = []
    for ticker in tickers:
        price = prices.get(ticker, 0)
        value = portfolio['values'][ticker]
        cost = portfolio['costs'][ticker]
        gain = portfolio['gains'][ticker]
        gain_pct = (gain / cost * 100) if cost else 0
        weight = (value / total_value * 100) if total_value else 0

        holdings_detail.append({
            'ticker': ticker,
            'shares': holdings[ticker],
            'avg_cost': round(purchase_prices[ticker], 2),
            'current_price': round(price, 2),
            'value': round(value, 2),
            'gain': round(gain, 2),
            'gain_pct': round(gain_pct, 2),
            'weight': round(weight, 2),
            'sector': sectors.get(ticker, 'Other'),
        })

    holdings_detail.sort(key=lambda x: x['value'], reverse=True)

    return jsonify({
        'summary': {
            'total_value': round(total_value, 2),
            'total_cost': round(total_cost, 2),
            'total_gain': round(total_gain, 2),
            'total_gain_pct': round((total_gain / total_cost * 100) if total_cost else 0, 2),
        },
        'holdings': holdings_detail,
        'sector_allocation': {k: round(v, 2) for k, v in sector_alloc.items()},
        'performance': performance,
    })


# ─── ENTRY ────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5050))
    app.run(debug=True, port=port)
