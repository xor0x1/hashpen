PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS articles (
    id              INTEGER PRIMARY KEY,
    slug            TEXT    NOT NULL UNIQUE,
    title           TEXT    NOT NULL,
    body_md         TEXT    NOT NULL,
    body_html       TEXT    NOT NULL,
    toc_json        TEXT    NOT NULL DEFAULT '[]',
    plain_text      TEXT    NOT NULL DEFAULT '',
    excerpt         TEXT    NOT NULL DEFAULT '',
    reading_minutes INTEGER NOT NULL DEFAULT 1,
    status          TEXT    NOT NULL DEFAULT 'published' CHECK (status IN ('draft', 'published')),
    published_at    TEXT    NOT NULL,                       -- YYYY-MM-DD
    created_at      TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_articles_status_date ON articles (status, published_at DESC);

CREATE TABLE IF NOT EXISTS tags (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    slug TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS article_tags (
    article_id INTEGER NOT NULL REFERENCES articles (id) ON DELETE CASCADE,
    tag_id     INTEGER NOT NULL REFERENCES tags (id) ON DELETE CASCADE,
    PRIMARY KEY (article_id, tag_id)
);

-- Полнотекстовый индекс; rowid = articles.id, синхронизируется в models.save_article/delete_article
CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5 (
    title, tags, body,
    tokenize = 'unicode61 remove_diacritics 2'
);

-- ---------- вход автора (этап 2) ----------

CREATE TABLE IF NOT EXISTS auth_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS used_backup_codes (
    hash    TEXT PRIMARY KEY,
    used_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS login_attempts (
    ip TEXT NOT NULL,
    ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_attempts ON login_attempts (ip, ts);

-- ---------- отдельные страницы (этап 5) ----------

CREATE TABLE IF NOT EXISTS pages (
    id         INTEGER PRIMARY KEY,
    slug       TEXT    NOT NULL UNIQUE,
    title      TEXT    NOT NULL,
    body_md    TEXT    NOT NULL,
    body_html  TEXT    NOT NULL,
    toc_json   TEXT    NOT NULL DEFAULT '[]',
    excerpt    TEXT    NOT NULL DEFAULT '',
    status     TEXT    NOT NULL DEFAULT 'published' CHECK (status IN ('draft', 'published')),
    in_sidebar INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 100,
    created_at TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pages_sidebar ON pages (status, in_sidebar, sort_order);
