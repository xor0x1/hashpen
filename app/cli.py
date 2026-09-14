"""Команды: flask import-json, flask import-md, flask rebuild."""
import json
import re
from datetime import date, datetime
from pathlib import Path

import click
import yaml

from . import content, models
from .db import get_db

FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)


def parse_front_matter(block):
    """YAML, а если он не разобрался — простой разбор «ключ: значение».

    Обычная причина сбоя — двоеточие в заголовке («Блог: как я его писал»):
    по правилам YAML такую строку нужно брать в кавычки, но забывают об этом все.
    """
    try:
        data = yaml.safe_load(block)
        if isinstance(data, dict):
            return data
    except yaml.YAMLError:
        pass

    data = {}
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip().strip("'\"")
        if value.startswith("[") and value.endswith("]"):
            data[key] = [v.strip().strip("'\"") for v in value[1:-1].split(",") if v.strip()]
        else:
            data[key] = value
    return data


def parse_md_file(path):
    text = Path(path).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    meta = {}
    m = FRONT_MATTER.match(text)
    if m:
        meta = parse_front_matter(m.group(1))
        text = text[m.end():]
    title = meta.get("title")
    if not title:
        h1 = re.match(r"\s*#\s+(.+?)\s*#*\s*(\n|$)", text)
        if h1:
            title = h1.group(1)
            text = text[h1.end():]
        else:
            title = Path(path).stem
    d = meta.get("date")
    if isinstance(d, (date, datetime)):
        d = d.isoformat()[:10]
    return {
        "title": str(title),
        "body_md": text.strip() + "\n",
        "tags": models.parse_tags(meta.get("tags") or []),
        "published_at": d or datetime.fromtimestamp(Path(path).stat().st_mtime).date().isoformat(),
        "slug": meta.get("slug"),
        "status": models.DRAFT if meta.get("draft") else models.PUBLISHED,
    }


def _upsert(item, update):
    db = get_db()
    slug = content.slugify(item.get("slug") or item["title"])
    row = db.execute("SELECT id FROM articles WHERE slug = ?", (slug,)).fetchone()
    if row and not update:
        return "skip", slug
    saved = models.save_article(
        title=item["title"], body_md=item["body_md"], tags=item["tags"], published_at=item["published_at"],
        status=item["status"], slug=slug, article_id=row["id"] if row else None,
    )
    return ("update" if row else "new"), saved


def register(app):
    @app.cli.command("import-md")
    @click.argument("folder", type=click.Path(exists=True, file_okay=False, path_type=Path))
    @click.option("--update", is_flag=True, help="Перезаписать статьи с тем же slug.")
    def import_md(folder, update):
        """Импорт всех .md из папки (front matter: title, date, tags, slug, draft)."""
        files = sorted(folder.glob("*.md"))
        if not files:
            click.echo("В папке нет .md файлов.")
        for f in files:
            try:
                action, slug = _upsert(parse_md_file(f), update)
            except Exception as e:  # noqa: BLE001 — продолжаем импорт остальных
                click.echo(f"  ошибка   {f.name}: {e}")
                continue
            click.echo(f"  {action:<8} {f.name} → /a/{slug}")

    @app.cli.command("import-json")
    @click.argument("path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
    @click.option("--update", is_flag=True, help="Перезаписать статьи с тем же slug.")
    def import_json(path, update):
        """Импорт статей из прототипа (index.html со state-data или .json)."""
        raw = path.read_text(encoding="utf-8")
        m = re.search(r'<script id="state-data" type="application/json">(.*?)</script>', raw, re.S)
        data = json.loads(m.group(1) if m else raw)
        for a in data.get("articles", []):
            item = {
                "title": a["title"], "body_md": a.get("contentMd", ""), "tags": a.get("tags", []),
                "published_at": a.get("date"), "slug": a.get("slug"), "status": models.PUBLISHED,
            }
            action, slug = _upsert(item, update)
            click.echo(f"  {action:<8} {a['title']} → /a/{slug}")

    @app.cli.command("set-password")
    def set_password():
        """Задать пароль автора: печатает строку для .env."""
        from werkzeug.security import generate_password_hash

        pwd = click.prompt("Новый пароль", hide_input=True, confirmation_prompt=True)
        if len(pwd) < 10:
            click.echo("Слишком короткий пароль: нужно минимум 10 символов.")
            return
        click.echo("\nВставьте в .env строку:\n")
        click.echo(f"ADMIN_PASSWORD_HASH={generate_password_hash(pwd)}\n")
        click.echo("После этого перезапустите сайт: systemctl restart zametki")

    @app.cli.command("setup-2fa")
    def setup_2fa():
        """Создать секрет для приложения-аутентификатора и резервные коды."""
        from werkzeug.security import generate_password_hash

        from .auth import new_backup_codes, new_secret, provisioning_uri

        secret = new_secret()
        uri = provisioning_uri(secret, label=app.config["SITE_TITLE"], issuer=app.config["SITE_TITLE"])
        codes = new_backup_codes()

        click.echo("\n1) Отсканируйте QR-код в приложении (Google Authenticator, Aegis, 2FAS):\n")
        try:
            import qrcode

            qr = qrcode.QRCode(border=1)
            qr.add_data(uri)
            qr.print_ascii(invert=True)
        except ImportError:
            click.echo("   (для QR-кода: pip install qrcode — или добавьте ключ вручную)")
        click.echo(f"\n   Ключ для ручного ввода: {secret}")
        click.echo(f"   Ссылка: {uri}")

        click.echo("\n2) Сохраните резервные коды — каждый работает один раз:\n")
        for c in codes:
            click.echo(f"   {c}")

        click.echo("\n3) Вставьте в .env:\n")
        click.echo(f"ADMIN_TOTP_SECRET={secret}")
        click.echo("ADMIN_BACKUP_CODE_HASHES=" + "|".join(generate_password_hash(c) for c in codes))
        click.echo("\nПосле этого перезапустите сайт: systemctl restart zametki")

    @app.cli.command("db-upgrade")
    def db_upgrade():
        """Привести схему базы к последней версии (обычно делается сама при запуске)."""
        from . import migrations
        from .db import connect

        path = app.config["DATABASE"]
        conn = connect(path)
        before = migrations.current_version(conn)
        applied = migrations.upgrade(conn, log=click.echo)
        after = migrations.current_version(conn)
        conn.close()
        click.echo(f"База {path}: версия {before} → {after}" + (", изменений нет" if not applied else ""))

    @app.cli.command("rebuild")
    def rebuild():
        """Пересобрать HTML, оглавления и поисковый индекс всех статей (после смены рендера)."""
        db = get_db()
        rows = db.execute("SELECT * FROM articles").fetchall()
        for r in rows:
            tags = [t["name"] for t in models.get_article(r["slug"], include_drafts=True)["tags"]]
            models.save_article(r["title"], r["body_md"], tags, r["published_at"], r["status"], r["slug"], r["id"])
        click.echo(f"Пересобрано статей: {len(rows)}")
