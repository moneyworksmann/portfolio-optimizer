#!/usr/bin/env python3
"""
Portfolio Intelligence Platform — Flask server.

Routes
  GET  /                      dashboard UI
  GET  /stress                stress test page (sliders + Monte Carlo)
  GET  /api/health            liveness probe
  POST /api/parse             files (csv/xlsx/ods/json/pdf/docx/images) and/or a
                              Google Sheets link -> holdings with acquisition dates
  POST /api/parse/csv         legacy single-CSV route
  POST /api/parse/screenshot  brokerage screenshot -> holdings (OCR)
  POST /api/analyze           holdings -> P&L, optimization, PRISM, since-you-bought,
                              Monte Carlo return distribution
  POST /api/simulate          holdings + options -> Monte Carlo return distribution
  POST /api/sensitivity/model     holdings -> factor betas for the stress test
  POST /api/sensitivity/simulate  model + slider settings -> scenario + Monte Carlo
  GET  /api/portfolio         the saved ("watched") portfolio          (owner key)
  POST /api/portfolio         save holdings + watchlist for the news loop (owner key)
  GET  /api/intel             news signals, scored items, suggestions   (owner key)
  POST /api/intel/run         one pass of the news loop; the scheduler calls this (owner key)

One POST /api/analyze builds a single MarketData object and passes it to the
valuation, optimizer and PRISM layers in turn. Before the merge this was two
services on two stacks (Flask + FastAPI) that each did their own downloads and
each derived their own weights.
"""

import hmac
import math
import os
import time

import numpy as np
from flask import Flask, jsonify, render_template, request

from core import hindsight, ingest, intel, montecarlo, optimizer, portfolio, prism, sensitivity, store
from core.market_data import MarketData, counters, lookup_sectors, reset_counters

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024  # 32 MB


# ── UI ───────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/stress')
def stress_page():
    """Stress test: live sensitivity sliders + Monte Carlo, on its own page."""
    return render_template('stress.html')


@app.route('/api/health')
def health():
    return jsonify({'status': 'ok'})


# ── saved portfolio + news loop (owner only) ─────────────────────────────────

_LOOPBACK = {'127.0.0.1', '::1', 'localhost'}


def _is_owner() -> bool:
    """Bearer INTEL_TOKEN, or — when no token is configured — a request from this
    machine (./run.sh on your Mac). On Vercel without a token, nobody gets in."""
    token = os.environ.get('INTEL_TOKEN', '').strip()
    header = request.headers.get('Authorization', '')
    if token:
        given = header[7:].strip() if header.startswith('Bearer ') else ''
        return bool(given) and hmac.compare_digest(given.encode(), token.encode())
    if os.environ.get('VERCEL'):
        return False
    return request.remote_addr in _LOOPBACK and not request.headers.get('X-Forwarded-For')


def _owner_only():
    if _is_owner():
        return None
    msg = ('Owner key required.' if os.environ.get('INTEL_TOKEN')
           else 'Set INTEL_TOKEN on the server to use this from outside your own computer.')
    return jsonify({'error': msg, 'needs_key': True}), 401


@app.route('/api/portfolio', methods=['GET'])
def get_portfolio():
    if (denied := _owner_only()):
        return denied
    saved = store.get('portfolio')
    if not saved:
        return jsonify({'error': 'No saved portfolio yet.'}), 404
    return jsonify(saved)


@app.route('/api/portfolio', methods=['POST'])
def save_portfolio():
    if (denied := _owner_only()):
        return denied
    body = request.get_json(force=True, silent=True) or {}
    lots = ingest.clean_lots(body.get('holdings', []))
    lots = [l for l in lots if l.get('ticker') and (l.get('shares') or 0) > 0]
    if not lots:
        return jsonify({'error': 'No holdings to save.'}), 400
    held = {l['ticker'] for l in lots}
    candidates = list(dict.fromkeys(
        str(c).upper().strip() for c in body.get('candidates', []) or []
        if str(c).strip() and str(c).upper().strip() not in held
    ))[:30]
    saved = {'saved_at': store.now_iso(), 'holdings': lots, 'candidates': candidates}
    try:
        store.put('portfolio', saved)
    except store.StoreUnavailable as e:
        return jsonify({'error': str(e)}), 503
    return jsonify({'ok': True, 'saved_at': saved['saved_at'],
                    'holdings': len(lots), 'tickers': len(held), 'candidates': candidates})


@app.route('/api/intel', methods=['GET'])
def intel_view():
    if (denied := _owner_only()):
        return denied
    return jsonify(_sanitize(intel.view()))


