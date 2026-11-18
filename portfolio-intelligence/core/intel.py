#!/usr/bin/env python3
"""
Portfolio intelligence: the news-driven suggestion loop.

Runs on a schedule (POST /api/intel/run, called by .github/workflows/intel.yml
every 30 minutes in market hours) against the one portfolio you saved with
"Watch this portfolio". It only ever looks at those tickers.

Each run:

    1. Collect   news and filings since the last run for every saved ticker,
                 dropping anything already read (by id) or already seen under
                 another outlet's name (same normalised headline).
    2. Score     Claude reads only the new items and returns, per item and
                 ticker: direction (-1..+1), magnitude (1 minor, 2 notable,
                 3 thesis-changing), confidence (0..1), event type, a one-line
                 reason and a quote from the item. An item whose quote is not
                 actually in its text is dropped.
    3. Decay     each item fades with a half-life (about 3 trading days for
                 news, 5 for filings) and is weighted by event type, so the
                 per-ticker score reflects the last week or two, not one
                 headline:

                     S = c * sum(direction * magnitude * confidence * w_type * 2^(-age/h))

    4. Confirm   c = 1.25 when today's price move agrees with the score and is
                 larger than one daily standard deviation, 0.75 when it
                 contradicts it, 1 otherwise.
    5. Suggest   holdings scoring |S| >= 4 (and not contradicted by price)
                 become candidates. Their expected returns are tilted by up to
                 5 points, the optimizer re-solves with each candidate moving at
                 most 5 points, and only trades of 2%+ of the portfolio that are
                 not in a 3-day cooldown and do not cost more than 5 PRISM
                 points survive. Monte Carlo ranges before/after are attached.

INTEL_MODE=shadow (the default) computes and shows everything but labels the
suggestions "shadow" and never pushes them. Nothing here places trades.
"""

from __future__ import annotations

import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import numpy as np

from . import montecarlo, news, optimizer, prism, store

# ── tunables (see the design doc; recalibrate after a month of stored scores) ─

EVENT_TYPES = (
    'guidance', 'earnings', 'mna', 'regulatory_legal', 'filing',
    'analyst', 'management', 'product', 'macro', 'opinion', 'other',
)
EVENT_WEIGHTS = {
    'guidance': 1.0, 'earnings': 1.0, 'mna': 1.0, 'regulatory_legal': 1.0, 'filing': 1.0,
    'analyst': 0.6, 'management': 0.6,
    'product': 0.4, 'macro': 0.4,
    'other': 0.2, 'opinion': 0.1,
}
HALF_LIFE_DAYS = {'news': 4.0, 'filing': 7.0}   # calendar days ~ 3 and 5 trading days
WATCH_AT = 2.0
CANDIDATE_AT = 4.0
TILT_MAX = 0.05            # max shift in annual expected return
TILT_FULL_AT = 8.0         # score at which the tilt reaches TILT_MAX
MAX_MOVE = 0.05            # max weight change per candidate per suggestion
MIN_TRADE = 0.02           # smallest trade worth surfacing (fraction of portfolio)
COOLDOWN_DAYS = 4          # ~3 trading days
MAX_SUGGESTIONS_PER_DAY = 3
PRISM_MAX_DROP = 5.0
KEEP_DAYS = 21             # scored items older than this no longer matter (2^-5)
SEEN_DAYS = 30
FIRST_RUN_LOOKBACK_DAYS = 3
MAX_NEW_PER_RUN = 60       # bounds cost and run time; the rest wait for the next run
BATCH_SIZE = 20

DEFAULT_MODEL = 'claude-opus-5-5'


def mode() -> str:
    return 'live' if os.environ.get('INTEL_MODE', 'shadow').strip().lower() == 'live' else 'shadow'


def config_status() -> dict:
    """Which pieces are configured, as booleans only (never the values)."""
    return {
        'mode': mode(),
        'store': store.backend(),
        'finnhub': bool(os.environ.get('FINNHUB_API_KEY')),
        'claude': bool(os.environ.get('ANTHROPIC_API_KEY')),
        'sec_user_agent': bool(os.environ.get('SEC_USER_AGENT')),
        'push': bool(os.environ.get('NTFY_TOPIC')),
        'run_token': bool(os.environ.get('INTEL_TOKEN')),
    }


