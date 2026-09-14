"""Редактор статей: создание, правка, удаление, загрузка картинок."""
import secrets
from datetime import date, datetime
from pathlib import Path

from flask import (Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request,
                   send_from_directory, url_for)
from werkzeug.utils import secure_filename

from . import content, models, settings as site_settings
from .auth import login_required

bp = Blueprint("admin", __name__, url_prefix="/admin")
files_bp = Blueprint("files", __name__)

# Подпись файла → расширение. Проверяем содержимое, а не только имя.
SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)


def detect_image(head):
    for sig, ext in SIGNATURES:
        if head.startswith(sig):
            return ext
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    return None


def uploads_dir():
    return Path(current_app.config["UPLOAD_DIR"])


@bp.get("/new")
@login_required
def new():
    a = {"title": "", "body_md": "", "tags": [], "slug": "", "status": models.PUBLISHED,
         "published_at": date.today().isoformat()}
    return render_template("editor.html", a=a, mode="new")


@bp.post("/new")
@login_required
def create():
    form = _read_form()
    if not form:
        a = _form_article()
        return render_template("editor.html", a=a, mode="new"), 400
    slug = models.save_article(**form)
    flash("Статья сохранена.", "ok")
    return redirect(url_for("blog.article", slug=slug))


@bp.get("/a/<slug>/edit")
@login_required
def edit(slug):
    a = models.get_article(slug, include_drafts=True)
    if not a:
        abort(404)
    return render_template("editor.html", a=a, mode="edit")


@bp.post("/a/<slug>/edit")
@login_required
def update(slug):
    a = models.get_article(slug, include_drafts=True)
    if not a:
        abort(404)
    form = _read_form()
    if not form:
        return render_template("editor.html", a=_form_article(a["id"]), mode="edit"), 400
    new_slug = models.save_article(article_id=a["id"], **form)
    flash("Изменения сохранены.", "ok")
    return redirect(url_for("blog.article", slug=new_slug))


@bp.post("/a/<slug>/delete")
@login_required
def delete(slug):
    a = models.get_article(slug, include_drafts=True)
    if not a:
        abort(404)
    models.delete_article(a["id"])
    flash(f"Статья «{a['title']}» удалена.", "ok")
    return redirect(url_for("blog.index"))


@bp.post("/preview")
@login_required
def preview():
    body_html, _ = content.render_markdown(request.form.get("body_md", ""))
    return jsonify(html=body_html)


@bp.post("/upload")
@login_required
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify(error="Файл не выбран."), 400
    head = f.stream.read(32)
    f.stream.seek(0)
    ext = detect_image(head)
    if not ext:
        return jsonify(error="Это не картинка (поддерживаются PNG, JPEG, GIF, WebP)."), 400

    today = datetime.now()
    folder = uploads_dir() / f"{today:%Y/%m}"
    folder.mkdir(parents=True, exist_ok=True)
    # slugify сам транслитерирует кириллицу, secure_filename — страховка от служебных символов
    stem = content.slugify(Path(f.filename).stem[:60], "image")
    name = secure_filename(f"{stem}-{secrets.token_hex(4)}.{ext}")
    f.save(folder / name)

    url = url_for("files.uploaded", name=f"{today:%Y/%m}/{name}")
    return jsonify(url=url, markdown=f"![]({url})")


@files_bp.get("/uploads/<path:name>")
def uploaded(name):
    return send_from_directory(uploads_dir(), name, max_age=60 * 60 * 24 * 30)


# ---------- разбор формы ----------

def _form_article(article_id=None):
    """Данные из формы обратно в шаблон — чтобы при ошибке не потерять текст."""
    return {
        "id": article_id,
        "title": request.form.get("title", ""),
        "body_md": request.form.get("body_md", ""),
        "tags": [{"name": t, "slug": content.slugify(t)} for t in models.parse_tags(request.form.get("tags", ""))],
        "slug": request.form.get("slug", ""),
        "status": models.DRAFT if request.form.get("status") == models.DRAFT else models.PUBLISHED,
        "published_at": request.form.get("published_at", ""),
        "toc": [],
    }


def _read_form():
    title = request.form.get("title", "").strip()
    body_md = request.form.get("body_md", "")
    if not title:
        flash("Добавьте заголовок статьи.", "error")
        return None
    if not body_md.strip():
        flash("Текст статьи пуст.", "error")
        return None
    published_at = request.form.get("published_at", "").strip() or date.today().isoformat()
    try:
        date.fromisoformat(published_at)
    except ValueError:
        flash("Дата должна быть в формате ГГГГ-ММ-ДД.", "error")
        return None
    return {
        "title": title,
        "body_md": body_md,
        "tags": models.parse_tags(request.form.get("tags", "")),
        "published_at": published_at,
        "status": models.DRAFT if request.form.get("status") == models.DRAFT else models.PUBLISHED,
        "slug": request.form.get("slug", "").strip() or title,
    }


