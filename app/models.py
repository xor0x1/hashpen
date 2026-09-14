"""Работа со статьями и тегами."""
import json
import re
from datetime import date

from . import content
from .db import get_db

PUBLISHED = "published"
DRAFT = "draft"


def _tags_for(db, article_ids):
    if not article_ids:
        return {}
    q = ",".join("?" * len(article_ids))
    rows = db.execute(
        f"""SELECT at.article_id, t.name, t.slug FROM article_tags at
            JOIN tags t ON t.id = at.tag_id
            WHERE at.article_id IN ({q}) ORDER BY t.name COLLATE NOCASE""",
        article_ids,
    ).fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["article_id"], []).append({"name": r["name"], "slug": r["slug"]})
    return out


def _attach_tags(db, rows):
    items = [dict(r) for r in rows]
    tags = _tags_for(db, [a["id"] for a in items])
    for a in items:
        a["tags"] = tags.get(a["id"], [])
        if "toc_json" in a:
            a["toc"] = json.loads(a.pop("toc_json") or "[]")
    return items


LIST_COLS = "a.id, a.slug, a.title, a.excerpt, a.reading_minutes, a.status, a.published_at"


def list_articles(tag_slug=None, include_drafts=False, limit=20, offset=0):
    db = get_db()
    where, params = [], []
    if not include_drafts:
        where.append("a.status = 'published'")
    join = ""
    if tag_slug:
        join = "JOIN article_tags at ON at.article_id = a.id JOIN tags t ON t.id = at.tag_id"
        where.append("t.slug = ?")
        params.append(tag_slug)
    sql_where = ("WHERE " + " AND ".join(where)) if where else ""
    total = db.execute(f"SELECT COUNT(*) FROM articles a {join} {sql_where}", params).fetchone()[0]
    rows = db.execute(
        f"SELECT {LIST_COLS} FROM articles a {join} {sql_where} "
        "ORDER BY a.published_at DESC, a.id DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()
    return _attach_tags(db, rows), total


def get_article(slug, include_drafts=False):
    db = get_db()
    sql = "SELECT * FROM articles WHERE slug = ?"
    if not include_drafts:
        sql += " AND status = 'published'"
    row = db.execute(sql, (slug,)).fetchone()
    return _attach_tags(db, [row])[0] if row else None


def tag_counts(include_drafts=False):
    cond = "" if include_drafts else "WHERE a.status = 'published'"
    return get_db().execute(
        f"""SELECT t.name, t.slug, COUNT(*) AS count FROM tags t
            JOIN article_tags at ON at.tag_id = t.id
            JOIN articles a ON a.id = at.article_id {cond}
            GROUP BY t.id ORDER BY t.name COLLATE NOCASE"""
    ).fetchall()


def get_tag(slug):
    return get_db().execute("SELECT name, slug FROM tags WHERE slug = ?", (slug,)).fetchone()


def count_articles(include_drafts=False):
    cond = "" if include_drafts else "WHERE status = 'published'"
    return get_db().execute(f"SELECT COUNT(*) FROM articles {cond}").fetchone()[0]


MARK_OPEN, MARK_CLOSE = "\x02", "\x03"  # метки совпадений: текст экранируем, потом заменяем их на <mark>


def search(query, include_drafts=False, limit=50):
    words = re.findall(r"\w+", query or "", flags=re.U)
    if not words:
        return []
    match = " ".join(f'"{w}"*' for w in words[:12])
    db = get_db()
    cond = "" if include_drafts else "AND a.status = 'published'"
    rows = db.execute(
        f"""SELECT {LIST_COLS},
                   snippet(articles_fts, 2, ?, ?, '…', 22) AS snippet
            FROM articles_fts f JOIN articles a ON a.id = f.rowid
            WHERE articles_fts MATCH ? {cond}
            ORDER BY bm25(articles_fts, 10.0, 5.0, 1.0) LIMIT ?""",
        (MARK_OPEN, MARK_CLOSE, match, limit),
    ).fetchall()
    items = _attach_tags(db, rows)
    for a in items:
        a["snippet"] = content.mark_to_html(a["snippet"] or a["excerpt"])
        a["title_marked"] = content.highlight_words(a["title"], words)
    return items


def unique_slug(base, exclude_id=None):
    db = get_db()
    slug, n = base, 2
    while True:
        row = db.execute("SELECT id FROM articles WHERE slug = ?", (slug,)).fetchone()
        if not row or row["id"] == exclude_id:
            return slug
        slug, n = f"{base}-{n}", n + 1


def _set_tags(db, article_id, names):
    db.execute("DELETE FROM article_tags WHERE article_id = ?", (article_id,))
    for name in names:
        row = db.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        if row:
            tag_id = row["id"]
        else:
            base = content.slugify(name, "tag")
            slug, n = base, 2
            while db.execute("SELECT 1 FROM tags WHERE slug = ?", (slug,)).fetchone():
                slug, n = f"{base}-{n}", n + 1
            tag_id = db.execute("INSERT INTO tags (name, slug) VALUES (?, ?)", (name, slug)).lastrowid
        db.execute("INSERT OR IGNORE INTO article_tags VALUES (?, ?)", (article_id, tag_id))
    db.execute("DELETE FROM tags WHERE id NOT IN (SELECT tag_id FROM article_tags)")


def parse_tags(value):
    if isinstance(value, str):
        value = value.split(",")
    seen, out = set(), []
    for t in value or []:
        t = str(t).strip().lstrip("#").strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def save_article(title, body_md, tags=(), published_at=None, status=PUBLISHED, slug=None, article_id=None):
    """Создаёт (article_id=None) или обновляет статью. Возвращает slug."""
    db = get_db()
    title = title.strip()
    tags = parse_tags(tags)
    published_at = str(published_at or date.today().isoformat())[:10]
    slug = unique_slug(content.slugify(slug or title), exclude_id=article_id)
    built = content.build(body_md)
    fields = dict(title=title, slug=slug, body_md=body_md, status=status, published_at=published_at, **built)

    if article_id is None:
        cols = ", ".join(fields)
        article_id = db.execute(
            f"INSERT INTO articles ({cols}) VALUES ({', '.join('?' * len(fields))})", list(fields.values())
        ).lastrowid
    else:
        sets = ", ".join(f"{k} = ?" for k in fields)
        db.execute(
            f"UPDATE articles SET {sets}, updated_at = datetime('now') WHERE id = ?",
            list(fields.values()) + [article_id],
        )

    _set_tags(db, article_id, tags)
    db.execute("DELETE FROM articles_fts WHERE rowid = ?", (article_id,))
    db.execute(
        "INSERT INTO articles_fts (rowid, title, tags, body) VALUES (?, ?, ?, ?)",
        (article_id, title, " ".join(tags), built["plain_text"]),
    )
    db.commit()
    return slug


def delete_article(article_id):
    db = get_db()
    db.execute("DELETE FROM articles WHERE id = ?", (article_id,))
    db.execute("DELETE FROM articles_fts WHERE rowid = ?", (article_id,))
    db.execute("DELETE FROM tags WHERE id NOT IN (SELECT tag_id FROM article_tags)")
    db.commit()


def all_for_sitemap():
    return get_db().execute(
        "SELECT slug, title, published_at, updated_at FROM articles WHERE status = 'published' "
        "ORDER BY published_at DESC, id DESC"
    ).fetchall()


def latest_full(limit=20):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM articles WHERE status = 'published' ORDER BY published_at DESC, id DESC LIMIT ?", (limit,)
    ).fetchall()
    return _attach_tags(db, rows)


