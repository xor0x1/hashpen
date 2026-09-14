#!/usr/bin/env bash
# Установка блога на чистую Ubuntu. Запускать от root из папки с проектом:
#     sudo bash install.sh
# Скрипт можно запускать повторно: он не трогает существующие .env и базу.
set -Eeuo pipefail

die() { echo -e "\n[ОШИБКА] $*" >&2; exit 1; }
step() { echo -e "\n=== $* ==="; }

[[ $EUID -eq 0 ]] || die "Запустите от root: sudo bash install.sh"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$SRC/wsgi.py" && -d "$SRC/app" ]] || die "Запускайте скрипт из папки проекта (рядом должны быть wsgi.py и app/)."

# ---------- вопросы ----------

read -rp "Домен сайта (например blog.example.ru, можно пусто — тогда только по IP): " DOMAIN
read -rp "Название сайта [Заметки]: " SITE_TITLE
read -rp "Имя службы и системного пользователя [hashpen]: " SERVICE
read -rp "Куда установить [/srv/${SERVICE:-hashpen}]: " TARGET

SITE_TITLE="${SITE_TITLE:-Заметки}"
SERVICE="${SERVICE:-hashpen}"
TARGET="${TARGET:-/srv/$SERVICE}"
[[ "$SERVICE" =~ ^[a-z][a-z0-9_-]*$ ]] || die "Имя службы: латиница, цифры, дефис."

echo
echo "  Домен:    ${DOMAIN:-（только по IP）}"
echo "  Название: $SITE_TITLE"
echo "  Служба:   $SERVICE"
echo "  Папка:    $TARGET"
read -rp "Всё верно? [y/N] " OK
[[ "$OK" =~ ^[yYдД]$ ]] || die "Отменено."

# ---------- пакеты ----------

step "Пакеты"
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip nginx sqlite3 >/dev/null
echo "python3, nginx, sqlite3 на месте"

# ---------- пользователь и файлы ----------

step "Пользователь и файлы"
id -u "$SERVICE" &>/dev/null || adduser --system --group --home "$TARGET" --disabled-login "$SERVICE" >/dev/null
mkdir -p "$TARGET"

if [[ "$SRC" != "$TARGET" ]]; then
    # .env и instance не перезаписываем: там ключи и база
    rsync -a --exclude .env --exclude instance --exclude .venv --exclude __pycache__ \
          "$SRC"/ "$TARGET"/ 2>/dev/null || {
        cp -r "$SRC"/app "$SRC"/wsgi.py "$SRC"/requirements.txt "$TARGET"/
        [[ -f "$SRC/setup-auth.py" ]] && cp "$SRC"/setup-auth.py "$TARGET"/
    }
fi

chown -R "$SERVICE:$SERVICE" "$TARGET"
chmod 751 "$TARGET"            # чтобы nginx мог зайти внутрь за статикой
echo "файлы в $TARGET"

# ---------- окружение python ----------

step "Окружение Python"
[[ -d "$TARGET/.venv" ]] || sudo -u "$SERVICE" python3 -m venv "$TARGET/.venv"
sudo -u "$SERVICE" "$TARGET/.venv/bin/pip" install -q --upgrade pip
sudo -u "$SERVICE" "$TARGET/.venv/bin/pip" install -q -r "$TARGET/requirements.txt"
sudo -u "$SERVICE" "$TARGET/.venv/bin/pip" install -q qrcode
echo "зависимости установлены"

# ---------- .env ----------

step "Настройки"
if [[ -f "$TARGET/.env" ]]; then
    echo ".env уже есть, не трогаю"
else
    SECRET="$("$TARGET/.venv/bin/python" -c 'import secrets; print(secrets.token_hex(32))')"
    SITE_URL=""
    [[ -n "$DOMAIN" ]] && SITE_URL="http://$DOMAIN"   # после выпуска сертификата поменяется на https
    cat > "$TARGET/.env" <<ENVEOF
SECRET_KEY=$SECRET
SITE_TITLE=$SITE_TITLE
SITE_URL=$SITE_URL
# 1 — только после выпуска сертификата, иначе вход не будет работать
SESSION_COOKIE_SECURE=0
MAX_UPLOAD_MB=10

# Вход автора: заполнит setup-auth.py
ADMIN_PASSWORD_HASH=
ADMIN_TOTP_SECRET=
ADMIN_BACKUP_CODE_HASHES=
ENVEOF
    chown "$SERVICE:$SERVICE" "$TARGET/.env"
    chmod 600 "$TARGET/.env"
    echo ".env создан, ключ сгенерирован"
