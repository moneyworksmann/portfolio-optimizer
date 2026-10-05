#!/usr/bin/env python3
"""
Portfolio Intelligence Platform — Flask server.

Routes
  GET  /                      dashboard UI
  GET  /api/health            liveness probe
  POST /api/parse             files (csv/xlsx/ods/json/pdf/docx/images) and/or a
                              Google Sheets link -> holdings with acquisition dates
  POST /api/parse/csv         legacy single-CSV route
  POST /api/parse/screenshot  brokerage screenshot -> holdings (OCR)
  POST /api/analyze           holdings -> P&L, optimization, PRISM, since-you-bought

One POST /api/analyze builds a single MarketData object and passes it to the
valuation, optimizer and PRISM layers in turn. Before the merge this was two
services on two stacks (Flask + FastAPI) that each did their own downloads and
each derived their own weights.
"""

import os
import time

from flask import Flask, jsonify, render_template, request

from core import hindsight, ingest, optimizer, portfolio, prism
from core.market_data import MarketData, counters, reset_counters

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32 MB


# ── UI ───────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})


# ── ingest ───────────────────────────────────────────────────────────────────

@app.route('/api/parse', methods=['POST'])
def parse_any():
    """Any number of files (CSV, Excel, Sheets export, JSON, PDF, Word, images)
    and/or a Google Sheets link -> one combined list of holdings."""
    holdings, notes, errors = [], [], []
    for f in request.files.getlist('files'):
        try:
            h, n = ingest.parse_file(f.filename or 'file', f.read())
            for x in h:
                x['source'] = f.filename
            holdings.extend(h)
            notes.extend(n)
        except ingest.IngestError as e:
            errors.append(str(e))
        except Exception as e:  # a malformed file shouldn't sink the others
            errors.append(f'{f.filename}: {e}')
    url = (request.form.get('sheet_url') or '').strip()
    if url:
        try:
            h, n = ingest.parse_sheet_url(url)
            for x in h:
                x['source'] = 'Google Sheet'
            holdings.extend(h)
            notes.extend(n)
        except ingest.IngestError as e:
            errors.append(str(e))
    if not holdings:
        return jsonify({'error': ' '.join(errors) or 'No files received.'}), 400
    return jsonify({'holdings': holdings, 'notes': notes, 'errors': errors})


@app.route('/api/parse/csv', methods=['POST'])
def parse_csv():
    """Kept for old clients; /api/parse handles every format."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    f = request.files['file']
    try:
        h, n = ingest.parse_file(f.filename or 'upload.csv', f.read())
        return jsonify({'holdings': h, 'notes': n})
    except ingest.IngestError as e:
        return jsonify({'error': str(e)}), 400


# ── analyze ──────────────────────────────────────────────────────────────────

@app.route('/api/analyze', methods=['POST'])
def analyze():
    started = time.time()
    reset_counters()

    body = request.get_json(force=True, silent=True) or {}
    lots = ingest.clean_lots(body.get('holdings', []))
    shares, purchase_prices = ingest.normalise(lots)

    if not shares:
        return jsonify({'error': 'No holdings provided'}), 400

    # Single download feeding everything below.
    md = MarketData(list(shares), period='5y')

    if not md.valid:
        return jsonify({
            'error': 'Could not fetch price data for any of these tickers. '
                     'Check that they are valid stock symbols.'
        }), 400

    prices, purchase = portfolio.resolve_prices(md, shares, purchase_prices)
    book = portfolio.calculate(shares, prices, purchase)
    weights = portfolio.weights_from(book)

    total_cost = book['total_cost']

    payload = {
        'summary': {
            'total_value': round(book['total_value'], 2),
            'total_cost': round(total_cost, 2),
            'total_gain': round(book['total_gain'], 2),
            'total_gain_pct': round(
                (book['total_gain'] / total_cost * 100) if total_cost else 0.0, 2
            ),
            'positions': len(shares),
        },
        'holdings': portfolio.holdings_detail(shares, prices, purchase, book, md.sectors),
        'sector_allocation': {
            k: round(v, 2) for k, v in portfolio.sector_allocation(book, md.sectors).items()
        },
        'performance': portfolio.performance_vs_benchmark(md, shares, purchase),
        'optimization': optimizer.analyse(md, weights, book['total_value']),
        'prism': prism.compute(md, weights),
        'hindsight': _hindsight(lots, md),
        'meta': {
            'dropped_tickers': md.dropped,
            'elapsed_ms': int((time.time() - started) * 1000),
            'fetches': counters(),
        },
    }

    return jsonify(payload)


def _hindsight(lots, md):
    try:
        return hindsight.analyse([l for l in lots if l['ticker'] in md.valid], md.sectors)
    except Exception as e:  # never let the history view sink the whole analysis
        return {'available': False, 'reason': f'Could not build the since-you-bought view: {e}'}


# ── re-optimize with candidate stocks ───────────────────────────────────────

@app.route('/api/reoptimize', methods=['POST'])
def reoptimize():
    """Re-run the optimizer with candidate tickers added to the universe,
    and compute PRISM for both the current and suggested portfolios."""
    started = time.time()
    reset_counters()

    body = request.get_json(force=True, silent=True) or {}
    lots = ingest.clean_lots(body.get('holdings', []))
    shares, purchase_prices = ingest.normalise(lots)
    candidates = list(dict.fromkeys(
        t.upper().strip() for t in body.get('candidates', [])
        if t.strip() and t.upper().strip() not in shares
    ))

    if not shares:
        return jsonify({'error': 'No holdings provided'}), 400
    if not candidates:
        return jsonify({'error': 'No candidate tickers provided'}), 400

    all_tickers = list(shares) + candidates
    md = MarketData(all_tickers, period='5y')

    if not md.valid:
        return jsonify({'error': 'Could not fetch price data.'}), 400

    valid_candidates = [c for c in candidates if c in md.valid]
    invalid_candidates = [c for c in candidates if c not in md.valid]

    prices, purchase = portfolio.resolve_prices(md, shares, purchase_prices)
    book = portfolio.calculate(shares, prices, purchase)
    weights = portfolio.weights_from(book)

    for c in valid_candidates:
        weights[c] = 0.0

    optimization = optimizer.analyse(md, weights, book['total_value'])

    current_weights = portfolio.weights_from(book)
    prism_current = prism.compute(md, current_weights)

    prism_suggested = None
    if optimization.get('available') and optimization.get('strategies', {}).get('optimal'):
        opt_pcts = optimization['strategies']['optimal']['weights']
        opt_weights = {t: v / 100.0 for t, v in opt_pcts.items()}
        prism_suggested = prism.compute(md, opt_weights)

    payload = {
        'optimization': optimization,
        'prism_current': prism_current,
        'prism_suggested': prism_suggested,
        'candidates': valid_candidates,
        'invalid_candidates': invalid_candidates,
        'meta': {
            'elapsed_ms': int((time.time() - started) * 1000),
            'fetches': counters(),
        },
    }
    return jsonify(payload)


# ── entry ────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=bool(os.environ.get('DEBUG')), port=port)
