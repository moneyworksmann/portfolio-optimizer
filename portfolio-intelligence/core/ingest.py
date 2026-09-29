#!/usr/bin/env python3
"""
Holdings ingest from almost any file a brokerage, spreadsheet or person produces.

    CSV / TSV / TXT        brokerage exports, Google Sheets "Download as CSV"
    XLSX / XLS / ODS       Excel, Numbers exports, Google Sheets "Download as xlsx"
    Google Sheets link     a shared sheet URL (read through its CSV export)
    JSON                   a list of {ticker, shares, ...} records
    PDF                    brokerage statements (tables first, then text)
    DOCX                   Word documents with a holdings table or lines of text
    PNG / JPG / …          brokerage screenshots (OCR)

Every source is reduced to rows of cells, and one table detector finds the header
row (spreadsheets often carry a title block above it, like the Google Finance
tracker template) and maps its columns by name.

Holdings shape (one entry per lot, so the same ticker bought on two dates stays
two rows):

    {'ticker': str, 'shares': float, 'avg_cost': float | None,
     'acquired': 'YYYY-MM-DD' | None, 'name': str | None}
"""

import io
import json
import math
import re
from datetime import date, datetime, timedelta

import pandas as pd


class IngestError(ValueError):
    """Raised when a file cannot be turned into holdings."""


# ── column vocabulary ────────────────────────────────────────────────────────
# Normalised header text -> role. Exact matches win; then "contains" matches for
# the longer phrases. Order inside each list does not matter.

ROLES = {
    'ticker': ['ticker', 'symbol', 'stock symbol', 'ticker symbol', 'security symbol', 'instrument', 'code', 'stock ticker'],
    'shares': ['shares', '# shares', 'shares owned', 'quantity', 'qty', 'units', 'number of shares', 'no of shares',
               'share count', 'position', 'holding', 'holdings', 'amount'],
    'avg_cost': ['avg cost', 'average cost', 'avg price', 'average price', 'purchase price', 'cost per share',
                 'price paid', 'buy price', 'unit cost', 'cost share', 'avg cost basis', 'average cost basis',
                 'cost basis per share', 'acquisition price', 'entry price', 'avg_cost', 'avg buy price'],
    'total_cost': ['total cost', 'cost basis', 'cost', 'total invested', 'invested', 'amount invested', 'book value',
                   'total cost basis', 'cost of acquisition', 'acquisition cost'],
    'acquired': ['date of acquisition', 'acquisition date', 'acquired', 'date acquired', 'purchase date', 'buy date',
                 'trade date', 'date', 'open date', 'date purchased', 'acquired on', 'bought on', 'bought'],
    'name': ['stock name', 'name', 'description', 'security', 'security name', 'company', 'company name'],
    'price': ['current price', 'price', 'last price', 'market price', 'last', 'close'],
    'value': ['current value', 'market value', 'value', 'total value', 'mkt value'],
    'total_return': ['total return', 'gain loss', 'total gain loss', 'unrealized gain loss', 'gain', 'return', 'p l', 'profit loss'],
}

_NOT_TICKERS = {
    'TOTAL', 'TOTALS', 'CASH', 'SUBTOTAL', 'NAN', 'NONE', 'NULL', 'SYMBOL', 'TICKER', 'N/A', 'NA', '-', '--',
    'ACCOUNT', 'PENDING', 'MONEY', 'SWEEP', 'CORE',
}

# Words an OCR pass will surface that look like tickers but are not.
_EXCLUDE_WORDS = {
    'A', 'I', 'AM', 'PM', 'USD', 'CAD', 'ETF', 'INC', 'LLC', 'LTD', 'PLC',
    'ADR', 'CORP', 'CO', 'NA', 'NV', 'SE', 'AG', 'SA', 'THE', 'AND', 'FOR',
    'NEW', 'NET', 'EST', 'AVG', 'TOTAL', 'GAIN', 'LOSS', 'PRICE', 'VALUE',
    'RETURN', 'COST', 'BASIS', 'MARKET', 'ACCOUNT', 'BALANCE', 'SHARES',
    'STOCK', 'PORTFOLIO', 'TODAY', 'OPEN', 'CLOSE', 'HIGH', 'LOW', 'BUY',
    'SELL', 'TRADE', 'ORDER', 'TYPE', 'QTY', 'SYMBOL', 'NAME', 'MY', 'OF',
    'IN', 'AT', 'BY', 'NO', 'ON', 'UP', 'OR', 'TO', 'IT', 'DATE',
}

