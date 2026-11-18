"""Tests for the saved portfolio and the news loop. No network: news, Claude
and prices are all faked."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from core import intel, optimizer, store
from core.market_data import MarketData

NOW = datetime(2026, 11, 18, 17, 0, tzinfo=timezone.utc)
TICKERS = ['AAA', 'BBB', 'CCC', 'DDD']


# ── fakes ────────────────────────────────────────────────────────────────────

def fake_md(last_move=None, seed=0):
    """A real MarketData object built from synthetic closes, skipping the download."""
    rng = np.random.default_rng(seed)
    n = 3 * 252
    mean = np.array([0.0006, 0.0004, 0.0003, 0.0002, 0.0003])
    vol = np.array([0.02, 0.015, 0.012, 0.008, 0.01])
    corr = np.full((5, 5), 0.3) + 0.7 * np.eye(5)
    rets = rng.multivariate_normal(mean, corr * np.outer(vol, vol), size=n)
    rets[-1, :] = 0.0                      # a flat last day unless a test sets one
    for i, t in enumerate(TICKERS):
        if last_move and t in last_move:
            rets[-1, i] = last_move[t]
    prices = 100 * np.cumprod(1 + rets, axis=0)
    idx = pd.bdate_range(end='2026-11-18', periods=n)
    closes = pd.DataFrame(prices, index=idx, columns=TICKERS + ['SPY'])

    md = MarketData.__new__(MarketData)
    md.requested = list(TICKERS)
    md.period = '5y'
    md.valid = list(TICKERS)
    md.dropped = []
    md.closes = closes
    md.benchmark_closes = closes['SPY']
    md.latest = {t: float(closes[t].iloc[-1]) for t in TICKERS}
    md.returns = closes[TICKERS].pct_change().dropna()
    md.sectors = {'AAA': 'Technology', 'BBB': 'Technology', 'CCC': 'Energy', 'DDD': 'Utilities'}
    return md


def item(i, ticker='AAA', title=None, summary='', kind='news', hours_ago=2):
    return {
        'id': f'x:{i}', 'ticker': ticker, 'title': title or f'{ticker} headline {i}', 'summary': summary,
        'source': 'Wire', 'url': f'https://example.com/{i}', 'kind': kind,
        'published': (NOW - timedelta(hours=hours_ago)).isoformat(),
    }


def scored(ticker='AAA', direction=-1.0, magnitude=3, confidence=1.0, event_type='guidance',
           kind='news', days_ago=0.0, i=0):
    return {
        'id': f's:{ticker}:{i}', 'ticker': ticker, 'kind': kind, 'title': 't', 'url': 'u', 'source': 's',
        'published': (NOW - timedelta(days=days_ago)).isoformat(),
        'direction': direction, 'magnitude': magnitude, 'confidence': confidence,
        'event_type': event_type, 'reason': 'r',
    }


class FakeClaude:
    """Mimics client.beta.messages.create with canned scores."""

    def __init__(self, scores_for):
        self.scores_for = scores_for
        self.calls = 0
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        payload = json.loads(kwargs['messages'][0]['content'].split('\n', 1)[1])
        out = [s for it in payload for s in self.scores_for(it)]
        text = json.dumps({'scores': out})
        return SimpleNamespace(stop_reason='end_turn', content=[SimpleNamespace(type='text', text=text)])


@pytest.fixture(autouse=True)
def file_store(tmp_path, monkeypatch):
    monkeypatch.setenv('PI_DATA_DIR', str(tmp_path))
    for var in ('DATABASE_URL', 'POSTGRES_URL', 'VERCEL', 'INTEL_MODE', 'NTFY_TOPIC', 'INTEL_TOKEN'):
        monkeypatch.delenv(var, raising=False)
    return tmp_path


# ── store ────────────────────────────────────────────────────────────────────

def test_file_store_round_trip():
    assert store.backend() == 'file'
    assert store.get('portfolio') is None
    store.put('portfolio', {'holdings': [{'ticker': 'AAA', 'shares': 2}]})
    assert store.get('portfolio')['holdings'][0]['ticker'] == 'AAA'


def test_vercel_without_database_refuses_to_save(monkeypatch):
    monkeypatch.setenv('VERCEL', '1')
    assert store.backend() == 'none'
    with pytest.raises(store.StoreUnavailable):
        store.put('portfolio', {})


# ── scoring guardrails ───────────────────────────────────────────────────────

def test_scores_need_a_quote_that_is_really_in_the_item():
    batch = [{**item(1, title='AAA cuts full-year guidance'), 'tickers': ['AAA']}]
    raw = [
        {'item_id': 'x:1', 'ticker': 'AAA', 'direction': -0.9, 'magnitude': 3, 'confidence': 0.9,
         'event_type': 'guidance', 'reason': 'Guidance cut.', 'quote': 'cuts  full-year GUIDANCE'},
        {'item_id': 'x:1', 'ticker': 'AAA', 'direction': -0.9, 'magnitude': 3, 'confidence': 0.9,
         'event_type': 'guidance', 'reason': 'Invented.', 'quote': 'CEO resigns'},
        {'item_id': 'x:1', 'ticker': 'ZZZ', 'direction': 1, 'magnitude': 1, 'confidence': 1,
         'event_type': 'other', 'reason': 'Wrong ticker.', 'quote': 'AAA'},
    ]
    out = intel.validate_scores(raw, batch)
    assert len(out) == 1 and out[0]['reason'] == 'Guidance cut.'


def test_out_of_range_values_are_clipped():
    batch = [{**item(1, title='Big news'), 'tickers': ['AAA']}]
    raw = [{'item_id': 'x:1', 'ticker': 'AAA', 'direction': -7, 'magnitude': 9, 'confidence': 2,
            'event_type': 'nonsense', 'reason': 'r', 'quote': 'big news'}]
    (s,) = intel.validate_scores(raw, batch)
    assert (s['direction'], s['magnitude'], s['confidence'], s['event_type']) == (-1, 3, 1, 'other')


def test_duplicate_headlines_merge_across_tickers():
    def collector(t, since, filings=True):
        return [item(t, ticker=t, title='Chipmakers slide on export rules')], []

    fresh, errors = intel.collect_new(['AAA', 'BBB'], {'AAA', 'BBB'}, NOW - timedelta(days=1), {}, collector)
    assert len(fresh) == 1 and fresh[0]['tickers'] == ['AAA', 'BBB'] and not errors


# ── decay, weights, price confirmation ───────────────────────────────────────

def test_half_life_halves_the_contribution():
    fresh = intel.item_contribution(scored(days_ago=0), NOW)
    old = intel.item_contribution(scored(days_ago=intel.HALF_LIFE_DAYS['news']), NOW)
    assert old == pytest.approx(fresh / 2)


def test_opinion_pieces_barely_count():
    a = intel.item_contribution(scored(event_type='guidance'), NOW)
    b = intel.item_contribution(scored(event_type='opinion'), NOW)
    assert b == pytest.approx(a * 0.1)


def test_levels_and_price_confirmation():
    items = [scored('AAA', -1, 3, 1, i=0), scored('AAA', -1, 2, 1, i=1)]   # raw -5
    sig = intel.ticker_signals(items, ['AAA', 'BBB'], NOW, fake_md())['AAA']
    assert sig['level'] == 'candidate' and sig['score'] <= -4

    down = intel.ticker_signals(items, ['AAA'], NOW, fake_md(last_move={'AAA': -0.08}))['AAA']
    assert down['price_factor'] == 1.25 and down['score'] == pytest.approx(sig['raw'] * 1.25, abs=0.01)

    up = intel.ticker_signals(items, ['AAA'], NOW, fake_md(last_move={'AAA': 0.08}))['AAA']
    assert up['price_factor'] == 0.75 and up['level'] == 'disagree'

    watch = intel.ticker_signals([scored('BBB', 1, 3, 1)], ['BBB'], NOW, None)['BBB']
    assert watch['level'] == 'watch'


# ── tilted rebalance ─────────────────────────────────────────────────────────

def test_tilted_rebalance_moves_only_candidates_within_the_cap():
    md = fake_md()
    w = {'AAA': 0.4, 'BBB': 0.3, 'CCC': 0.2, 'DDD': 0.1}
    new = optimizer.tilted_rebalance(md.mean_returns(252), md.covariance(252), w, {'AAA': -0.05}, 0.05)
    assert sum(new.values()) == pytest.approx(1.0)
    assert new['AAA'] <= w['AAA'] + 1e-9 and new['AAA'] >= w['AAA'] - 0.05 - 1e-9
    others = {t: new[t] / w[t] for t in ('BBB', 'CCC', 'DDD')}
    assert max(others.values()) == pytest.approx(min(others.values()))   # pro rata


def test_no_tilts_means_no_change():
    md = fake_md()
    w = {'AAA': 0.5, 'BBB': 0.5}
    assert optimizer.tilted_rebalance(md.mean_returns(252), md.covariance(252), w, {}) == pytest.approx(w)


# ── suggestions ──────────────────────────────────────────────────────────────

HOLDINGS = [{'ticker': 'AAA', 'shares': 40}, {'ticker': 'BBB', 'shares': 30},
            {'ticker': 'CCC', 'shares': 20}, {'ticker': 'DDD', 'shares': 10}]


def strong_negative(md, ticker='AAA'):
    items = [scored(ticker, -1, 3, 1, i=i) for i in range(4)]   # raw -12
    return intel.ticker_signals(items, TICKERS, NOW, md)


def test_strong_bad_news_trims_the_holding():
    md = fake_md()
    sug = intel.build_suggestion(md, HOLDINGS, strong_negative(md), intel.empty_state(), NOW)
    assert sug and sug['drivers'] == ['AAA'] and sug['mode'] == 'shadow'
    lead = sug['trades'][0]
    assert lead['ticker'] == 'AAA' and lead['action'] == 'Trim'
    assert -intel.MAX_MOVE * 100 - 1e-6 <= lead['change_pct'] <= -intel.MIN_TRADE * 100
    assert sum(t['change_pct'] for t in sug['trades']) == pytest.approx(0, abs=0.05)
    assert sug['outcomes_1y_pct'] and set(sug['outcomes_1y_pct']) == {'current', 'suggested'}


def test_cooldown_blocks_a_repeat():
    md = fake_md()
    state = intel.empty_state()
    state['last_suggested'] = {'AAA': {'at': (NOW - timedelta(days=1)).isoformat(), 'sign': -1}}
    assert intel.build_suggestion(md, HOLDINGS, strong_negative(md), state, NOW) is None
    state['last_suggested']['AAA']['sign'] = 1     # the news flipped: allowed again
    assert intel.build_suggestion(md, HOLDINGS, strong_negative(md), state, NOW) is not None


def test_daily_cap():
    md = fake_md()
    state = intel.empty_state()
    state['suggestions'] = [{'created': NOW.isoformat()}] * intel.MAX_SUGGESTIONS_PER_DAY
    assert intel.build_suggestion(md, HOLDINGS, strong_negative(md), state, NOW) is None


def test_watch_level_never_suggests():
    md = fake_md()
    sig = intel.ticker_signals([scored('AAA', -1, 3, 1)], TICKERS, NOW, md)
    assert intel.build_suggestion(md, HOLDINGS, sig, intel.empty_state(), NOW) is None


# ── a whole run ──────────────────────────────────────────────────────────────

def test_run_end_to_end_only_touches_saved_tickers():
    store.put('portfolio', {'saved_at': NOW.isoformat(), 'holdings': HOLDINGS, 'candidates': ['EEE']})
    asked = []

    def collector(t, since, filings=True):
        asked.append((t, filings))
        if t == 'AAA':
            return [item(i, 'AAA', title=f'AAA slashes outlook, part {i}', hours_ago=1) for i in range(4)], []
        return [], []

    def scores_for(it):
        return [{'item_id': it['item_id'], 'ticker': 'AAA', 'direction': -1, 'magnitude': 3, 'confidence': 1,
                 'event_type': 'guidance', 'reason': 'Outlook cut.', 'quote': 'slashes outlook'}]

    claude = FakeClaude(scores_for)
    summary = intel.run(now=NOW, collector=collector, client=claude, market_data=fake_md())
    assert summary['ok'] and summary['scored'] == 4 and summary['candidates'] == ['AAA']
    assert summary['suggestion'] and claude.calls == 1
    assert sorted(t for t, _ in asked) == ['AAA', 'BBB', 'CCC', 'DDD', 'EEE']
    assert dict(asked)['EEE'] is False      # no filings for watchlist-only tickers

    view = intel.view()
    assert view['signals']['AAA']['level'] == 'candidate' and view['signals']['EEE']['watchlist']
    assert view['suggestions'][0]['trades'][0]['source']['url'].startswith('https://example.com/')

    # Second run: nothing new is re-scored, and the cooldown holds.
    again = intel.run(now=NOW + timedelta(minutes=30), collector=collector, client=claude, market_data=fake_md())
    assert again['scored'] == 0 and not again['suggestion'] and claude.calls == 1


def test_run_without_saved_portfolio():
    assert intel.run(now=NOW, collector=lambda *a, **k: ([], []))['ok'] is False


def test_failed_scoring_leaves_items_for_next_run():
    store.put('portfolio', {'saved_at': NOW.isoformat(), 'holdings': HOLDINGS})

    class Broken:
        beta = SimpleNamespace(messages=SimpleNamespace(create=lambda **k: (_ for _ in ()).throw(RuntimeError())))

    collector = lambda t, since, filings=True: ([item(1, 'AAA', title='AAA news')] if t == 'AAA' else [], [])
    s = intel.run(now=NOW, collector=collector, client=Broken(), market_data=fake_md())
    assert s['ok'] and s['scored'] == 0 and s['errors']
    assert 'x:1' not in store.get('intel_state')['seen']


# ── routes ───────────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    from app import app
    app.config['TESTING'] = True
    return app.test_client()


def test_portfolio_routes_need_the_owner_key(client, monkeypatch):
    monkeypatch.setenv('INTEL_TOKEN', 't' * 32)
    body = {'holdings': [{'ticker': 'aaa', 'shares': 3}], 'candidates': ['bbb', 'AAA']}
    assert client.post('/api/portfolio', json=body).status_code == 401
    assert client.get('/api/intel').status_code == 401
    ok = client.post('/api/portfolio', json=body, headers={'Authorization': 'Bearer ' + 't' * 32})
    assert ok.status_code == 200 and ok.get_json()['candidates'] == ['BBB']
    got = client.get('/api/portfolio', headers={'Authorization': 'Bearer ' + 't' * 32}).get_json()
    assert got['holdings'][0]['ticker'] == 'AAA'


def test_local_requests_work_without_a_token(client):
    r = client.post('/api/portfolio', json={'holdings': [{'ticker': 'AAA', 'shares': 1}]})
    assert r.status_code == 200
    assert client.get('/api/intel').get_json()['config']['mode'] == 'shadow'


def test_on_vercel_without_a_token_nobody_gets_in(client, monkeypatch):
    monkeypatch.setenv('VERCEL', '1')
    assert client.get('/api/intel').status_code == 401


def test_news_outage_keeps_the_lookback_and_skips_suggestions():
    store.put('portfolio', {'saved_at': NOW.isoformat(), 'holdings': HOLDINGS})
    ok = lambda t, since, filings=True: ([], [])
    intel.run(now=NOW, collector=ok, client=FakeClaude(lambda it: []), market_data=fake_md())
    first = store.get('intel_state')['last_collected']

    down = lambda t, since, filings=True: ([], [f'{t}: Google News failed (ProxyError)'])
    s = intel.run(now=NOW + timedelta(hours=1), collector=down, client=FakeClaude(lambda it: []), market_data=fake_md())
    assert not s['suggestion'] and any('Every news source failed' in e for e in s['errors'])
    assert store.get('intel_state')['last_collected'] == first
