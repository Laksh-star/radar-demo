"""
The dedup / persistence layer — real, working SQLite, not mocked. This is
what the diagram calls the "State store" on the right, plus the final
"Persist" step (stage 7) that would in production be your create_brief /
get_trending_competitors tool calls. Here it's a local dashboard.sqlite file
so the demo is fully runnable without any external service.
"""

import sqlite3
from pathlib import Path

from models import Signal

DB_PATH = Path(__file__).parent / "dashboard.sqlite"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS seen_entities (
            entity_key TEXT PRIMARY KEY,
            first_seen TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS signals (
            url TEXT PRIMARY KEY,
            entity TEXT,
            source TEXT,
            status TEXT,
            category TEXT,
            relevance_score REAL,
            brief TEXT,
            seen_date TEXT
        )
        """
    )
    return conn


def entity_key(entity: str, source: str) -> str:
    return f"{source}:{entity.lower().strip()}"


def has_seen(entity: str, source: str) -> bool:
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM seen_entities WHERE entity_key = ?",
            (entity_key(entity, source),),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def mark_seen(entity: str, source: str, seen_date: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO seen_entities (entity_key, first_seen) VALUES (?, ?)",
            (entity_key(entity, source), seen_date),
        )
        conn.commit()
    finally:
        conn.close()


def persist(signal: Signal) -> None:
    """Stage 7 — the equivalent of create_brief / get_trending_competitors."""
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO signals
                (url, entity, source, status, category, relevance_score, brief, seen_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(signal.raw.url),
                signal.raw.entity,
                signal.raw.source.value,
                signal.status.value,
                signal.triage.category.value,
                signal.triage.relevance_score,
                signal.brief,
                signal.raw.seen_date.isoformat(),
            ),
        )
        conn.commit()
        mark_seen(signal.raw.entity, signal.raw.source.value, signal.raw.seen_date.isoformat())
    finally:
        conn.close()


def reset() -> None:
    """Wipe the local demo database so the pipeline can be re-run from scratch."""
    if DB_PATH.exists():
        DB_PATH.unlink()