# ── helpers ──────────────────────────────────────────────────────────────────

def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _squash(s: str) -> str:
    return re.sub(r'\s+', ' ', (s or '').lower()).strip()


def _clip(x, lo, hi, default=0.0):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return default
    return default if not math.isfinite(x) else min(hi, max(lo, x))


def portfolio_tickers(portfolio: dict) -> tuple[list, list]:
    """(held tickers, watchlist-only tickers) from a saved portfolio."""
    held = []
    for lot in portfolio.get('holdings', []):
        t = str(lot.get('ticker', '')).upper().strip()
        if t and float(lot.get('shares') or 0) > 0 and t not in held:
            held.append(t)
    watch = [t for t in (str(c).upper().strip() for c in portfolio.get('candidates', [])) if t and t not in held]
    return held, list(dict.fromkeys(watch))


# ── 1. collect ───────────────────────────────────────────────────────────────

def collect_new(tickers: list, held: set, since: datetime, seen: dict, collector=news.collect) -> tuple[list, list]:
    """New items for these tickers, deduplicated by id and by headline."""
    def one(t):
        return collector(t, since, filings=t in held)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(one, tickers))

    errors, by_title = [], {}
    for items, errs in results:
        errors += errs
        for it in items:
            if it['id'] in seen:
                continue
            key = news.norm_title(it['title'])
            if key in by_title:
                prev = by_title[key]
                prev['tickers'] = sorted(set(prev['tickers']) | {it['ticker']})
                continue
            by_title[key] = {**it, 'tickers': [it['ticker']]}
    fresh = sorted(by_title.values(), key=lambda x: x['published'], reverse=True)
    return fresh, errors


# ── 2. score with Claude ─────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You score news items for a personal stock portfolio. For each item, judge what it
means for the stock(s) it is about, using only the item's own title and summary.

For every (item, ticker) pair that carries real information about that ticker, return:
- direction: -1 (clearly bad for the stock) to +1 (clearly good); 0 if mixed
- magnitude: 1 minor, 2 notable, 3 thesis-changing (guidance cut, big M&A, major lawsuit or approval)
- confidence: 0 to 1, how sure you are of the direction given only this text
- event_type: one of guidance, earnings, mna, regulatory_legal, filing, analyst,
  management, product, macro, opinion, other. Use "filing" for an SEC filing whose
  content is not described; use "opinion" for commentary, listicles and price recaps.
- reason: one plain sentence a retail investor can read
- quote: a short exact phrase copied from the item's title or summary that supports it

