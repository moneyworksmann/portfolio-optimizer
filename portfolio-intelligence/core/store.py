#!/usr/bin/env python3
"""
Small key-value store for the one thing Portfolio Intelligence has to remember:
your saved ("watched") portfolio, and the news loop's state.

Everything else in the app is computed fresh on each request. The news loop
runs on a schedule while nobody has the page open, so it needs the portfolio
and what it has already read to live somewhere other than the browser.

Backends, picked automatically:

    Postgres    when DATABASE_URL or POSTGRES_URL is set (Vercel -> Storage ->
                Neon sets these for you). One table, `pi_kv`, created on first use.
    JSON files  otherwise, under PI_DATA_DIR (default: .data/ next to app.py).
                Fine on your Mac with ./run.sh. On Vercel the disk is read-only
                and wiped between requests, so there a database is required and
                saving without one fails with a clear message.

Values are JSON-serialisable dicts. Keys used today: 'portfolio', 'intel_state'.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()
_TABLE_READY = False


class StoreUnavailable(RuntimeError):
    """No usable place to save data (e.g. on Vercel without a database)."""


def _db_url() -> str | None:
    return os.environ.get('DATABASE_URL') or os.environ.get('POSTGRES_URL') or None


def _data_dir() -> Path:
    return Path(os.environ.get('PI_DATA_DIR') or Path(__file__).resolve().parent.parent / '.data')


def backend() -> str:
    if _db_url():
        return 'postgres'
    if os.environ.get('VERCEL'):
        return 'none'
    return 'file'


# ── Postgres ─────────────────────────────────────────────────────────────────

def _connect():
    import psycopg  # imported lazily so local file-mode runs don't need it

    return psycopg.connect(_db_url(), autocommit=True, connect_timeout=10)


def _ensure_table(conn) -> None:
    global _TABLE_READY
    if _TABLE_READY:
        return
    conn.execute(
        'CREATE TABLE IF NOT EXISTS pi_kv ('
        ' key TEXT PRIMARY KEY,'
        ' value JSONB NOT NULL,'
        ' updated_at TIMESTAMPTZ NOT NULL DEFAULT now())'
    )
    _TABLE_READY = True


def _pg_get(key: str):
    with _connect() as conn:
        _ensure_table(conn)
        row = conn.execute('SELECT value FROM pi_kv WHERE key = %s', (key,)).fetchone()
    if not row:
        return None
    value = row[0]
    return json.loads(value) if isinstance(value, str) else value


def _pg_put(key: str, value: dict) -> None:
    from psycopg.types.json import Jsonb

    with _connect() as conn:
        _ensure_table(conn)
        conn.execute(
            'INSERT INTO pi_kv (key, value, updated_at) VALUES (%s, %s, now()) '
            'ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()',
            (key, Jsonb(value)),
        )


# ── JSON files ───────────────────────────────────────────────────────────────

def _path(key: str) -> Path:
    safe = ''.join(c for c in key if c.isalnum() or c in '_-')
    return _data_dir() / f'{safe}.json'


def _file_get(key: str):
    p = _path(key)
    if not p.exists():
        return None
    with _LOCK:
        return json.loads(p.read_text())


def _file_put(key: str, value: dict) -> None:
    p = _path(key)
    with _LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix('.tmp')
        tmp.write_text(json.dumps(value, indent=1, default=str))
        tmp.replace(p)


# ── public ───────────────────────────────────────────────────────────────────

def get(key: str):
    b = backend()
    if b == 'postgres':
        return _pg_get(key)
    if b == 'file':
        return _file_get(key)
    return None


def put(key: str, value: dict) -> None:
    b = backend()
    if b == 'postgres':
        return _pg_put(key, value)
    if b == 'file':
        return _file_put(key, value)
    raise StoreUnavailable(
        'No database is connected, so the portfolio cannot be saved on this server. '
        'In Vercel, open Storage, create a Postgres (Neon) database, connect it to '
        'this project and redeploy.'
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
