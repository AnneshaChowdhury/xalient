import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


DB_PATH = Path("xreach.db")


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection configured for dict-like rows."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def db_connection() -> Iterator[sqlite3.Connection]:
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tweet_url TEXT NOT NULL UNIQUE,
                author_handle TEXT,
                author_name TEXT,
                follower_count INTEGER DEFAULT 0,
                tweet_text TEXT NOT NULL,
                timestamp TEXT,
                processed INTEGER NOT NULL DEFAULT 0 CHECK (processed IN (0, 1))
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS drafts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER NOT NULL,
                is_hiring INTEGER NOT NULL CHECK (is_hiring IN (0, 1)),
                confidence REAL NOT NULL DEFAULT 0.0,
                reply_draft TEXT,
                dm_draft TEXT,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'skipped', 'sent')),
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (post_id) REFERENCES posts (id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_posts_processed ON posts (processed)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_drafts_status_created "
            "ON drafts (status, created_at DESC)"
        )


def insert_post(
    tweet_url: str,
    author_handle: str | None,
    author_name: str | None,
    follower_count: int | None,
    tweet_text: str,
    timestamp: str | None,
) -> bool:
    """Insert a post if it has not been seen. Returns True when inserted."""
    with db_connection() as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO posts (
                tweet_url,
                author_handle,
                author_name,
                follower_count,
                tweet_text,
                timestamp
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                tweet_url,
                author_handle,
                author_name,
                follower_count or 0,
                tweet_text,
                timestamp,
            ),
        )
        return cursor.rowcount == 1


def post_exists(tweet_url: str) -> bool:
    with db_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM posts WHERE tweet_url = ? LIMIT 1",
            (tweet_url,),
        ).fetchone()
        return row is not None


def main() -> None:
    init_db()
    print(f"Initialized database at {DB_PATH.resolve()}")


if __name__ == "__main__":
    main()
