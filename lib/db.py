"""SQLite state tracking — schema, insert/query helpers."""

import json
import sqlite3
from datetime import datetime, timezone


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_schema(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS programs (
            platform      TEXT NOT NULL,
            handle        TEXT NOT NULL,
            name          TEXT,
            url           TEXT,
            max_bounty    REAL DEFAULT 0,
            scope_hash    TEXT,
            scope_count   INTEGER DEFAULT 0,
            first_seen_at TEXT,
            last_seen_at  TEXT,
            last_score    REAL DEFAULT 0,
            enrichment    TEXT DEFAULT '{}',
            PRIMARY KEY (platform, handle)
        );

        CREATE TABLE IF NOT EXISTS change_events (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            platform    TEXT NOT NULL,
            handle      TEXT NOT NULL,
            event_type  TEXT NOT NULL,
            details     TEXT DEFAULT '{}',
            score       REAL DEFAULT 0,
            detected_at TEXT NOT NULL,
            notified    INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS notification_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id    INTEGER,
            channel     TEXT NOT NULL,
            sent_at     TEXT NOT NULL,
            FOREIGN KEY (event_id) REFERENCES change_events(id)
        );
    """)
    conn.commit()


def upsert_program(conn, platform, handle, name=None, url=None,
                    max_bounty=0, scope_hash=None, scope_count=0, score=0):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO programs (platform, handle, name, url, max_bounty,
                              scope_hash, scope_count, first_seen_at,
                              last_seen_at, last_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(platform, handle) DO UPDATE SET
            name = COALESCE(excluded.name, name),
            url = COALESCE(excluded.url, url),
            max_bounty = excluded.max_bounty,
            scope_hash = excluded.scope_hash,
            scope_count = excluded.scope_count,
            last_seen_at = excluded.last_seen_at,
            last_score = excluded.last_score
    """, (platform, handle, name, url, max_bounty, scope_hash, scope_count,
          now, now, score))
    conn.commit()


def insert_event(conn, platform, handle, event_type, details, score, detected_at=None):
    if detected_at is None:
        detected_at = datetime.now(timezone.utc).isoformat()
    cur = conn.execute("""
        INSERT INTO change_events (platform, handle, event_type, details, score, detected_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (platform, handle, event_type, json.dumps(details), score, detected_at))
    conn.commit()
    return cur.lastrowid


def is_duplicate_event(conn, platform, handle, event_type, details):
    """Check if this event type was already recorded and notified for this program."""
    row = conn.execute("""
        SELECT id FROM change_events
        WHERE platform = ? AND handle = ? AND event_type = ? AND notified = 1
    """, (platform, handle, event_type)).fetchone()
    return row is not None


def mark_notified(conn, event_id, channel="discord"):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE change_events SET notified = 1 WHERE id = ?", (event_id,))
    conn.execute("""
        INSERT INTO notification_log (event_id, channel, sent_at)
        VALUES (?, ?, ?)
    """, (event_id, channel, now))
    conn.commit()


def get_top_programs(conn, limit=20):
    return conn.execute("""
        SELECT platform, handle, name, url, max_bounty, scope_count,
               last_score, first_seen_at, last_seen_at
        FROM programs
        ORDER BY last_score DESC
        LIMIT ?
    """, (limit,)).fetchall()


def get_unnotified_events(conn, min_score=0):
    return conn.execute("""
        SELECT id, platform, handle, event_type, details, score, detected_at
        FROM change_events
        WHERE notified = 0 AND score >= ?
        ORDER BY score DESC
    """, (min_score,)).fetchall()