@app.route('/api/intel/run', methods=['POST'])
def intel_run():
    if (denied := _owner_only()):
        return denied
    started = time.time()
    try:
        summary = intel.run()
    except store.StoreUnavailable as e:
        return jsonify({'ok': False, 'error': str(e)}), 503
    summary['elapsed_ms'] = int((time.time() - started) * 1000)
    return jsonify(_sanitize(summary)), (200 if summary.get('ok') else 409)



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
        'optimization': (opt := optimizer.analyse(md, weights, book['total_value'])),
        'prism': prism.compute(md, weights),
        'prism_max': _prism_max(md, weights),
        'prism_suggested': _prism_for_optimal(md, opt),
        'hindsight': _hindsight(lots, md),
        'monte_carlo': _monte_carlo(md, weights, book['total_value'], opt),
        'meta': {
            'dropped_tickers': md.dropped,
            'elapsed_ms': int((time.time() - started) * 1000),
            'fetches': counters(),
        },
    }

    return jsonify(_sanitize(payload))


def _sanitize(obj):
    """Replace NaN/Infinity floats with None so json.dumps doesn't choke."""
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v) for v in obj]
    return obj


def _hindsight(lots, md):
    try:
        return hindsight.analyse([l for l in lots if l['ticker'] in md.valid], md.sectors)
    except Exception as e:  # never let the history view sink the whole analysis
        return {'available': False, 'reason': f'Could not build the since-you-bought view: {e}'}


# Fixed seed on the dashboard so a refresh shows the same distribution; the
# numbers only move when holdings or prices do.
DASHBOARD_SEED = 7
DASHBOARD_PATHS = 2000


def _monte_carlo(md, weights, total_value, opt):
    """Return distribution for today's mix and, when available, the optimizer's."""
    try:
        compare = {}
        if opt.get('available') and opt.get('strategies', {}).get('optimal'):
            pcts = opt['strategies']['optimal']['weights']
            compare['optimal'] = {t: v / 100.0 for t, v in pcts.items()}
        return montecarlo.analyse(
            md, weights, total_value, n_paths=DASHBOARD_PATHS,
            compare=compare, seed=DASHBOARD_SEED,
        )
    except Exception as e:  # never let the simulation sink the whole analysis
        return {'available': False, 'reason': f'Could not run the simulation: {e}'}


def _prism_max(md, weights):
    """Compute the maximum achievable PRISM score for the current tickers."""
    try:
        tickers = [t for t in md.valid if t in weights and weights[t] > 0]
        if len(tickers) < 2:
            return None
        total = sum(weights[t] for t in tickers)
        norm = {t: weights[t] / total for t in tickers}
        return prism.max_achievable(md, tickers, norm)
    except Exception:
        return None


def _prism_for_optimal(md, opt):
    """Compute PRISM on the optimizer's suggested weights."""
    try:
        if not opt.get('available') or not opt.get('strategies', {}).get('optimal'):
            return None
        pcts = opt['strategies']['optimal']['weights']
        w = {t: v / 100.0 for t, v in pcts.items()}
        return prism.compute(md, w)
    except Exception:
        return None


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
    return jsonify(_sanitize(payload))


# ── Monte Carlo ─────────────────────────────────────────────────────────────

def _int_opt(body, key, default):
    v = body.get(key, default)
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise montecarlo.SimulationError(f'{key} must be a whole number.')


