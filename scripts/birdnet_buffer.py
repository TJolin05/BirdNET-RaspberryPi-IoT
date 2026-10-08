#!/usr/bin/env python3

import os
import sqlite3
import hashlib
from datetime import datetime

DB_DIR = "/home/jolin/bird_monitor_data"
DB_PATH = os.path.join(DB_DIR, "birdnet_buffer.db")

os.makedirs(DB_DIR, exist_ok=True)


def get_connection():
    conn = sqlite3.connect(DB_PATH, timeout=5)

    # Better reliability for continuous Raspberry Pi operation
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=FULL;")
    conn.execute("PRAGMA busy_timeout=5000;")

    return conn


def init_db():
    conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS detections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            species_code TEXT NOT NULL,
            common_name TEXT NOT NULL,
            sci_name TEXT NOT NULL,
            confidence REAL NOT NULL,

            detected_at TEXT NOT NULL,
            node_id TEXT NOT NULL,

            lat REAL,
            lon REAL,

            sent INTEGER NOT NULL DEFAULT 0,
            sent_at TEXT,

            attempts INTEGER NOT NULL DEFAULT 0,

            event_id TEXT,
            start_time TEXT,
            end_time TEXT,
            duration REAL
        )
    """)

    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_event_id
        ON detections(event_id)
        WHERE event_id IS NOT NULL
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_pending
        ON detections(sent, id)
    """)

    conn.commit()
    conn.close()

    print(f"[SQLITE] Database ready: {DB_PATH}")


def make_event_id(node_id, species_code, start_time, end_time):
    raw = f"{node_id}|{species_code}|{start_time}|{end_time}"

    digest = hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:16]

    return f"{node_id}_{digest}"


def insert_event(
    species_code,
    common_name,
    sci_name,
    confidence,
    detected_at,
    node_id,
    lat=None,
    lon=None,
    event_id=None,
    start_time=None,
    end_time=None,
    duration=None
):
    init_db()

    if event_id is None:
        event_id = make_event_id(
            node_id,
            species_code,
            start_time,
            end_time
        )

    conn = get_connection()

    cursor = conn.execute("""
        INSERT OR IGNORE INTO detections (
            species_code,
            common_name,
            sci_name,
            confidence,
            detected_at,
            node_id,
            lat,
            lon,
            sent,
            sent_at,
            attempts,
            event_id,
            start_time,
            end_time,
            duration
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, 0, ?, ?, ?, ?)
    """, (
        species_code,
        common_name,
        sci_name,
        confidence,
        detected_at,
        node_id,
        lat,
        lon,
        event_id,
        start_time,
        end_time,
        duration
    ))

    inserted = cursor.rowcount > 0

    conn.commit()

    if inserted:
        detection_id = cursor.lastrowid

        print(
            f"[SQLITE] Event stored: "
            f"id={detection_id}, "
            f"event_id={event_id}, "
            f"sent=0"
        )
    else:
        row = conn.execute(
            "SELECT id FROM detections WHERE event_id = ?",
            (event_id,)
        ).fetchone()

        detection_id = row[0] if row else None

        print(
            f"[SQLITE] Event already exists: "
            f"event_id={event_id}"
        )

    conn.close()

    return detection_id, event_id, inserted


def get_pending(limit=100):
    conn = get_connection()

    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT *
        FROM detections
        WHERE sent = 0
        ORDER BY id ASC
        LIMIT ?
    """, (limit,)).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def mark_sent_by_event_id(event_id):
    conn = get_connection()

    sent_at = datetime.now().astimezone().isoformat()

    conn.execute("""
        UPDATE detections
        SET sent = 1,
            sent_at = ?
        WHERE event_id = ?
    """, (
        sent_at,
        event_id
    ))

    conn.commit()
    conn.close()


def increment_attempts(event_id):
    conn = get_connection()

    conn.execute("""
        UPDATE detections
        SET attempts = attempts + 1
        WHERE event_id = ?
    """, (event_id,))

    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