TICKER_RE = re.compile(r'^[A-Z][A-Z0-9]{0,5}([.\-][A-Z0-9]{1,3})?$')


def _norm_header(s) -> str:
    s = str(s or '').lower().replace('\n', ' ')
    s = re.sub(r'\(.*?\)', ' ', s)            # "Exchange (optional)"
    s = s.replace('_', ' ').replace('/', ' ')
    s = re.sub(r'[^a-z0-9# ]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def _role_of(header: str):
    h = _norm_header(header)
    if not h:
        return None
    for role, names in ROLES.items():
        if h in names:
            return role
    # "Contains" match for descriptive headers ("Average cost per share ($)").
    for role in ('acquired', 'avg_cost', 'total_cost', 'shares', 'ticker', 'total_return', 'value', 'price', 'name'):
        for n in ROLES[role]:
            if len(n) >= 5 and n in h:
                return role
    return None


# ── cell parsing ─────────────────────────────────────────────────────────────

def _num(v):
    """'1,070.16' / '$1.71' / '(5.00)' / '-$6.63' / 12 -> float, else None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return None if (isinstance(v, float) and math.isnan(v)) else float(v)
    s = str(v).strip()
    if not s or s in {'-', '—', '--'}:
        return None
    neg = s.startswith('(') and s.endswith(')')
    s = re.sub(r'[^0-9.\-eE]', '', s)
    if not s or s in {'-', '.'}:
        return None
    try:
        x = float(s)
    except ValueError:
        return None
    return -abs(x) if neg else x


def _date(v):
    """Many date spellings (and Excel serial numbers) -> 'YYYY-MM-DD', else None."""
    if v is None:
        return None
    if isinstance(v, (datetime, date, pd.Timestamp)):
        return pd.Timestamp(v).strftime('%Y-%m-%d')
    if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)):
        if 20000 < v < 80000:  # Excel serial date
            return (datetime(1899, 12, 30) + timedelta(days=float(v))).strftime('%Y-%m-%d')
        return None
    s = str(v).strip()
    if not s or s in {'-', '—'}:
        return None
    for fmt in ('%m/%d/%Y', '%m/%d/%y', '%Y-%m-%d', '%d-%b-%Y', '%b %d, %Y', '%B %d, %Y', '%d %b %Y', '%Y/%m/%d', '%m-%d-%Y'):
        try:
            return datetime.strptime(s, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    try:
        ts = pd.to_datetime(s, errors='coerce')
        return None if pd.isna(ts) else ts.strftime('%Y-%m-%d')
    except Exception:
        return None


def _ticker(v):
    s = str(v or '').strip().upper()
    s = s.split(':')[-1]                  # "NASDAQ:AAPL"
    s = s.replace(' ', '')
    if s in _NOT_TICKERS or not TICKER_RE.match(s):
        return None
    return s


# ── the table detector ───────────────────────────────────────────────────────

def holdings_from_rows(rows: list, source: str = 'file') -> tuple:
    """Find the header row in a grid of cells and turn the rows below into holdings.

    Returns (holdings, notes).
    """
    rows = [[('' if c is None else c) for c in r] for r in rows if r is not None]
    best, best_score = None, 0
    for i, r in enumerate(rows[:60]):
        roles = [_role_of(c) for c in r]
        if 'ticker' not in roles:
            continue
        score = len({x for x in roles if x})
        if score > best_score:
            best, best_score = i, score
    if best is None or best_score < 2:
        return [], []

    header = rows[best]
    cols: dict = {}
    for j, c in enumerate(header):
        role = _role_of(c)
        if role and role not in cols:
            cols[role] = j
    # "Symbol" beats a "Name" column that also looked like a ticker source.
    get = lambda r, role: r[cols[role]] if role in cols and cols[role] < len(r) else None

    raw = []
    for r in rows[best + 1:]:
        t = _ticker(get(r, 'ticker'))
        if not t:
            continue
        raw.append({
            'ticker': t,
            'shares': _num(get(r, 'shares')),
            'avg_cost': _num(get(r, 'avg_cost')),
            'total_cost': _num(get(r, 'total_cost')),
            'acquired': _date(get(r, 'acquired')),
            'name': (str(get(r, 'name')).strip() or None) if get(r, 'name') not in (None, '', '-') else None,
            'price': _num(get(r, 'price')),
            'value': _num(get(r, 'value')),
            'total_return': _num(get(r, 'total_return')),
        })

    notes = []
    per_share = _total_cost_is_per_share(raw) if 'total_cost' in cols and 'avg_cost' not in cols else False
    if per_share:
        notes.append(f'{source}: the “{header[cols["total_cost"]]}” column holds a cost per share (it matches your '
                     f'price and return columns), so it was read as average cost.')

    out = []
    for h in raw:
        shares, avg = h['shares'], h['avg_cost']
        tc = h['total_cost']
        if avg is None and tc is not None:
            if per_share:
                avg = tc
            elif shares:
                avg = tc / shares
        if (shares is None or shares <= 0) and h['value'] and h['price']:
            shares = h['value'] / h['price']
        if not shares or shares <= 0:
            continue
        out.append({'ticker': h['ticker'], 'shares': round(shares, 6), 'avg_cost': round(avg, 4) if avg else None,
                    'acquired': h['acquired'], 'name': h['name']})

    dated = sum(1 for h in out if h['acquired'])
    if out and dated < len(out):
        notes.append(f'{source}: {len(out) - dated} of {len(out)} positions have no acquisition date; add them in the review table to unlock the “since you bought” dashboards.')
    return out, notes


def _total_cost_is_per_share(raw: list) -> bool:
    """A column called "Total Cost" sometimes holds a per-share cost (the Google
    Finance tracker template does). Decide per file, by majority vote, using the
    return column if there is one and the price column otherwise."""
    votes_per, votes_total = 0, 0
    for h in raw:
        tc, sh = h['total_cost'], h['shares']
        if not tc or not sh or abs(sh - 1) < 1e-9:
            continue  # with one share both readings are identical, so the row can't vote
        if h['value'] is not None and h['total_return'] is not None:
            implied_total = h['value'] - h['total_return']
            if abs(tc * sh - implied_total) < abs(tc - implied_total):
                votes_per += 1
            else:
                votes_total += 1
        elif h['price']:
            per_as_is = abs(math.log(max(tc, 1e-9) / h['price']))
            per_divided = abs(math.log(max(tc / sh, 1e-9) / h['price']))
            if per_as_is < per_divided:
                votes_per += 1
            else:
                votes_total += 1
    return votes_per > votes_total


# ── file readers: each turns a file into grids of cells ──────────────────────

def _grids_from_csv(content: bytes) -> list:
    text = content.decode('utf-8-sig', errors='replace')
    sep = '\t' if text.count('\t') > text.count(',') else ','
    df = pd.read_csv(io.StringIO(text), header=None, dtype=str, sep=sep, engine='python', on_bad_lines='skip', keep_default_na=False)
    return [df.values.tolist()]


def _grids_from_excel(content: bytes) -> list:
    try:
        sheets = pd.read_excel(io.BytesIO(content), sheet_name=None, header=None)
    except ImportError as exc:
        raise IngestError('Reading this spreadsheet needs an extra package: pip install openpyxl (xlsx), xlrd (xls) or odfpy (ods).') from exc
    return [df.where(pd.notna(df), None).values.tolist() for df in sheets.values()]


def _grids_from_json(content: bytes) -> list:
    data = json.loads(content.decode('utf-8-sig'))
    if isinstance(data, dict):
        data = data.get('holdings') or data.get('positions') or next((v for v in data.values() if isinstance(v, list)), [])
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return []
    keys = list(dict.fromkeys(k for d in data for k in d))
    return [[keys] + [[d.get(k) for k in keys] for d in data]]


def _pdf_text_and_tables(content: bytes) -> tuple:
    try:
        import pdfplumber
    except ImportError as exc:
        raise IngestError('Reading PDFs needs: pip install pdfplumber') from exc
    grids, text = [], []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            for t in page.extract_tables() or []:
                grids.append(t)
            text.append(page.extract_text() or '')
    return grids, '\n'.join(text)


def _docx_text_and_tables(content: bytes) -> tuple:
    try:
        import docx
    except ImportError as exc:
        raise IngestError('Reading Word files needs: pip install python-docx') from exc
    d = docx.Document(io.BytesIO(content))
    grids = [[[c.text for c in row.cells] for row in t.rows] for t in d.tables]
    text = '\n'.join(p.text for p in d.paragraphs)
    return grids, text


def _grids_from_text(text: str) -> list:
    """Plain text with a delimiter-separated table inside it."""
    lines = [l for l in text.splitlines() if l.strip()]
    for sep in ('\t', ',', ';', '|'):
        if sum(1 for l in lines if l.count(sep) >= 2) >= 2:
            return [[[c.strip() for c in l.split(sep)] for l in lines]]
    # Columns separated by runs of spaces (statement text).
    return [[re.split(r'\s{2,}', l.strip()) for l in lines]]


IMAGE_EXT = {'png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'tif', 'tiff', 'heic'}
SUPPORTED = ['csv', 'tsv', 'txt', 'xlsx', 'xlsm', 'xls', 'ods', 'json', 'pdf', 'docx'] + sorted(IMAGE_EXT)


def parse_file(filename: str, content: bytes) -> tuple:
    """Any supported file -> (holdings, notes)."""
    name = filename or 'file'
    ext = name.rsplit('.', 1)[-1].lower() if '.' in name else ''
    text_fallback = None

    if ext in ('csv', 'tsv', 'txt', ''):
        grids = _grids_from_csv(content)
        if ext == 'txt':
            grids += _grids_from_text(content.decode('utf-8', errors='replace'))
            text_fallback = content.decode('utf-8', errors='replace')
    elif ext in ('xlsx', 'xlsm', 'xls', 'ods'):
        grids = _grids_from_excel(content)
    elif ext == 'json':
        grids = _grids_from_json(content)
    elif ext == 'pdf':
        grids, text_fallback = _pdf_text_and_tables(content)
        grids += _grids_from_text(text_fallback)
    elif ext == 'docx':
        grids, text_fallback = _docx_text_and_tables(content)
        grids += _grids_from_text(text_fallback)
    elif ext in IMAGE_EXT:
        holdings = parse_screenshot(content)
        return holdings, [f'{name}: read from an image. Please check every row; OCR can misread numbers.'] if holdings else []
    elif ext == 'doc':
        raise IngestError('Old .doc files cannot be read directly. Save it as .docx or PDF and upload again.')
    else:
        raise IngestError(f'{name}: unsupported file type .{ext}. Supported: {", ".join(SUPPORTED)}')

    holdings, notes = [], []
    for g in grids:
        h, n = holdings_from_rows(g, name)
        if h:
            holdings.extend(h)
            notes.extend(n)
            if ext not in ('xlsx', 'xlsm', 'xls', 'ods'):
                break  # first table that works; spreadsheets may hold one table per tab
    if not holdings and text_fallback:
        holdings = parse_brokerage_text(text_fallback)
        if holdings:
            notes.append(f'{name}: no table found, so holdings were picked out of the text. Please check them.')
    if not holdings:
        raise IngestError(f'{name}: no holdings found. The file needs a column like “Symbol” or “Ticker” and one like “Shares” or “Quantity”.')
    return holdings, notes


def sheet_url_to_csv(url: str) -> str:
    """https://docs.google.com/spreadsheets/d/<id>/edit#gid=<gid> -> its CSV export URL."""
    m = re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', url or '')
    if not m:
        raise IngestError('That does not look like a Google Sheets link.')
    gid = re.search(r'[#&?]gid=(\d+)', url)
    return f'https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv' + (f'&gid={gid.group(1)}' if gid else '')


def parse_sheet_url(url: str) -> tuple:
    import urllib.request
    csv_url = sheet_url_to_csv(url)
    try:
        with urllib.request.urlopen(urllib.request.Request(csv_url, headers={'User-Agent': 'portfolio-intelligence'}), timeout=20) as r:
            content = r.read()
    except Exception as exc:
        raise IngestError('Could not open the sheet. In Google Sheets choose Share → “Anyone with the link can view”, then try again.') from exc
    if content[:15].lower().startswith(b'<!doctype html') or b'<html' in content[:200].lower():
        raise IngestError('The sheet is private. Share it as “Anyone with the link can view”, or download it as CSV/XLSX and upload the file.')
    return parse_file('google-sheet.csv', content)


# Backwards-compatible entry point for the old CSV route.
def parse_csv(content: str) -> list:
    holdings, _ = parse_file('upload.csv', content.encode('utf-8'))
    return holdings


# ── images (OCR) ─────────────────────────────────────────────────────────────

def parse_screenshot(image_bytes: bytes) -> list:
    """OCR a brokerage screenshot into holdings. Requires pytesseract + pillow."""
    try:
        import pytesseract
        from PIL import Image, ImageEnhance, ImageFilter
    except ImportError as exc:
        raise IngestError(
            'Reading images needs Tesseract: pip install pytesseract pillow '
            'and brew install tesseract. Or upload a CSV, spreadsheet or PDF instead.'
        ) from exc

    img = Image.open(io.BytesIO(image_bytes)).convert('RGB')
    img = ImageEnhance.Contrast(img).enhance(1.8)
    img = img.filter(ImageFilter.SHARPEN)
    text = pytesseract.image_to_string(img, config='--psm 6')
    return parse_brokerage_text(text)


def parse_brokerage_text(text: str) -> list:
    """Heuristic extraction of ticker / shares / avg_cost (and a date) from free text."""
    holdings, seen = [], set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        acquired = None
        m = re.search(r'\b(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2})\b', line)
        if m:
            acquired = _date(m.group(1))
            line_wo = line.replace(m.group(1), ' ')
        else:
            line_wo = line
        tickers = re.findall(r'\b([A-Z]{1,5})\b', line_wo)
        raw_nums = re.findall(r'[\d,]+\.?\d*', line_wo)
        valid = [t for t in tickers if t not in _EXCLUDE_WORDS and 1 < len(t) <= 5]
        if not valid or not raw_nums:
            continue
        ticker = valid[0]
        if ticker in seen:
            continue
        nums = [x for x in (_num(n) for n in raw_nums) if x is not None]
        if not nums:
            continue
        seen.add(ticker)
        shares = nums[0]
        avg_cost = nums[1] if len(nums) >= 2 else None
        if shares > 0:
            holdings.append({'ticker': ticker, 'shares': shares, 'avg_cost': avg_cost, 'acquired': acquired, 'name': None})
    return holdings


# ── request payload -> analysis inputs ───────────────────────────────────────

def clean_lots(holdings_list: list) -> list:
    """Validated lots from the review table."""
    lots = []
    for h in holdings_list:
        ticker = _ticker(h.get('ticker'))
        qty = _num(h.get('shares'))
        if not ticker or not qty or qty <= 0:
            continue
        cost = _num(h.get('avg_cost'))
        lots.append({'ticker': ticker, 'shares': qty, 'avg_cost': cost if cost and cost > 0 else None,
                     'acquired': _date(h.get('acquired'))})
    return lots


def normalise(holdings_list: list) -> tuple:
    """Lots -> (shares, purchase_prices) keyed by ticker. Several lots of one ticker
    are summed, with a share-weighted average cost."""
    shares, cost_total, cost_shares = {}, {}, {}
    for lot in clean_lots(holdings_list):
        t = lot['ticker']
        shares[t] = shares.get(t, 0.0) + lot['shares']
        if lot['avg_cost'] is not None:
            cost_total[t] = cost_total.get(t, 0.0) + lot['avg_cost'] * lot['shares']
            cost_shares[t] = cost_shares.get(t, 0.0) + lot['shares']
    purchase_prices = {t: cost_total[t] / cost_shares[t] for t in cost_total if cost_shares.get(t)}
    return shares, purchase_prices
