"""Обработка markdown: HTML, оглавление, отрывок, время чтения, slug."""
import html
import json
import re

from markdown_it import MarkdownIt
from markupsafe import Markup

TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}

MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]

EXCERPT_LEN = 170
WORDS_PER_MINUTE = 180

# Привычные написания → имена языков highlight.js
LANG_ALIASES = {
    "sh": "bash", "shell": "bash", "zsh": "bash", "console": "bash", "terminal": "bash",
    "py": "python", "js": "javascript", "ts": "typescript", "yml": "yaml",
    "conf": "ini", "cfg": "ini", "docker": "dockerfile", "html": "xml", "text": "plaintext",
}


def slugify(text, fallback="post"):
    out = []
    for ch in str(text or "").lower().strip():
        if ch in TRANSLIT:
            out.append(TRANSLIT[ch])
        elif re.match(r"[a-z0-9]", ch):
            out.append(ch)
        else:
            out.append("-")
    s = re.sub(r"-+", "-", "".join(out)).strip("-")
    return s or fallback


def plural(n, one, few, many):
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 10 <= n % 100 < 20:
        return few
    return many


def ru_date(iso):
    try:
        y, m, d = str(iso)[:10].split("-")
        return f"{int(d)} {MONTHS[int(m) - 1]} {y}"
    except (ValueError, IndexError):
        return iso or ""


def _md():
    md = MarkdownIt("commonmark", {"html": True, "typographer": False})
    md.enable(["table", "strikethrough"])

    def fence(_renderer, tokens, idx, options, env):
        tok = tokens[idx]
        lang = (tok.info or "").strip().split()[0].lower() if tok.info else ""
        lang = lang if re.fullmatch(r"[a-z0-9#+.-]{1,20}", lang or "") else ""
        lang = LANG_ALIASES.get(lang, lang)
        # Без явного языка код остаётся обычным моноширинным текстом:
        # угадывание на коротких фрагментах чаще врёт, чем помогает.
        label = f'<span class="code-lang">{html.escape(lang)}</span>' if lang else ""
        cls = f' class="language-{html.escape(lang)}"' if lang else ""
        return (
            "<pre>" + label +
            '<button type="button" class="code-copy" aria-label="Скопировать код">Copy</button>'
            f"<code{cls}>{html.escape(tok.content)}</code></pre>\n"
        )

    md.add_render_rule("fence", fence)
    md.add_render_rule("code_block", fence)
    return md


_MD = _md()


def render_markdown(text):
    """Возвращает (html, toc), где toc — список {id, text, level} для h2/h3."""
    tokens = _MD.parse(text or "")
    toc, used = [], {}
    for i, tok in enumerate(tokens):
        if tok.type != "heading_open":
            continue
        title = tokens[i + 1].content if i + 1 < len(tokens) else ""
        plain = re.sub(r"[`*_~]", "", title)
        base = slugify(plain, "section")
        n = used.get(base, 0)
        used[base] = n + 1
        hid = f"{base}-{n}" if n else base
        tok.attrSet("id", hid)
        level = int(tok.tag[1])
        if level in (2, 3):
            toc.append({"id": hid, "text": plain, "level": level})
    out = _MD.renderer.render(tokens, _MD.options, {})
    out = out.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    return out, toc


def plain_text(body_html):
    s = re.sub(r"<pre>.*?</pre>", " ", body_html, flags=re.S)
    s = re.sub(r"</?(p|h\d|li|ul|ol|td|th|tr|blockquote|div|table|br|hr)\b[^>]*>", " ", s)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def paragraphs_text(body_html):
    """Текст только из абзацев — для отрывка (без заголовков, таблиц и кода)."""
    return " ".join(plain_text(p) for p in re.findall(r"<p>(.*?)</p>", body_html, flags=re.S))


def excerpt(text, length=EXCERPT_LEN):
    if len(text) <= length:
        return text
    return re.sub(r"\s+\S*$", "", text[:length]) + "…"


def reading_minutes(text):
    return max(1, round(len(text.split()) / WORDS_PER_MINUTE))


def mark_to_html(text):
    """Экранирует текст и превращает служебные метки FTS5 в <mark>."""
    out = html.escape(text or "").replace("\x02", "<mark>").replace("\x03", "</mark>")
    return Markup(out)


def highlight_words(text, words):
    """Выделяет в тексте слова запроса (совпадение по началу слова, как в поиске)."""
    escaped = html.escape(text or "")
    for w in sorted(set(words), key=len, reverse=True)[:12]:
        if len(w) < 2:
            continue
        escaped = re.sub(rf"(?<![\w>]){re.escape(html.escape(w))}\w*", r"<mark>\g<0></mark>", escaped, flags=re.I)
    return Markup(escaped)


def build(body_md):
    """Всё, что вычисляется из markdown при сохранении статьи."""
    body_html, toc = render_markdown(body_md)
    text = plain_text(body_html)
    return {
        "body_html": body_html,
        "toc_json": json.dumps(toc, ensure_ascii=False),
        "plain_text": text,
        "excerpt": excerpt(paragraphs_text(body_html) or text),
        "reading_minutes": reading_minutes(text),
    }
