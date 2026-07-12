"""
db.py
SQLite persistence for ClonerCC.

Each row in the `videos` table represents one TikTok video:
  - url          : canonical video URL (primary key)
  - profile      : TikTok handle, e.g. "dakpsico1"
  - description  : caption / hashtags written by the creator
  - status       : pending | downloaded | error
  - file_path    : absolute path of the downloaded file (filled after download)
  - scraped_at   : ISO-8601 timestamp of when the URL was first seen
  - downloaded_at: ISO-8601 timestamp of when the download completed
  - error_msg    : last error message (if status = error)
"""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

DB_PATH = Path(__file__).parent / "clonercc.db"

VideoStatus = Literal["pending", "downloaded", "error", "cleared"]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class VideoRecord:
    url: str
    profile: str
    description: str = ""
    status: VideoStatus = "pending"
    file_path: Optional[str] = None
    scraped_at: str = field(default_factory=lambda: _now())
    downloaded_at: Optional[str] = None
    error_msg: Optional[str] = None

    @property
    def video_id(self) -> str:
        """Extract the numeric video ID from the URL."""
        return self.url.rstrip("/").split("/")[-1]

    def mark_downloaded(self, file_path: str) -> None:
        self.status = "downloaded"
        self.file_path = file_path
        self.downloaded_at = _now()

    def mark_error(self, msg: str) -> None:
        self.status = "error"
        self.error_msg = msg


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

class Database:
    def __init__(self, path: Path = DB_PATH) -> None:
        self._path = path
        self._init()

    def _init(self) -> None:
        """Create the database and tables if they don't exist."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS videos (
                    url            TEXT PRIMARY KEY,
                    profile        TEXT NOT NULL,
                    description    TEXT NOT NULL DEFAULT '',
                    status         TEXT NOT NULL DEFAULT 'pending',
                    file_path      TEXT,
                    scraped_at     TEXT NOT NULL,
                    downloaded_at  TEXT,
                    error_msg      TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_profile ON videos(profile)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_status  ON videos(status)")

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ── Write operations ────────────────────────────────────────────────────

    def upsert_video(self, record: VideoRecord) -> None:
        """
        Insert a new video record or update description/scraped_at if it already exists.
        Never overwrites status, file_path, or downloaded_at for existing rows.
        """
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO videos (url, profile, description, status, scraped_at)
                VALUES (:url, :profile, :description, :status, :scraped_at)
                ON CONFLICT(url) DO UPDATE SET
                    description = CASE
                        WHEN excluded.description != '' THEN excluded.description
                        ELSE videos.description
                    END
            """, {
                "url"        : record.url,
                "profile"    : record.profile,
                "description": record.description,
                "status"     : record.status,
                "scraped_at" : record.scraped_at,
            })

    def mark_downloaded(self, url: str, file_path: str) -> None:
        with self._connect() as conn:
            conn.execute("""
                UPDATE videos
                SET status = 'downloaded', file_path = ?, downloaded_at = ?
                WHERE url = ?
            """, (file_path, _now(), url))

    def mark_error(self, url: str, msg: str) -> None:
        with self._connect() as conn:
            conn.execute("""
                UPDATE videos
                SET status = 'error', error_msg = ?
                WHERE url = ?
            """, (msg, url))

    def mark_cleared(self, file_path: str, mov_path: str) -> None:
        """Marca o vídeo como 'cleared' após limpeza de metadados bem-sucedida."""
        with self._connect() as conn:
            conn.execute("""
                UPDATE videos
                SET status = 'cleared', file_path = ?
                WHERE file_path = ?
            """, (mov_path, file_path))

    def update_description(self, url: str, description: str) -> None:
        """Update the description of an existing record."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE videos SET description = ? WHERE url = ?",
                (description, url)
            )

    def delete_video(self, url: str) -> None:
        """Delete a single video record by URL."""
        with self._connect() as conn:
            conn.execute("DELETE FROM videos WHERE url = ?", (url,))

    def delete_all(self, profile: Optional[str] = None) -> int:
        """
        Delete all records, optionally filtered by profile.
        Returns the number of rows deleted.
        """
        with self._connect() as conn:
            if profile:
                cur = conn.execute(
                    "DELETE FROM videos WHERE profile = ?",
                    (profile.lstrip("@"),)
                )
            else:
                cur = conn.execute("DELETE FROM videos")
            return cur.rowcount

    def reset_errors(self, profile: Optional[str] = None) -> int:
        """Reset all 'error' records back to 'pending' so they can be retried."""
        with self._connect() as conn:
            if profile:
                cur = conn.execute(
                    "UPDATE videos SET status='pending', error_msg=NULL WHERE status='error' AND profile=?",
                    (profile.lstrip("@"),)
                )
            else:
                cur = conn.execute(
                    "UPDATE videos SET status='pending', error_msg=NULL WHERE status='error'"
                )
            return cur.rowcount

    # ── Read operations ─────────────────────────────────────────────────────

    def get_pending(self, profile: Optional[str] = None) -> list[VideoRecord]:
        """Return all pending videos, optionally filtered by profile."""
        with self._connect() as conn:
            if profile:
                rows = conn.execute(
                    "SELECT * FROM videos WHERE status = 'pending' AND profile = ? ORDER BY scraped_at",
                    (profile.lstrip("@"),)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM videos WHERE status = 'pending' ORDER BY scraped_at"
                ).fetchall()
        return [_row_to_record(r) for r in rows]

    def get_all(self, profile: Optional[str] = None) -> list[VideoRecord]:
        """Return all videos, optionally filtered by profile."""
        with self._connect() as conn:
            if profile:
                rows = conn.execute(
                    "SELECT * FROM videos WHERE profile = ? ORDER BY scraped_at DESC",
                    (profile.lstrip("@"),)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM videos ORDER BY scraped_at DESC"
                ).fetchall()
        return [_row_to_record(r) for r in rows]

    def get_known_urls(self, profile: str) -> set[str]:
        """Return the set of all URLs already seen for a given profile."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT url FROM videos WHERE profile = ?",
                (profile.lstrip("@"),)
            ).fetchall()
        return {r["url"] for r in rows}

    def stats(self, profile: Optional[str] = None) -> dict:
        """Return a summary dict with counts per status."""
        with self._connect() as conn:
            if profile:
                rows = conn.execute(
                    "SELECT status, COUNT(*) as n FROM videos WHERE profile = ? GROUP BY status",
                    (profile.lstrip("@"),)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT status, COUNT(*) as n FROM videos GROUP BY status"
                ).fetchall()
        return {r["status"]: r["n"] for r in rows}


def _row_to_record(row: sqlite3.Row) -> VideoRecord:
    return VideoRecord(
        url          = row["url"],
        profile      = row["profile"],
        description  = row["description"] or "",
        status       = row["status"],
        file_path    = row["file_path"],
        scraped_at   = row["scraped_at"],
        downloaded_at= row["downloaded_at"],
        error_msg    = row["error_msg"],
    )


# ---------------------------------------------------------------------------
# Module-level singleton (convenience)
# ---------------------------------------------------------------------------

_db: Optional[Database] = None

def get_db(path: Path = DB_PATH) -> Database:
    global _db
    if _db is None:
        _db = Database(path)
    return _db
