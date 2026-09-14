import sqlite3
from pathlib import Path

from flask import current_app, g


def connect(path):
    conn = sqlite3.connect(path, detect_types=0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(path):
    """Создаёт базу, если её нет, и доводит схему до последней версии."""
    from . import migrations

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        applied = migrations.upgrade(conn)
    finally:
        conn.close()
    return applied
