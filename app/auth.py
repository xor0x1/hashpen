"""Вход автора: пароль + одноразовый код (TOTP) или резервный код."""
import base64
import hashlib
import hmac
import secrets
import struct
import time

from flask import (Blueprint, abort, current_app, flash, redirect, render_template, request, session, url_for)
from werkzeug.security import check_password_hash

from .db import get_db

bp = Blueprint("auth", __name__)

STEP = 30              # период TOTP, секунд
WINDOW = 1             # допуск ±1 шаг (расхождение часов)
PENDING_TTL = 300      # 5 минут между вводом пароля и кода
MAX_FAILS = 7          # попыток
FAIL_WINDOW = 900      # за 15 минут


# ---------- TOTP ----------

def totp_at(secret_b32, counter, digits=6):
    pad = "=" * (-len(secret_b32) % 8)
    key = base64.b32decode(secret_b32.upper().replace(" ", "") + pad)
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    code = struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF
    return str(code % 10 ** digits).zfill(digits)


def verify_totp(secret, code):
    """Возвращает счётчик подошедшего кода или None."""
    now = int(time.time()) // STEP
    for c in range(now - WINDOW, now + WINDOW + 1):
        if hmac.compare_digest(totp_at(secret, c), code):
            return c
    return None


def provisioning_uri(secret, label, issuer):
    from urllib.parse import quote
    return (f"otpauth://totp/{quote(issuer)}:{quote(label)}?secret={secret}"
            f"&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period={STEP}")


def new_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def new_backup_codes(count=8):
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    codes = []
    for _ in range(count):
        raw = "".join(secrets.choice(alphabet) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    return codes


# ---------- состояние в базе ----------

def _state_get(key):
    row = get_db().execute("SELECT value FROM auth_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _state_set(key, value):
    db = get_db()
    db.execute("INSERT INTO auth_state (key, value) VALUES (?, ?) "
               "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
    db.commit()


def _client_ip():
    return request.remote_addr or "?"


def _fails():
    db = get_db()
    db.execute("DELETE FROM login_attempts WHERE ts < ?", (int(time.time()) - FAIL_WINDOW,))
    db.commit()
    return db.execute("SELECT COUNT(*) FROM login_attempts WHERE ip = ?", (_client_ip(),)).fetchone()[0]


def _fail():
    db = get_db()
    db.execute("INSERT INTO login_attempts (ip, ts) VALUES (?, ?)", (_client_ip(), int(time.time())))
    db.commit()


def _clear_fails():
    db = get_db()
    db.execute("DELETE FROM login_attempts WHERE ip = ?", (_client_ip(),))
    db.commit()


# ---------- вход ----------

def is_configured():
    c = current_app.config
    return bool(c["ADMIN_PASSWORD_HASH"] and c["ADMIN_TOTP_SECRET"])


def is_admin():
    return bool(session.get("admin"))


def login_required(view):
    from functools import wraps

    @wraps(view)
    def wrapped(*a, **kw):
        if not is_admin():
            return redirect(url_for("auth.login", next=request.path))
        return view(*a, **kw)

    return wrapped


@bp.route("/login", methods=("GET", "POST"))
def login():
    if is_admin():
        return redirect(url_for("blog.index"))
    if not is_configured():
        return render_template("login.html", not_configured=True), 503
    if _fails() >= MAX_FAILS:
        return render_template("login.html", blocked=True), 429

    if request.method == "POST":
        password = request.form.get("password", "")
        if check_password_hash(current_app.config["ADMIN_PASSWORD_HASH"], password):
            session.clear()
            session["pending"] = int(time.time())
            return redirect(url_for("auth.two_factor", next=request.args.get("next", "")))
        _fail()
        flash("Неверный пароль.", "error")
    return render_template("login.html")


@bp.route("/login/2fa", methods=("GET", "POST"))
def two_factor():
    pending = session.get("pending")
    if not pending or time.time() - pending > PENDING_TTL:
        session.pop("pending", None)
        return redirect(url_for("auth.login"))
    if _fails() >= MAX_FAILS:
        return render_template("login.html", blocked=True), 429

    if request.method == "POST":
        code = request.form.get("code", "").strip().replace(" ", "").lower()
        if _check_code(code):
            session.clear()
            session["admin"] = True
            session.permanent = True
            _clear_fails()
            nxt = request.args.get("next", "")
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("blog.index"))
        _fail()
        flash("Код не подошёл.", "error")
    return render_template("login_2fa.html")


def _check_code(code):
    secret = current_app.config["ADMIN_TOTP_SECRET"]
    if code.isdigit() and len(code) == 6:
        counter = verify_totp(secret, code)
        if counter is None:
            return False
        last = int(_state_get("totp_last_counter") or 0)
        if counter <= last:          # этот код уже использован
            return False
        _state_set("totp_last_counter", counter)
        return True

    # резервный код
    db = get_db()
    for h in current_app.config["ADMIN_BACKUP_CODE_HASHES"]:
        if not check_password_hash(h, code):
            continue
        if db.execute("SELECT 1 FROM used_backup_codes WHERE hash = ?", (h,)).fetchone():
            return False
        db.execute("INSERT INTO used_backup_codes (hash, used_at) VALUES (?, datetime('now'))", (h,))
        db.commit()
        return True
    return False


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("blog.index"))


# ---------- CSRF ----------

def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def check_csrf():
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return None
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
    if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
        abort(400, "Некорректный CSRF-токен. Обновите страницу и попробуйте ещё раз.")
    return None


def init_app(app):
    app.register_blueprint(bp)
    app.before_request(check_csrf)
    app.jinja_env.globals["csrf_token"] = csrf_token
