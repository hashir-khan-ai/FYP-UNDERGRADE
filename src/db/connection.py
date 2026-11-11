"""SQLite database connection and lifecycle management."""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from src.config import settings


def get_db_path(custom_path: str | None = None) -> str:
    """Return database file path, ensuring parent directory exists."""
    path_str = custom_path or settings.DATABASE_PATH
    Path(path_str).parent.mkdir(parents=True, exist_ok=True)
    return path_str


@contextmanager
def get_db_connection(db_path: str | None = None) -> Generator[sqlite3.Connection, None, None]:
    """
    Context manager providing a configured SQLite connection.
    Enforces WAL mode and foreign key constraints.
    """
    path = get_db_path(db_path)
    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row

    # Performance and integrity pragmas
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")

    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

