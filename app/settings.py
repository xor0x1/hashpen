"""Настройки сайта: то, что правится в админке, а не в коде.

Значение берётся из базы; если его там нет — из `.env` (config), если и там нет — из DEFAULTS.
"""
import re

from flask import current_app, g
from markupsafe import Markup

from .db import get_db

# ключ → (значение по умолчанию, имя переменной в .env или None)
FIELDS = {
    "title": ("Заметки", "SITE_TITLE"),
    "tagline": ("личный блог об IT", "SITE_TAGLINE"),
    "description": ("Личный блог об IT: статьи, заметки и разборы, опубликованные в markdown.", "SITE_DESCRIPTION"),
    "contact_email": ("", "CONTACT_EMAIL"),
    "metrika_id": ("", "METRIKA_ID"),
    "accent_dark": ("#2fe08a", None),
    "accent_light": ("#15915f", None),
    "default_theme": ("dark", None),
    "custom_css": ("", None),
}

COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _rows():
    return {r["key"]: r["value"] for r in get_db().execute("SELECT key, value FROM settings").fetchall()}


def all_settings():
    """Все настройки одним словарём, с кэшем на время запроса."""
    if "settings" not in g:
        try:
            saved = _rows()
        except Exception:  # noqa: BLE001 — таблицы ещё нет (первый запуск до миграции)
            saved = {}
        data = {}
        for key, (default, env_key) in FIELDS.items():
            if key in saved:
                data[key] = saved[key]
            elif env_key and current_app.config.get(env_key):
                data[key] = current_app.config[env_key]
            else:
                data[key] = default
        g.settings = data
    return g.settings


def get(key):
    return all_settings().get(key, "")


def save(values):
    """Сохраняет только известные ключи. Возвращает список ошибок."""
    errors = []
    clean = {}
    for key, value in values.items():
        if key not in FIELDS:
            continue
        value = (value or "").strip()
        if key in ("accent_dark", "accent_light"):
            if not COLOR_RE.match(value):
                errors.append(f"Цвет «{value}» записан неверно: нужен формат #2fe08a.")
                continue
        if key == "default_theme" and value not in ("dark", "light"):
            value = "dark"
        if key == "metrika_id" and value and not value.isdigit():
            errors.append("Номер Яндекс.Метрики — это только цифры.")
            continue
        if key == "custom_css":
            value = value.replace("</", "<\\/")  # чтобы стили не могли закрыть тег <style>
            if len(value) > 20000:
                errors.append("CSS слишком длинный: ограничение 20 000 символов.")
                continue
        clean[key] = value

    if errors:
        return errors

    db = get_db()
    for key, value in clean.items():
        db.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')",
            (key, value),
        )
    db.commit()
    g.pop("settings", None)
    return []


def reset(key):
    db = get_db()
    db.execute("DELETE FROM settings WHERE key = ?", (key,))
    db.commit()
    g.pop("settings", None)


# ---------- цвета ----------

def _hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, int(c))):02x}" for c in rgb)


def shade(color, amount):
    """amount > 0 — светлее, < 0 — темнее (доля от 0 до 1)."""
    r, g_, b = _hex_to_rgb(color)
    if amount >= 0:
        return _rgb_to_hex((r + (255 - r) * amount, g_ + (255 - g_) * amount, b + (255 - b) * amount))
    return _rgb_to_hex((r * (1 + amount), g_ * (1 + amount), b * (1 + amount)))


def mix(color, other, ratio):
    """Смешивает цвет с другим: ratio — доля первого."""
    a, b = _hex_to_rgb(color), _hex_to_rgb(other)
    return _rgb_to_hex(tuple(a[i] * ratio + b[i] * (1 - ratio) for i in range(3)))


def theme_css():
    """Переопределение акцентов под выбранные цвета — вставляется после style.css."""
    dark, light = get("accent_dark"), get("accent_light")
    if not COLOR_RE.match(dark or ""):
        dark = FIELDS["accent_dark"][0]
    if not COLOR_RE.match(light or ""):
        light = FIELDS["accent_light"][0]
    return (
        ":root{"
        f"--accent:{dark};--accent-strong:{shade(dark, 0.18)};--focus:{dark};"
        f"--accent-soft:{mix(dark, '#0d1210', 0.16)};--accent-contrast:{shade(dark, -0.82)};"
        f"--hl-string:{dark};"
        "}"
        ':root[data-theme="light"]{'
        f"--accent:{light};--accent-strong:{shade(light, -0.18)};--focus:{light};"
        f"--accent-soft:{mix(light, '#ffffff', 0.14)};--accent-contrast:#ffffff;"
        f"--hl-string:{shade(light, -0.18)};"
        "}"
    )


def context():
    """Словарь `site` для шаблонов."""
    data = dict(all_settings())
    # CSS вставляется в <style> как есть: иначе Jinja экранирует кавычки
    # и селекторы вида [data-theme="light"] перестают работать.
    # Последовательность "</" вырезана при сохранении, закрыть тег стилями нельзя.
    data["theme_css"] = Markup(theme_css())
    data["custom_css"] = Markup(data.get("custom_css", ""))
    return data
