import re
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

from flask import Blueprint, Response, abort, current_app, render_template, render_template_string, request, url_for

from . import auth, content, models, settings as site_settings

bp = Blueprint("blog", __name__)
PAGES_DIR = Path(__file__).parent / "pages"


def _page():
    try:
        return max(1, int(request.args.get("page", 1)))
    except ValueError:
        return 1


def _listing(tag_slug=None):
    per_page = current_app.config["PER_PAGE"]
    page = _page()
    articles, total = models.list_articles(
        tag_slug=tag_slug, include_drafts=auth.is_admin(), limit=per_page, offset=(page - 1) * per_page
    )
    pages = max(1, -(-total // per_page))
    if page > pages:
        abort(404)
    return articles, page, pages


def site_url():
    return current_app.config["SITE_URL"] or request.url_root.rstrip("/")


@bp.get("/")
def index():
    articles, page, pages = _listing()
    return render_template("list.html", articles=articles, page=page, pages=pages)


@bp.get("/tag/<slug>")
def tag(slug):
    t = models.get_tag(slug)
    if not t:
        abort(404)
    articles, page, pages = _listing(slug)
    return render_template("list.html", articles=articles, page=page, pages=pages, active_tag=t)


@bp.get("/search")
def search():
    q = request.args.get("q", "").strip()
    articles = models.search(q, include_drafts=auth.is_admin()) if q else []
    return render_template("list.html", articles=articles, query=q, page=1, pages=1)


@bp.get("/a/<slug>")
def article(slug):
    a = models.get_article(slug, include_drafts=auth.is_admin())
    if not a:
        abort(404)
    return render_template("article.html", a=a, og_image=_og_image(a))


def _og_image(a):
    """Первая картинка статьи — для превью ссылки в мессенджерах; иначе общая."""
    m = re.search(r'<img[^>]+src="([^"]+)"', a["body_html"])
    src = m.group(1) if m else url_for("static", filename="og-image.png")
    return src if src.startswith("http") else site_url() + src


@bp.get("/<slug>")
def page(slug):
    """Отдельная страница вроде «О себе». Правило стоит последним: статические адреса важнее."""
    p = models.get_page(slug, include_drafts=auth.is_admin())
    if not p:
        abort(404)
    return render_template("page.html", title=p["title"], body_html=p["body_html"], page=p)


@bp.get("/privacy")
def privacy():
    md = (PAGES_DIR / "privacy.md").read_text(encoding="utf-8")
    md = render_template_string(md, site_url=site_url(), site=site_settings.context())
    body_html, _ = content.render_markdown(md)
    return render_template("page.html", title="Политика конфиденциальности", body_html=body_html)


@bp.get("/sitemap")
def sitemap_page():
    groups = {}
    for a in models.all_for_sitemap():
        groups.setdefault(a["published_at"][:4], []).append(a)
    return render_template("sitemap.html", groups=groups, pages=models.list_pages())


@bp.get("/sitemap.xml")
def sitemap_xml():
    xml = render_template("sitemap.xml", base=site_url(), articles=models.all_for_sitemap(),
                          pages=models.list_pages())
    return Response(xml, mimetype="application/xml")


@bp.get("/rss.xml")
def rss():
    items = models.latest_full(20)
    for a in items:
        dt = datetime.fromisoformat(a["published_at"]).replace(tzinfo=timezone.utc)
        a["rfc822"] = format_datetime(dt)
    xml = render_template("rss.xml", base=site_url(), items=items, now=format_datetime(datetime.now(timezone.utc)))
    return Response(xml, mimetype="application/rss+xml")


@bp.get("/robots.txt")
def robots():
    body = f"User-agent: *\nDisallow: /login\nDisallow: /admin\n\nSitemap: {site_url()}{url_for('blog.sitemap_xml')}\n"
    return Response(body, mimetype="text/plain")