@app.route('/api/simulate', methods=['POST'])
def simulate():
    """Monte Carlo distribution for the holdings, with tunable assumptions.

    Body
      holdings        same shape as /api/analyze
      horizon_days    trading days to simulate (default 252 = one year)
      paths           number of simulated paths (default 5000, max 50000)
      method          normal | student_t | bootstrap (default normal)
      lookback_days   history window for the estimates (default: all 5y)
      block           bootstrap block length in days (default 1)
      df              Student-t degrees of freedom (default 5)
      seed            fix for reproducible output
      weights         optional {ticker: weight} to simulate instead of today's mix
                      (fractions or percentages; renormalised either way)
    """
    started = time.time()
    reset_counters()

    body = request.get_json(force=True, silent=True) or {}
    lots = ingest.clean_lots(body.get('holdings', []))
    shares, purchase_prices = ingest.normalise(lots)
    override = {
        str(t).upper().strip(): float(v) for t, v in (body.get('weights') or {}).items()
        if isinstance(v, (int, float)) and v > 0
    }
    if not shares and not override:
        return jsonify({'error': 'No holdings provided'}), 400

    try:
        method = str(body.get('method', 'normal'))
        options = dict(
            horizon_days=_int_opt(body, 'horizon_days', montecarlo.TRADING_DAYS),
            n_paths=_int_opt(body, 'paths', montecarlo.DEFAULT_PATHS),
            method=method,
            lookback_days=_int_opt(body, 'lookback_days', None),
            seed=_int_opt(body, 'seed', None),
            block=_int_opt(body, 'block', 1),
        )
        if 'df' in body:
            options['df'] = float(body['df'])
    except (montecarlo.SimulationError, TypeError, ValueError) as e:
        return jsonify({'error': str(e)}), 400

    md = MarketData(list(dict.fromkeys(list(shares) + list(override))), period='5y')
    if not md.valid:
        return jsonify({'error': 'Could not fetch price data for any of these tickers.'}), 400

    total_value = 0.0
    if shares:
        prices, purchase = portfolio.resolve_prices(md, shares, purchase_prices)
        book = portfolio.calculate(shares, prices, purchase)
        total_value = book['total_value']
        weights = portfolio.weights_from(book)
    if override:
        weights = override

    try:
        result = montecarlo.analyse(md, weights, total_value, **options)
    except montecarlo.SimulationError as e:
        return jsonify({'error': str(e)}), 400

    result['meta'] = {
        'dropped_tickers': md.dropped,
        'elapsed_ms': int((time.time() - started) * 1000),
        'fetches': counters(),
    }
    return jsonify(_sanitize(result))


# ── stress test: live sensitivity + Monte Carlo ──────────────────────────────

_MODEL_CACHE: dict = {}
_MODEL_TTL = 30 * 60


@app.route('/api/sensitivity/model', methods=['POST'])
def sensitivity_model():
    """Holdings -> factor betas, factor covariance and presets. One download;
    the browser keeps the result and sends it back with every slider move."""
    body = request.get_json(force=True, silent=True) or {}
    items = body.get('holdings', [])
    tickers = list(dict.fromkeys(
        str(h.get('ticker', '')).upper().strip() for h in items if str(h.get('ticker', '')).strip()
    ))[:100]
    if not tickers:
        return jsonify({'error': 'No holdings provided'}), 400
    sectors = {str(h.get('ticker', '')).upper().strip(): h.get('sector')
               for h in items if h.get('sector')}

    key = tuple(sorted(tickers))
    hit = _MODEL_CACHE.get(key)
    if hit and time.time() - hit[0] < _MODEL_TTL:
        return jsonify(hit[1])

    missing = [t for t in tickers if t not in sectors]
    if missing:
        try:
            sectors.update(lookup_sectors(missing))
        except Exception:
            pass
    model = _sanitize(sensitivity.build_model(tickers, sectors))
    if model.get('available'):
        _MODEL_CACHE[key] = (time.time(), model)
    return jsonify(model)


@app.route('/api/sensitivity/simulate', methods=['POST'])
def sensitivity_simulate():
    """Model + slider settings -> scenario P&L and Monte Carlo. No downloads."""
    body = request.get_json(force=True, silent=True) or {}
    model = body.get('model') or {}
    try:
        keys = list(model['factor_keys'])
        if not 1 <= len(keys) <= len(sensitivity.FACTORS) or 'market' not in keys:
            raise ValueError
        if len(model.get('assets', [])) > 100:
            raise ValueError
        values = {str(k): float(v) for k, v in (body.get('values') or {}).items()}

        def num(name, default, lo, hi):
            try:
                return min(hi, max(lo, float(body.get(name, default))))
            except (TypeError, ValueError):
                return default

        result = sensitivity.simulate(
            model, values,
            shocks={k: float(v) for k, v in (body.get('shocks') or {}).items() if k in keys},
            sector_shocks={str(k): float(v) for k, v in (body.get('sector_shocks') or {}).items()},
            vol_mult=num('vol_mult', 1.0, 0.25, 4.0),
            horizon_months=int(num('horizon_months', 12, 1, 120)),
            market_return=num('market_return', 0.07, -0.5, 0.5),
            linked=bool(body.get('linked', True)),
            fat_tails=bool(body.get('fat_tails', True)),
            target_return=num('target_return', 0.0, -0.5, 1.0),
            paths=int(num('paths', 4000, 500, 10000)),
        )
    except (KeyError, TypeError, ValueError, np.linalg.LinAlgError):
        return jsonify({'error': 'The stress-test model looks malformed. Reload it and try again.'}), 400
    return jsonify(_sanitize(result))


# ── entry ────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=bool(os.environ.get('DEBUG')), port=port)
