import os
from pathlib import Path

from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, render_template
from werkzeug.middleware.proxy_fix import ProxyFix

from . import admin, auth, content, db, models
from . import settings as site_settings

BASE_DIR = Path(__file__).resolve().parent.parent


def create_app(test_config=None):
    load_dotenv(BASE_DIR / ".env")
    app = Flask(__name__, instance_path=str(BASE_DIR / "instance"))
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        DATABASE=os.environ.get("DATABASE", str(BASE_DIR / "instance" / "blog.db")),
        SITE_TITLE=os.environ.get("SITE_TITLE", "Заметки"),
        SITE_TAGLINE=os.environ.get("SITE_TAGLINE", "личный блог об IT"),
        SITE_DESCRIPTION=os.environ.get(
            "SITE_DESCRIPTION", "Личный блог об IT: статьи, заметки и разборы, опубликованные в markdown."
        ),
        SITE_URL=os.environ.get("SITE_URL", "").rstrip("/"),
        METRIKA_ID=os.environ.get("YANDEX_METRIKA_ID", "").strip(),
        CONTACT_EMAIL=os.environ.get("CONTACT_EMAIL", ""),
        PER_PAGE=20,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "1") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
        ADMIN_PASSWORD_HASH=os.environ.get("ADMIN_PASSWORD_HASH", "").strip(),
        ADMIN_TOTP_SECRET=os.environ.get("ADMIN_TOTP_SECRET", "").strip(),
        ADMIN_BACKUP_CODE_HASHES=[h for h in os.environ.get("ADMIN_BACKUP_CODE_HASHES", "").split("|") if h.strip()],
        UPLOAD_DIR=os.environ.get("UPLOAD_DIR", str(BASE_DIR / "instance" / "uploads")),
        MAX_CONTENT_LENGTH=int(os.environ.get("MAX_UPLOAD_MB", "10")) * 1024 * 1024,
    )
    # за nginx: настоящий IP клиента и протокол
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    if test_config:
        app.config.update(test_config)

    db.init_db(app.config["DATABASE"])
    app.teardown_appcontext(db.close_db)

    app.jinja_env.filters["ru_date"] = content.ru_date
    app.jinja_env.filters["reading"] = lambda n: f"{n} {content.plural(n, 'минута', 'минуты', 'минут')} чтения"

    @app.context_processor
    def sidebar_context():
        admin = auth.is_admin()
        return {
            "sidebar_tags": models.tag_counts(include_drafts=admin),
            "total_articles": models.count_articles(include_drafts=admin),
            "sidebar_pages": models.list_pages(include_drafts=admin, sidebar_only=True),
            "footer_pages": [p for p in models.list_pages(include_drafts=admin) if not p["in_sidebar"]],
            "is_admin": admin,
            "site": site_settings.context(),
        }

    from .views import bp
    app.register_blueprint(bp)
    auth.init_app(app)
    admin.init_app(app)
    Path(app.config["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)

    from .cli import register
    register(app)

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("404.html"), 404

    return app
