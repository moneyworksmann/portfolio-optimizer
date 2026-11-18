#!/usr/bin/env python3
"""
News and filings for the tickers in your saved portfolio.

    finnhub_news   Finnhub company news (needs FINNHUB_API_KEY, free tier is
                   60 calls/min). The primary feed.
    google_news    Google News RSS search. Keyless; used for a ticker when
                   Finnhub is not configured or fails.
    edgar_filings  SEC EDGAR filings (8-K, 10-Q, 10-K, 13D/G...). Keyless, but
                   the SEC asks every client to send a contact address in the
                   User-Agent: set SEC_USER_AGENT="your-app you@example.com".

Every item comes back in one shape:

    {id, ticker, title, summary, source, url, published (ISO, UTC), kind}

`kind` is 'news' or 'filing'. `id` is stable across runs, so the loop can tell
which items it has already read.
"""

from __future__ import annotations

import hashlib
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

TIMEOUT = 15
FINNHUB_BASE = 'https://finnhub.io/api/v1'
MAX_PER_TICKER = 15
MATERIAL_FORMS = re.compile(r'^(8-K|10-K|10-Q|6-K|20-F|S-1|424B\d|DEF 14A|SC 13[DG])')
_BROWSER_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'


class NewsError(RuntimeError):
    pass


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _id(prefix: str, *parts) -> str:
    raw = '|'.join(str(p) for p in parts)
    return f'{prefix}:{hashlib.sha1(raw.encode()).hexdigest()[:16]}'


def norm_title(title: str) -> str:
    """Lower-case words only, so the same wire story from two outlets matches."""
    return re.sub(r'\W+', ' ', (title or '').lower()).strip()


# ── Finnhub ──────────────────────────────────────────────────────────────────

def finnhub_news(ticker: str, since: datetime, api_key: str) -> list:
    today = datetime.now(timezone.utc).date()
    resp = requests.get(
        f'{FINNHUB_BASE}/company-news',
        params={'symbol': ticker, 'from': since.date().isoformat(), 'to': today.isoformat(), 'token': api_key},
        timeout=TIMEOUT,
    )
    if resp.status_code in (401, 403):
        raise NewsError('Finnhub rejected FINNHUB_API_KEY.')
    resp.raise_for_status()
    items = []
    for a in resp.json()[:MAX_PER_TICKER]:
        title = (a.get('headline') or '').strip()
        if not title:
            continue
        published = datetime.fromtimestamp(int(a.get('datetime') or 0), tz=timezone.utc)
        if published < since:
            continue
        items.append({
            'id': _id('fh', a.get('id') or a.get('url') or title),
            'ticker': ticker,
            'title': title,
            'summary': (a.get('summary') or '').strip()[:600],
            'source': a.get('source') or 'Finnhub',
            'url': a.get('url') or '',
            'published': _iso(published),
            'kind': 'news',
        })
    return items


# ── Google News RSS (fallback) ───────────────────────────────────────────────

_JUNK = re.compile(r'stock price,? news|quote (&|and) history|stock quote|price today|price and chart|live price', re.I)


def google_news(ticker: str, since: datetime) -> list:
    days = max(1, min(7, (datetime.now(timezone.utc) - since).days + 1))
    resp = requests.get(
        'https://news.google.com/rss/search',
        params={'q': f'{ticker} stock when:{days}d', 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'},
        headers={'User-Agent': _BROWSER_UA},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    items = []
    for it in root.iter('item'):
        title = (it.findtext('title') or '').strip()
        source = (it.findtext('source') or '').strip()
        if not title or _JUNK.search(title):
            continue
        if source and title.endswith(f' - {source}'):
            title = title[: -len(source) - 3]
        try:
            published = parsedate_to_datetime(it.findtext('pubDate') or '')
        except (TypeError, ValueError):
            continue
        if published < since:
            continue
        link = (it.findtext('link') or '').strip()
        items.append({
            'id': _id('gn', it.findtext('guid') or link or title),
            'ticker': ticker,
            'title': title,
            'summary': '',
            'source': source or 'Google News',
            'url': link,
            'published': _iso(published),
            'kind': 'news',
        })
        if len(items) >= MAX_PER_TICKER:
            break
    return items


# ── SEC EDGAR ────────────────────────────────────────────────────────────────

_ATOM = '{http://www.w3.org/2005/Atom}'


def edgar_filings(ticker: str, since: datetime, user_agent: str | None = None) -> list:
    ua = user_agent or os.environ.get('SEC_USER_AGENT')
    if not ua:
        return []  # the SEC requires a contact address; skip quietly without one
    resp = requests.get(
        'https://www.sec.gov/cgi-bin/browse-edgar',
        params={'action': 'getcompany', 'CIK': ticker.replace('.', '-'), 'type': '', 'dateb': '',
                'owner': 'exclude', 'count': 40, 'output': 'atom'},
        headers={'User-Agent': ua},
        timeout=TIMEOUT,
    )
    if resp.status_code == 404:
        return []
    resp.raise_for_status()
    root = ET.fromstring(resp.content)
    company = (root.findtext(f'{_ATOM}company-info/{_ATOM}conformed-name') or ticker).strip()
    items = []
    for e in root.iter(f'{_ATOM}entry'):
        c = e.find(f'{_ATOM}content')
        if c is None:
            continue
        form = (c.findtext(f'{_ATOM}filing-type') or '').strip()
        if not MATERIAL_FORMS.match(form):
            continue
        filed = (c.findtext(f'{_ATOM}filing-date') or '').strip()
        try:
            published = datetime.fromisoformat(filed).replace(hour=12, tzinfo=timezone.utc)
        except ValueError:
            continue
        if published < since - timedelta(days=1):
            continue
        name = (c.findtext(f'{_ATOM}form-name') or '').strip()
        accession = (c.findtext(f'{_ATOM}accession-number') or '').strip()
        items.append({
            'id': f'sec:{accession}' if accession else _id('sec', ticker, form, filed),
            'ticker': ticker,
            'title': f'{company} filed {form}' + (f' ({name})' if name else ''),
            'summary': (e.findtext(f'{_ATOM}summary') or '').strip()[:600],
            'source': 'SEC EDGAR',
            'url': (c.findtext(f'{_ATOM}filing-href') or '').strip(),
            'published': _iso(published),
            'kind': 'filing',
        })
        if len(items) >= 5:
            break
    return items


# ── one call per ticker ──────────────────────────────────────────────────────

def collect(ticker: str, since: datetime, *, filings: bool = True) -> tuple[list, list]:
    """(items, errors) for one ticker: Finnhub, else Google News, plus filings."""
    items, errors = [], []
    key = (os.environ.get('FINNHUB_API_KEY') or '').strip()
    got_news = False
    if key:
        try:
            items += finnhub_news(ticker, since, key)
            got_news = True
        except (requests.RequestException, NewsError, ValueError) as e:
            errors.append(f'{ticker}: Finnhub failed ({e.__class__.__name__})')
    if not got_news:
        try:
            items += google_news(ticker, since)
        except (requests.RequestException, ET.ParseError) as e:
            errors.append(f'{ticker}: Google News failed ({e.__class__.__name__})')
    if filings:
        try:
            items += edgar_filings(ticker, since)
        except (requests.RequestException, ET.ParseError) as e:
            errors.append(f'{ticker}: EDGAR failed ({e.__class__.__name__})')
    return items, errors