# ---------- отдельные страницы ----------

# Адреса, которые нельзя занимать страницами: они уже заняты сайтом.
RESERVED_SLUGS = {
    "a", "admin", "login", "logout", "search", "tag", "tags", "static", "uploads",
    "privacy", "sitemap", "sitemap.xml", "rss.xml", "robots.txt", "feed", "api", "p",
}


def list_pages(include_drafts=False, sidebar_only=False):
    cond = ["1 = 1"]
    if not include_drafts:
        cond.append("status = 'published'")
    if sidebar_only:
        cond.append("in_sidebar = 1")
    rows = get_db().execute(
        f"SELECT id, slug, title, status, in_sidebar, sort_order FROM pages "
        f"WHERE {' AND '.join(cond)} ORDER BY sort_order, title COLLATE NOCASE"
    ).fetchall()
    return [dict(r) for r in rows]


def get_page(slug, include_drafts=False):
    sql = "SELECT * FROM pages WHERE slug = ?"
    if not include_drafts:
        sql += " AND status = 'published'"
    row = get_db().execute(sql, (slug,)).fetchone()
    if not row:
        return None
    p = dict(row)
    p["toc"] = json.loads(p.pop("toc_json") or "[]")
    return p


def slug_is_free(slug, exclude_id=None):
    if slug in RESERVED_SLUGS or "/" in slug:
        return False
    row = get_db().execute("SELECT id FROM pages WHERE slug = ?", (slug,)).fetchone()
    return not row or row["id"] == exclude_id


def save_page(title, body_md, slug=None, status=PUBLISHED, in_sidebar=True, sort_order=100, page_id=None):
    db = get_db()
    title = title.strip()
    slug = content.slugify(slug or title)
    built = content.build(body_md)
    fields = {
        "slug": slug, "title": title, "body_md": body_md, "body_html": built["body_html"],
        "toc_json": built["toc_json"], "excerpt": built["excerpt"], "status": status,
        "in_sidebar": 1 if in_sidebar else 0, "sort_order": int(sort_order),
    }
    if page_id is None:
        cols = ", ".join(fields)
        db.execute(f"INSERT INTO pages ({cols}) VALUES ({', '.join('?' * len(fields))})", list(fields.values()))
    else:
        sets = ", ".join(f"{k} = ?" for k in fields)
        db.execute(f"UPDATE pages SET {sets}, updated_at = datetime('now') WHERE id = ?",
                   list(fields.values()) + [page_id])
    db.commit()
    return slug


def delete_page(page_id):
    db = get_db()
    db.execute("DELETE FROM pages WHERE id = ?", (page_id,))
    db.commit()
