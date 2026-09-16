#!/usr/bin/env python3
"""
Portfolio Intelligence Platform — Flask server.

Routes
  GET  /                      dashboard UI
  GET  /api/health            liveness probe
  POST /api/parse/csv         brokerage CSV -> holdings
  POST /api/parse/screenshot  brokerage screenshot -> holdings (OCR)
  POST /api/analyze           holdings -> P&L, optimization, PRISM

One POST /api/analyze builds a single MarketData object and passes it to the
valuation, optimizer and PRISM layers in turn. Before the merge this was two
services on two stacks (Flask + FastAPI) that each did their own downloads and
each derived their own weights.
"""

import os
import time

from flask import Flask, jsonify, render_template, request

from core import ingest, optimizer, portfolio, prism
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

@app.route('/api/parse/csv', methods=['POST'])
def parse_csv():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    try:
        content = request.files['file'].read().decode('utf-8', errors='replace')
        return jsonify({'holdings': ingest.parse_csv(content)})
    except ingest.IngestError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/api/parse/screenshot', methods=['POST'])
def parse_screenshot():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    try:
        holdings = ingest.parse_screenshot(request.files['file'].read())
    except ingest.IngestError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    if not holdings:
        return jsonify({
            'holdings': [],
            'note': 'Could not extract holdings automatically. Please add them manually.',
        })

    return jsonify({
        'holdings': holdings,
        'note': 'Review and correct the parsed data — OCR may have errors.',
    })


# ── analyze ──────────────────────────────────────────────────────────────────

@app.route('/api/analyze', methods=['POST'])
def analyze():
    started = time.time()
    reset_counters()

    body = request.get_json(force=True, silent=True) or {}
    shares, purchase_prices = ingest.normalise(body.get('holdings', []))

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
        'optimization': optimizer.analyse(md, weights),
        'prism': prism.compute(md, weights),
        'meta': {
            'dropped_tickers': md.dropped,
            'elapsed_ms': int((time.time() - started) * 1000),
            'fetches': counters(),
        },
    }

    return jsonify(payload)


# ── entry ────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=bool(os.environ.get('DEBUG')), port=port)