def init_app(app):
    app.register_blueprint(bp)
    app.register_blueprint(files_bp)

    @app.errorhandler(413)
    def too_large(_e):
        limit = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        if request.path.startswith("/admin/upload"):
            return jsonify(error=f"Файл больше {limit} МБ."), 413
        return render_template("404.html"), 413


# ---------- отдельные страницы ----------

@bp.get("/pages")
@login_required
def pages():
    return render_template("pages_admin.html", pages=models.list_pages(include_drafts=True))


@bp.get("/pages/new")
@login_required
def new_page():
    p = {"title": "", "body_md": "", "slug": "", "status": models.PUBLISHED, "in_sidebar": 1, "sort_order": 100}
    return render_template("editor.html", a=p, mode="new", kind="page")


@bp.post("/pages/new")
@login_required
def create_page():
    form = _read_page_form()
    if not form:
        return render_template("editor.html", a=_page_form_data(), mode="new", kind="page"), 400
    slug = models.save_page(**form)
    flash("Страница сохранена.", "ok")
    return redirect(url_for("blog.page", slug=slug))


@bp.get("/p/<slug>/edit")
@login_required
def edit_page(slug):
    p = models.get_page(slug, include_drafts=True)
    if not p:
        abort(404)
    return render_template("editor.html", a=p, mode="edit", kind="page")


@bp.post("/p/<slug>/edit")
@login_required
def update_page(slug):
    p = models.get_page(slug, include_drafts=True)
    if not p:
        abort(404)
    form = _read_page_form(exclude_id=p["id"])
    if not form:
        return render_template("editor.html", a=_page_form_data(p["id"]), mode="edit", kind="page"), 400
    new_slug = models.save_page(page_id=p["id"], **form)
    flash("Изменения сохранены.", "ok")
    return redirect(url_for("blog.page", slug=new_slug))


@bp.post("/p/<slug>/delete")
@login_required
def delete_page(slug):
    p = models.get_page(slug, include_drafts=True)
    if not p:
        abort(404)
    models.delete_page(p["id"])
    flash(f"Страница «{p['title']}» удалена.", "ok")
    return redirect(url_for("admin.pages"))


def _page_form_data(page_id=None):
    return {
        "id": page_id,
        "title": request.form.get("title", ""),
        "body_md": request.form.get("body_md", ""),
        "slug": request.form.get("slug", ""),
        "status": models.DRAFT if request.form.get("status") == models.DRAFT else models.PUBLISHED,
        "in_sidebar": 1 if request.form.get("in_sidebar") else 0,
        "sort_order": request.form.get("sort_order", 100),
        "toc": [],
    }


def _read_page_form(exclude_id=None):
    title = request.form.get("title", "").strip()
    body_md = request.form.get("body_md", "")
    if not title:
        flash("Добавьте заголовок страницы.", "error")
        return None
    if not body_md.strip():
        flash("Текст страницы пуст.", "error")
        return None
    slug = content.slugify(request.form.get("slug", "").strip() or title)
    if not models.slug_is_free(slug, exclude_id=exclude_id):
        flash(f"Адрес «/{slug}» занят: так называется служебная страница сайта или другая ваша страница. "
              f"Выберите другой.", "error")
        return None
    try:
        sort_order = int(request.form.get("sort_order") or 100)
    except ValueError:
        sort_order = 100
    return {
        "title": title, "body_md": body_md, "slug": slug,
        "status": models.DRAFT if request.form.get("status") == models.DRAFT else models.PUBLISHED,
        "in_sidebar": bool(request.form.get("in_sidebar")),
        "sort_order": sort_order,
    }


# ---------- настройки сайта ----------

@bp.get("/settings")
@login_required
def settings_page():
    return render_template("settings.html", s=site_settings.all_settings())


@bp.post("/settings")
@login_required
def save_settings():
    values = {key: request.form.get(key, "") for key in site_settings.FIELDS}
    errors = site_settings.save(values)
    for e in errors:
        flash(e, "error")
    if not errors:
        flash("Настройки сохранены.", "ok")
    return redirect(url_for("admin.settings_page"))


@bp.post("/settings/reset-css")
@login_required
def reset_css():
    site_settings.reset("custom_css")
    flash("Свой CSS очищен.", "ok")
    return redirect(url_for("admin.settings_page"))