fi

# ---------- база ----------

step "База"
sudo -u "$SERVICE" "$TARGET/.venv/bin/flask" --app "$TARGET/wsgi.py" db-upgrade
chmod o+x "$TARGET/instance" 2>/dev/null || true

# ---------- служба ----------

step "Служба systemd"
cat > "/etc/systemd/system/$SERVICE.service" <<UNITEOF
[Unit]
Description=$SITE_TITLE (gunicorn)
After=network.target

[Service]
User=$SERVICE
Group=$SERVICE
WorkingDirectory=$TARGET
Environment=PYTHONUNBUFFERED=1
RuntimeDirectory=$SERVICE
ExecStart=$TARGET/.venv/bin/gunicorn --workers 3 --bind unix:/run/$SERVICE/gunicorn.sock wsgi:app
Restart=always
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
UNITEOF

systemctl daemon-reload
systemctl enable --now "$SERVICE" >/dev/null
sleep 2
systemctl is-active --quiet "$SERVICE" || { journalctl -u "$SERVICE" -n 20 --no-pager; die "Служба не запустилась, смотрите лог выше."; }
echo "служба $SERVICE запущена"

# ---------- nginx ----------

step "nginx"
SERVER_NAME="${DOMAIN:-_}"
[[ -n "$DOMAIN" ]] && SERVER_NAME="$DOMAIN www.$DOMAIN"
cat > "/etc/nginx/sites-available/$SERVICE" <<NGINXEOF
server {
    listen 80;
    listen [::]:80;
    server_name $SERVER_NAME;

    client_max_body_size 10m;

    location /static/ {
        alias $TARGET/app/static/;
        expires 7d;
        access_log off;
    }

    location /uploads/ {
        alias $TARGET/instance/uploads/;
        expires 30d;
        access_log off;
    }

    location / {
        proxy_pass http://unix:/run/$SERVICE/gunicorn.sock;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGINXEOF

ln -sf "/etc/nginx/sites-available/$SERVICE" "/etc/nginx/sites-enabled/$SERVICE"
rm -f /etc/nginx/sites-enabled/default
nginx -t >/dev/null 2>&1 || { nginx -t; die "Конфиг nginx не прошёл проверку."; }
systemctl reload nginx
echo "nginx настроен"

# ---------- бэкапы ----------

step "Ежедневный бэкап"
mkdir -p /srv/backups && chown "$SERVICE:$SERVICE" /srv/backups
cat > "/etc/cron.daily/$SERVICE-backup" <<CRONEOF
#!/bin/sh
d=\$(date +%F)
sqlite3 $TARGET/instance/blog.db ".backup '/srv/backups/$SERVICE-\$d.db'"
tar czf "/srv/backups/$SERVICE-uploads-\$d.tgz" -C $TARGET/instance uploads 2>/dev/null
find /srv/backups -name "$SERVICE-*" -mtime +14 -delete
CRONEOF
chmod +x "/etc/cron.daily/$SERVICE-backup"
"/etc/cron.daily/$SERVICE-backup" && echo "копии складываются в /srv/backups"

# ---------- проверка ----------

step "Проверка"
CODE="$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/ || true)"
[[ "$CODE" == "200" ]] && echo "сайт отвечает: 200" || echo "внимание: локальный запрос вернул $CODE, смотрите journalctl -u $SERVICE"

cat <<FINAL

=== Готово ===

Сайт:   http://${DOMAIN:-<IP сервера>}
Папка:  $TARGET
Служба: systemctl status $SERVICE

Осталось два шага:

1) Вход автора — пароль и код из приложения:

     cd $TARGET && sudo -u $SERVICE .venv/bin/python setup-auth.py
     systemctl restart $SERVICE

2) HTTPS (нужен домен, указывающий на этот сервер):

     apt install -y certbot python3-certbot-nginx
     certbot --nginx -d ${DOMAIN:-example.ru}

   После выпуска сертификата в $TARGET/.env поставьте:
     SITE_URL=https://${DOMAIN:-example.ru}
     SESSION_COOKIE_SECURE=1
   и выполните: systemctl restart $SERVICE

Название, описание, цвета и счётчик Метрики меняются уже на самом сайте:
после входа — «Настройки сайта» в меню слева.
FINAL
