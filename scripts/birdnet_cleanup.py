#!/usr/bin/env python3

import os
import sqlite3
import sys

from datetime import datetime, timedelta


sys.stdout.reconfigure(line_buffering=True)


DB_PATH = "/home/jolin/bird_monitor_data/birdnet_buffer.db"

RETENTION_HOURS = 24


def main():

    print("==========================================")
    print("BirdNET SQLite Cleanup")
    print("==========================================")
    print(f"[CONFIG] Database: {DB_PATH}")
    print(f"[CONFIG] sent=1 retention: {RETENTION_HOURS} hours")
    print("[CONFIG] sent=0 events are protected")
    print("==========================================")

    if not os.path.exists(DB_PATH):

        print("[CLEANUP] Database does not exist.")
        return

    # Current local time minus 24 hours.
    cutoff = (
        datetime.now().astimezone()
        - timedelta(hours=RETENTION_HOURS)
    )

    cutoff_text = cutoff.isoformat()

    conn = sqlite3.connect(
        DB_PATH,
        timeout=10
    )

    try:

        # ----------------------------------------------------
        # sent=0 = not confirmed by Firestore
        # These rows must NEVER be age-deleted.
        # ----------------------------------------------------

        pending_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM detections
            WHERE sent = 0
            """
        ).fetchone()[0]

        # ----------------------------------------------------
        # Only successfully delivered rows older than 24 h
        # are eligible for deletion.
        # ----------------------------------------------------

        eligible_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM detections
            WHERE sent = 1
              AND sent_at IS NOT NULL
              AND sent_at < ?
            """,
            (cutoff_text,)
        ).fetchone()[0]

        print(
            f"[CLEANUP] Pending sent=0 rows protected: "
            f"{pending_count}"
        )

        print(
            f"[CLEANUP] sent=1 rows older than 24 h: "
            f"{eligible_count}"
        )

        cursor = conn.execute(
            """
            DELETE FROM detections
            WHERE sent = 1
              AND sent_at IS NOT NULL
              AND sent_at < ?
            """,
            (cutoff_text,)
        )

        deleted = cursor.rowcount

        conn.commit()

        print(
            f"[CLEANUP] Deleted: {deleted}"
        )

        integrity = conn.execute(
            "PRAGMA integrity_check;"
        ).fetchone()[0]

        print(
            f"[CLEANUP] Database integrity: {integrity}"
        )

        conn.execute(
            "PRAGMA wal_checkpoint(PASSIVE);"
        )

        print("[CLEANUP] Complete.")

    finally:

        conn.close()


if __name__ == "__main__":
    main()
