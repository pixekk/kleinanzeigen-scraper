from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import Listing

SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_ads (
    search_name TEXT NOT NULL,
    ad_id       TEXT NOT NULL,
    title       TEXT NOT NULL,
    url         TEXT NOT NULL,
    price       INTEGER,
    price_text  TEXT,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    notified_at TEXT,
    PRIMARY KEY (search_name, ad_id)
);
CREATE TABLE IF NOT EXISTS search_state (
    search_name  TEXT PRIMARY KEY,
    last_run     TEXT,
    seeded       INTEGER NOT NULL DEFAULT 0,
    last_error   TEXT
);
CREATE INDEX IF NOT EXISTS idx_seen_last ON seen_ads (search_name, last_seen);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def is_seeded(self, search_name: str) -> bool:
        row = self._conn.execute(
            "SELECT seeded FROM search_state WHERE search_name = ?", (search_name,)
        ).fetchone()
        return bool(row and row["seeded"])

    def mark_seeded(self, search_name: str) -> None:
        self._conn.execute(
            "INSERT INTO search_state (search_name, seeded, last_run) VALUES (?, 1, ?) "
            "ON CONFLICT(search_name) DO UPDATE SET seeded = 1, last_run = excluded.last_run",
            (search_name, _now()),
        )
        self._conn.commit()

    def record_run(self, search_name: str, error: Optional[str] = None) -> None:
        self._conn.execute(
            "INSERT INTO search_state (search_name, last_run, last_error) VALUES (?, ?, ?) "
            "ON CONFLICT(search_name) DO UPDATE SET last_run = excluded.last_run, "
            "last_error = excluded.last_error",
            (search_name, _now(), error),
        )
        self._conn.commit()

    def known_price(self, search_name: str, ad_id: str) -> tuple[bool, Optional[int]]:
        row = self._conn.execute(
            "SELECT price FROM seen_ads WHERE search_name = ? AND ad_id = ?",
            (search_name, ad_id),
        ).fetchone()
        if row is None:
            return False, None
        return True, row["price"]

    def upsert(self, search_name: str, listing: Listing, notified: bool) -> None:
        now = _now()
        self._conn.execute(
            "INSERT INTO seen_ads (search_name, ad_id, title, url, price, price_text, "
            "first_seen, last_seen, notified_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(search_name, ad_id) DO UPDATE SET title = excluded.title, "
            "price = excluded.price, price_text = excluded.price_text, last_seen = excluded.last_seen, "
            "notified_at = COALESCE(excluded.notified_at, seen_ads.notified_at)",
            (
                search_name,
                listing.ad_id,
                listing.title,
                listing.url,
                listing.price,
                listing.price_text,
                now,
                now,
                now if notified else None,
            ),
        )
        self._conn.commit()

    def touch(self, search_name: str, ad_id: str) -> None:
        self._conn.execute(
            "UPDATE seen_ads SET last_seen = ? WHERE search_name = ? AND ad_id = ?",
            (_now(), search_name, ad_id),
        )
        self._conn.commit()

    def count(self, search_name: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS total FROM seen_ads WHERE search_name = ?", (search_name,)
        ).fetchone()
        return int(row["total"])

    def prune(self, search_name: str, keep_days: int = 60) -> int:
        cutoff = datetime.now(timezone.utc).timestamp() - keep_days * 86400
        cutoff_iso = datetime.fromtimestamp(cutoff, timezone.utc).isoformat(timespec="seconds")
        with closing(
            self._conn.execute(
                "DELETE FROM seen_ads WHERE search_name = ? AND last_seen < ?",
                (search_name, cutoff_iso),
            )
        ) as cursor:
            self._conn.commit()
            return cursor.rowcount

    def reset(self, search_name: str) -> int:
        with closing(
            self._conn.execute("DELETE FROM seen_ads WHERE search_name = ?", (search_name,))
        ) as cursor:
            self._conn.execute("DELETE FROM search_state WHERE search_name = ?", (search_name,))
            self._conn.commit()
            return cursor.rowcount

    def close(self) -> None:
        self._conn.close()