Skip items with no real information about the ticker (do not return them).
Never use outside knowledge or invent facts; if the text is too thin to judge,
use low confidence. This is analysis, not investment advice."""

SCORE_SCHEMA = {
    'type': 'object',
    'properties': {
        'scores': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'item_id': {'type': 'string'},
                    'ticker': {'type': 'string'},
                    'direction': {'type': 'number'},
                    'magnitude': {'type': 'integer'},
                    'confidence': {'type': 'number'},
                    'event_type': {'type': 'string', 'enum': list(EVENT_TYPES)},
                    'reason': {'type': 'string'},
                    'quote': {'type': 'string'},
                },
                'required': ['item_id', 'ticker', 'direction', 'magnitude', 'confidence',
                             'event_type', 'reason', 'quote'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['scores'],
    'additionalProperties': False,
}


def _client():
    import anthropic  # lazy: the rest of the app runs without it

    return anthropic.Anthropic()


def _call_claude(client, batch: list) -> list:
    payload = [{
        'item_id': it['id'], 'tickers': it['tickers'], 'kind': it['kind'], 'source': it['source'],
        'published': it['published'], 'title': it['title'], 'summary': it['summary'],
    } for it in batch]
    response = client.beta.messages.create(
        model=os.environ.get('INTEL_MODEL') or DEFAULT_MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{'role': 'user', 'content': 'Score these items:\n' + json.dumps(payload, ensure_ascii=False)}],
        output_config={'effort': 'low', 'format': {'type': 'json_schema', 'schema': SCORE_SCHEMA}},
        # If a request is declined, the API retries it on a fallback model.
        betas=['server-side-fallback-2026-07-01'],
        fallbacks='default',
    )
    if response.stop_reason == 'refusal':
        return []
    text = next((b.text for b in response.content if b.type == 'text'), '')
    return json.loads(text).get('scores', []) if text else []


def validate_scores(raw: list, batch: list) -> list:
    """Keep only well-formed scores whose quote is really in the item."""
    items = {it['id']: it for it in batch}
    out = []
    for s in raw:
        it = items.get(s.get('item_id'))
        ticker = str(s.get('ticker', '')).upper().strip()
        if not it or ticker not in it['tickers']:
            continue
        quote = _squash(s.get('quote', ''))
        if not quote or quote not in _squash(f"{it['title']} {it['summary']}"):
            continue  # the reason must be grounded in the text we sent
        etype = s.get('event_type') if s.get('event_type') in EVENT_WEIGHTS else 'other'
        out.append({
            'id': it['id'], 'ticker': ticker, 'kind': it['kind'],
            'title': it['title'], 'url': it['url'], 'source': it['source'], 'published': it['published'],
            'direction': round(_clip(s.get('direction'), -1, 1), 3),
            'magnitude': int(_clip(s.get('magnitude'), 1, 3, 1)),
            'confidence': round(_clip(s.get('confidence'), 0, 1), 3),
            'event_type': etype,
            'reason': str(s.get('reason', ''))[:300],
        })
    return out


def score_items(items: list, client=None) -> tuple[list, list, set]:
    """(scored, errors, ids that were scored). Batches run in parallel; a failed
    batch stays unread and is retried on the next run."""
    if not items:
        return [], [], set()
    client = client or _client()
    batches = [items[i:i + BATCH_SIZE] for i in range(0, len(items), BATCH_SIZE)]
    scored, errors, done_ids = [], [], set()

    def one(batch):
        try:
            return batch, _call_claude(client, batch), None
        except Exception as e:  # network, rate limit, bad JSON: leave unseen, retry later
            return batch, [], f'Scoring failed for {len(batch)} items ({e.__class__.__name__})'

    with ThreadPoolExecutor(max_workers=3) as pool:
        for batch, raw, err in pool.map(one, batches):
            if err:
                errors.append(err)
                continue
            scored += validate_scores(raw, batch)
            done_ids.update(it['id'] for it in batch)
    return scored, errors, done_ids


# ── 3–4. decay and confirm ───────────────────────────────────────────────────

def item_contribution(s: dict, now: datetime) -> float:
    age_days = max(0.0, (now - _parse(s['published'])).total_seconds() / 86400)
    h = HALF_LIFE_DAYS.get(s.get('kind'), HALF_LIFE_DAYS['news'])
    w = EVENT_WEIGHTS.get(s.get('event_type'), EVENT_WEIGHTS['other'])
    return s['direction'] * s['magnitude'] * s['confidence'] * w * 2 ** (-age_days / h)


def price_check(md, ticker: str):
    """(today's move, one daily standard deviation), both as fractions, or (None, None)."""
    try:
        closes = md.closes[ticker].dropna()
        rets = closes.pct_change().dropna().tail(252)
        if len(closes) < 3 or rets.empty:
            return None, None
        return float(closes.iloc[-1] / closes.iloc[-2] - 1), float(rets.std())
    except (KeyError, AttributeError, IndexError):
        return None, None


def ticker_signals(scored: list, tickers: list, now: datetime, md=None) -> dict:
    signals = {}
    for t in tickers:
        mine = [s for s in scored if s['ticker'] == t]
        contribs = [(item_contribution(s, now), s) for s in mine]
        raw = sum(c for c, _ in contribs)
        move, sd = price_check(md, t) if md is not None else (None, None)
        factor, disagree = 1.0, False
        if move is not None and sd and abs(move) > sd and abs(raw) > 0:
            if np.sign(move) == np.sign(raw):
                factor = 1.25
            else:
                factor, disagree = 0.75, True
        score = raw * factor
        if disagree and abs(raw) >= CANDIDATE_AT:
            level = 'disagree'      # strong news, but the market is moving the other way
        elif abs(score) < WATCH_AT:
            level = 'none'
        elif abs(score) < CANDIDATE_AT:
            level = 'watch'
        else:
            level = 'candidate'
        top = sorted(contribs, key=lambda x: -abs(x[0]))[:3]
        signals[t] = {
            'score': round(score, 2), 'raw': round(raw, 2), 'price_factor': factor,
            'day_move_pct': round(move * 100, 2) if move is not None else None,
            'daily_sd_pct': round(sd * 100, 2) if sd else None,
            'level': level, 'items': len(mine),
            'top': [{**s, 'contribution': round(c, 3)} for c, s in top],
        }
    return signals


# ── 5. suggest ───────────────────────────────────────────────────────────────

def tilt_for(score: float) -> float:
    return float(np.sign(score)) * TILT_MAX * min(abs(score), TILT_FULL_AT) / TILT_FULL_AT


def _prism_score(md, weights: dict):
    tickers = [t for t in md.valid if weights.get(t, 0) > 0]
    if len(tickers) < 2:
        return None
    total = sum(weights[t] for t in tickers)
    norm = {t: weights[t] / total for t in tickers}
    corr = md.correlation().reindex(index=tickers, columns=tickers)
    parts = (
        prism.score_diversification(md.sector_weights(norm)),
        prism.score_correlation(corr),
        prism.score_volatility(md.portfolio_returns(norm)),
        prism.score_exposure(norm),
    )
    return round(sum(parts) / 4, 1)


def _in_cooldown(state: dict, ticker: str, sign: int, now: datetime) -> bool:
    last = (state.get('last_suggested') or {}).get(ticker)
    if not last:
        return False
    return last.get('sign') == sign and now - _parse(last['at']) < timedelta(days=COOLDOWN_DAYS)


def build_suggestion(md, holdings: list, signals: dict, state: dict, now: datetime) -> dict | None:
    """The trades the news justifies, or None. `holdings` = saved lots."""
    shares = {}
    for lot in holdings:
        t = str(lot.get('ticker', '')).upper()
        shares[t] = shares.get(t, 0.0) + float(lot.get('shares') or 0)
    values = {t: n * md.latest[t] for t, n in shares.items() if t in md.latest and n > 0}
    total_value = sum(values.values())
    if total_value <= 0 or len(values) < 2:
        return None
    weights = {t: v / total_value for t, v in values.items()}

    today = now.date().isoformat()
    made_today = sum(1 for s in state.get('suggestions', []) if s.get('created', '')[:10] == today)
    if made_today >= MAX_SUGGESTIONS_PER_DAY:
        return None

    tilts = {}
    for t, sig in signals.items():
        if t in weights and sig['level'] == 'candidate':
            sign = int(np.sign(sig['score']))
            if not _in_cooldown(state, t, sign, now):
                tilts[t] = tilt_for(sig['score'])
    if not tilts:
        return None

    mean = md.mean_returns(optimizer.TRADING_DAYS)
    cov = md.covariance(optimizer.TRADING_DAYS)
    new_w = optimizer.tilted_rebalance(mean, cov, weights, tilts, MAX_MOVE)

    moved = [t for t in tilts if abs(new_w.get(t, 0) - weights[t]) >= MIN_TRADE]
    if not moved:
        return None
    # Only surviving candidates move; everyone else is rescaled to fund them.
    final = dict(weights)
    for t in moved:
        final[t] = new_w[t]
    rest = [t for t in weights if t not in moved]
    rest_total = sum(weights[t] for t in rest)
    room = 1.0 - sum(final[t] for t in moved)
    for t in rest:
        final[t] = room * weights[t] / rest_total if rest_total > 0 else 0.0

    prism_before, prism_after = _prism_score(md, weights), _prism_score(md, final)
    if prism_before is not None and prism_after is not None and prism_before - prism_after > PRISM_MAX_DROP:
        return None

    tickers = list(weights)
    w0 = np.array([weights[t] for t in tickers])
    w1 = np.array([final[t] for t in tickers])
    mu = mean.reindex(tickers).fillna(0.0)
    cv = cov.reindex(index=tickers, columns=tickers).fillna(0.0)
    r0, v0, s0 = optimizer.stats(w0, mu, cv)
    r1, v1, s1 = optimizer.stats(w1, mu, cv)

    trades = []
    for t in tickers:
        delta = final[t] - weights[t]
        if abs(delta) < 0.001:
            continue
        price = md.latest.get(t)
        sig = signals.get(t, {})
        driver = t in moved
        top = (sig.get('top') or [{}])[0] if driver else {}
        trades.append({
            'ticker': t,
            'action': ('Add' if delta > 0 else 'Trim') if driver else 'Rebalance',
            'driver': driver,
            'current_pct': round(weights[t] * 100, 2),
            'target_pct': round(final[t] * 100, 2),
            'change_pct': round(delta * 100, 2),
            'dollars': round(delta * total_value, 2),
            'shares': round(delta * total_value / price, 3) if price else None,
            'score': sig.get('score'),
            'reason': top.get('reason') if driver else 'Scaled to fund the news-driven trades.',
            'source': {'title': top.get('title'), 'url': top.get('url'), 'source': top.get('source')} if driver else None,
        })
    trades.sort(key=lambda x: (not x['driver'], -abs(x['change_pct'])))

    outcomes = None
    try:
        mc = montecarlo.analyse(md, weights, total_value, compare={'suggested': final}, n_paths=2000, seed=7)
        if mc.get('available'):
            outcomes = {
                name: {k: res['percentiles_pct'][k] for k in ('p5', 'p50', 'p95')} | {'prob_loss': res['prob_loss']}
                for name, res in mc['results'].items()
            }
    except Exception:  # the suggestion stands without the probability ranges
        outcomes = None

    return {
        'created': store.now_iso(),
        'mode': mode(),
        'drivers': moved,
        'trades': trades,
        'total_value': round(total_value, 2),
        'sharpe_before': round(s0, 3), 'sharpe_after': round(s1, 3),
        'return_before_pct': round(r0 * 100, 2), 'return_after_pct': round(r1 * 100, 2),
        'risk_before_pct': round(v0 * 100, 2), 'risk_after_pct': round(v1 * 100, 2),
        'prism_before': prism_before, 'prism_after': prism_after,
        'outcomes_1y_pct': outcomes,
        'note': 'Expected returns and Sharpe use one year of history, without the news tilt.',
    }


# ── push (live mode only) ────────────────────────────────────────────────────

def push(suggestion: dict) -> bool:
    topic = os.environ.get('NTFY_TOPIC')
    if not topic or suggestion.get('mode') != 'live':
        return False
    import requests

    lines = [f"{t['action']} {t['ticker']} {t['current_pct']:.0f}% to {t['target_pct']:.0f}%. {t['reason'] or ''}"
             for t in suggestion['trades'] if t['driver']]
    body = '\n'.join(lines) + f"\nSharpe {suggestion['sharpe_before']:.2f} to {suggestion['sharpe_after']:.2f}."
    try:
        r = requests.post(f'https://ntfy.sh/{topic}', data=body.encode(),
                          headers={'Title': 'Portfolio Intelligence suggestion', 'Priority': '4'}, timeout=8)
        return r.ok
    except requests.RequestException:
        return False


# ── the run ──────────────────────────────────────────────────────────────────

def empty_state() -> dict:
    return {'version': 1, 'seen': {}, 'items': [], 'signals': {}, 'suggestions': [],
            'last_suggested': {}, 'runs': [], 'last_run': None}


def run(*, now: datetime | None = None, collector=news.collect, client=None, market_data=None) -> dict:
    """One pass of the loop. Returns the run summary (also stored in state)."""
    now = now or datetime.now(timezone.utc)
    portfolio = store.get('portfolio')
    if not portfolio or not portfolio.get('holdings'):
        return {'ok': False, 'error': 'No saved portfolio. Use "Watch this portfolio" first.'}

    held, watch = portfolio_tickers(portfolio)
    tickers = held + watch
    state = store.get('intel_state') or empty_state()
    seen = state.get('seen', {})
    # Look back from the last run that actually reached a news source, with some
    # overlap; already-read items are skipped by id, so the overlap costs nothing.
    last_ok = state.get('last_collected')
    since = _parse(last_ok) - timedelta(hours=6) if last_ok else now - timedelta(days=FIRST_RUN_LOOKBACK_DAYS)
    since = max(since, now - timedelta(days=KEEP_DAYS))

    errors = []
    fresh, errs = collect_new(tickers, set(held), since, seen, collector)
    errors += errs
    news_down = len([e for e in errs if 'Finnhub' in e or 'Google News' in e]) >= len(tickers)
    batch = fresh[:MAX_NEW_PER_RUN]

    scored = []
    if batch and (client is not None or os.environ.get('ANTHROPIC_API_KEY')):
        new_scores, errs, done_ids = score_items(batch, client)
        scored += new_scores
        errors += errs
        for it in batch:
            if it['id'] in done_ids:
                seen[it['id']] = it['published']
    elif batch:
        errors.append('ANTHROPIC_API_KEY is not set, so new items were collected but not scored.')

    cutoff = now - timedelta(days=KEEP_DAYS)
    items = [s for s in state.get('items', []) + scored if _parse(s['published']) >= cutoff and s['ticker'] in tickers]
    seen_cutoff = now - timedelta(days=SEEN_DAYS)
    seen = {k: v for k, v in seen.items() if _parse(v) >= seen_cutoff}

    md = market_data
    if md is None:
        try:
            from .market_data import MarketData

            md = MarketData(tickers, period='5y')
        except Exception as e:
            errors.append(f'Price download failed ({e.__class__.__name__})')
    signals = ticker_signals(items, tickers, now, md)
    for t in watch:
        signals[t]['watchlist'] = True

    suggestion = None
    if news_down:
        errors.append('Every news source failed this run, so no suggestion was made.')
    elif md is not None and getattr(md, 'valid', None):
        try:
            suggestion = build_suggestion(md, portfolio['holdings'], {t: signals[t] for t in held}, state, now)
        except Exception as e:
            errors.append(f'Suggestion step failed ({e.__class__.__name__})')

    if suggestion:
        state.setdefault('suggestions', []).insert(0, suggestion)
        state['suggestions'] = state['suggestions'][:30]
        for t in suggestion['drivers']:
            state.setdefault('last_suggested', {})[t] = {'at': now.isoformat(), 'sign': int(np.sign(signals[t]['score']))}
        suggestion['pushed'] = push(suggestion)

    summary = {
        'ok': True, 'at': now.replace(microsecond=0).isoformat(), 'mode': mode(),
        'tickers': len(tickers), 'new_items': len(fresh), 'scored': len(scored),
        'deferred': max(0, len(fresh) - len(batch)),
        'candidates': [t for t in held if signals[t]['level'] == 'candidate'],
        'suggestion': bool(suggestion), 'errors': errors[:20],
    }
    state.update({
        'seen': seen, 'items': items, 'signals': signals,
        'last_run': summary['at'],
        'last_collected': state.get('last_collected') if news_down else summary['at'],
        'runs': ([summary] + state.get('runs', []))[:20],
        'portfolio_saved_at': portfolio.get('saved_at'),
    })
    store.put('intel_state', state)
    return summary


def view() -> dict:
    """What the dashboard shows: signals, recent items, suggestions, config."""
    state = store.get('intel_state') or empty_state()
    portfolio = store.get('portfolio')
    recent = sorted(state.get('items', []), key=lambda s: s['published'], reverse=True)[:40]
    return {
        'config': config_status(),
        'portfolio': {
            'saved_at': portfolio.get('saved_at'),
            'tickers': sum(portfolio_tickers(portfolio), []),
        } if portfolio else None,
        'last_run': state.get('last_run'),
        'runs': state.get('runs', [])[:5],
        'signals': state.get('signals', {}),
        'items': recent,
        'suggestions': state.get('suggestions', [])[:10],
        'thresholds': {'watch': WATCH_AT, 'candidate': CANDIDATE_AT, 'max_move_pct': MAX_MOVE * 100,
                       'min_trade_pct': MIN_TRADE * 100, 'tilt_max_pct': TILT_MAX * 100},
    }
