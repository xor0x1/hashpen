# hashpen

**English** · [Русский](README.md)

A personal blog engine: Flask, SQLite, articles in markdown. No plugin system, no admin panel with five hundred switches, no database server — one Python process and one file on disk.

Built for my own blog, [worldnotes.ru](https://worldnotes.ru), and running there. The whole thing is about 1,500 lines you can read in an evening.

The name comes from the two things it is built around: the hash that starts a markdown heading (`## Section`) and a pen.

![Article feed](screenshots/01-lenta.png)

## What it does

- **Markdown articles** — rendered on the server at save time, along with the table of contents, reading time and list excerpt.
- **Syntax highlighting** — highlight.js, a Copy button and a language label in the corner of each block. A block with no language stays plain monospace: auto-detection is deliberately off, because on short snippets it guesses wrong more often than right.
- **Full-text search** — SQLite FTS5. Results show a snippet around the match, with the matched words highlighted in both the text and the title.
- **Tags** with filtering from the sidebar.
- **Standalone pages** such as "About" at short URLs like `/about`, each with a switch for whether it appears in the menu.
- **Drafts** — visible to the author only, marked with a badge in the feed.
- **Images** — drag a file into the editor, paste it from the clipboard, or pick it with a button. The file type is verified by its contents, not its extension.
- **Two-factor login** — password plus a code from an authenticator app, backup codes, rate limiting, CSRF protection.
- **Settings in the admin UI** — title, description, accent color, default theme, analytics ID and a custom CSS field.
- **Dark and light themes**, a mobile sidebar, RSS, `sitemap.xml` and Open Graph tags for link previews.
- **Cookie consent banner** — the analytics counter loads only after the visitor agrees.

## Screenshots

| Article | Search |
|---|---|
| ![Article](screenshots/02-statya.png) | ![Search](screenshots/03-poisk.png) |

| Editor | Settings |
|---|---|
| ![Editor](screenshots/04-redaktor.png) | ![Settings](screenshots/05-nastroyki.png) |

The interface is in Russian. Swapping it for another language means editing the templates in `app/templates` — there is no translation layer, and adding one is on the list.

## Quick start

Python 3.10 or newer.

```bash
git clone https://github.com/xor0x1/hashpen.git
cd hashpen
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # set your own SECRET_KEY and SESSION_COOKIE_SECURE=0 for local use
flask --app wsgi run
```

The site comes up on http://127.0.0.1:5000 and creates its database on first run.

To get into the admin UI, set a password and a second factor:

```bash
python setup-auth.py          # writes everything into .env and prints a QR code
```

## Deploying

On a fresh Ubuntu box, one command from the project directory:

```bash
sudo bash install.sh
```

The script asks for a domain, a site name and a service name, then does the rest: packages, a system user, a virtualenv, an `.env` with a random `SECRET_KEY`, the database, a systemd unit, an nginx config that serves static files and uploads directly, and a daily backup job. It finishes by printing the two remaining steps — the login setup and the TLS certificate.

Running it again is safe: `.env` and the database are never overwritten.

## Importing content

Articles are normally written in the browser, but a batch of existing files can be imported:

```bash
flask --app wsgi import-md ./articles     # every .md in the folder
```

Front matter is optional — see [examples/primer-stati.md](examples/primer-stati.md). Without it, the title comes from the first `# heading` or the file name, and the date from the file's modification time.

## How it is built

```
app/
  __init__.py   app factory and configuration
  content.py    markdown → HTML, table of contents, excerpt, reading time
  models.py     articles, pages, tags, search
  settings.py   site settings stored in the database
  auth.py       login, TOTP, CSRF, brute-force protection
  admin.py      editor and image uploads
  views.py      public pages, RSS, sitemap
  migrations.py database schema versions
  cli.py        import and maintenance commands
```

Four dependencies: Flask, markdown-it-py, python-dotenv, PyYAML — plus gunicorn in production. No ORM, no frontend build step, no Node.

The schema is versioned with `PRAGMA user_version`: the app brings the database up to date on startup, or you can run `flask --app wsgi db-upgrade` yourself. To change the schema, append a numbered step to `MIGRATIONS` in `app/migrations.py`.

## What it deliberately does not have

Multiple users and roles, plugins, a WYSIWYG editor, comments, i18n, switchable themes, caching. This is an engine for one author who writes in markdown. If you need a site with a shop and contact forms, use WordPress — that is the honest answer.

## Documentation

Both documents are currently in Russian:

- [docs/manual.md](docs/manual.md) — every feature in detail.
- [docs/deploy.md](docs/deploy.md) — manual server setup, for when you want to know what `install.sh` actually does.

## License

MIT — see [LICENSE](LICENSE). Use it, change it, run it on commercial sites. No warranty of any kind.
