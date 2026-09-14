"""Версии схемы базы.

Версия хранится в самой SQLite (`PRAGMA user_version`). Порядок такой:

* пустая или старая база (версия 0) — накатывается `schema.sql`, она же версия 1;
  для уже работающего сайта это безопасно: все CREATE написаны с IF NOT EXISTS,
  существующие таблицы и данные не трогаются;
* дальше по очереди применяются шаги из MIGRATIONS с номером больше текущего.

Чтобы изменить схему, добавьте шаг с новым номером в конец списка — и всё.
Никогда не правьте уже выпущенный шаг: на чужих базах он давно применён.
"""
from pathlib import Path

SCHEMA_SQL = Path(__file__).parent / "schema.sql"

MIGRATIONS = [
    (2, [
        """CREATE TABLE IF NOT EXISTS settings (
               key        TEXT PRIMARY KEY,
               value      TEXT NOT NULL,
               updated_at TEXT NOT NULL DEFAULT (datetime('now'))
           )""",
    ]),
]

LATEST = MIGRATIONS[-1][0] if MIGRATIONS else 1


def current_version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def upgrade(conn, log=None):
    """Приводит базу к последней версии. Возвращает список применённых шагов."""
    applied = []
    version = current_version(conn)

    if version == 0:
        conn.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
        conn.execute("PRAGMA user_version = 1")
        version = 1
        applied.append(1)

    for number, steps in MIGRATIONS:
        if number <= version:
            continue
        for sql in steps:
            conn.execute(sql)
        conn.execute(f"PRAGMA user_version = {number}")
        applied.append(number)
        if log:
            log(f"применён шаг {number}")

    conn.commit()
    return applied
