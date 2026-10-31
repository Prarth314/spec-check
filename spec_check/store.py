"""Local persistent documents and page-bounded retrieval chunks."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def data_dir() -> Path:
    path = Path(os.getenv("SPEC_CHECK_DATA_DIR", "data")).resolve()
    path.mkdir(parents=True, exist_ok=True)
    (path / "pdfs").mkdir(exist_ok=True)
    return path


@contextmanager
def connect():
    db = sqlite3.connect(data_dir() / "spec-check.sqlite3", timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
        db.commit()
    finally:
        db.close()


def initialize():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, sha256 TEXT UNIQUE NOT NULL,
          pages INTEGER NOT NULL, chunks INTEGER NOT NULL, warnings TEXT NOT NULL,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS chunks (
          id INTEGER PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
          page INTEGER NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS chunk_document ON chunks(document_id);
        """)
