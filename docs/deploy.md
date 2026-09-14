# Установка на сервер (Ubuntu)

> Проще всего выполнить `sudo bash install.sh` из папки проекта — скрипт делает всё, что описано ниже,
> и заодно закрывает частые ошибки с правами. Этот документ нужен, если хочется поставить руками
> или разобраться, что именно происходит.

Ниже `example.ru` замените на свой домен, `1.2.3.4` — на IP сервера.
Всё, кроме шага 7 (HTTPS), работает и без домена — сайт откроется по IP.

## 1. Загрузить файлы

С вашего компьютера, в PowerShell:

```powershell
cd C:\путь\к\проекту
scp -r blog root@1.2.3.4:/srv/hashpen
```

Либо через WinSCP: скопировать папку `blog` в `/srv/hashpen` на сервере.

## 2. Подготовить сервер

```bash
apt update && apt install -y python3-venv python3-pip nginx sqlite3
adduser --system --group --home /srv/hashpen --disabled-login hashpen
chown -R hashpen:hashpen /srv/hashpen
```

## 3. Окружение Python

```bash
cd /srv/hashpen
sudo -u hashpen python3 -m venv .venv
sudo -u hashpen .venv/bin/pip install -r requirements.txt
```

## 4. Настройки

```bash
sudo -u hashpen cp .env.example .env
sudo -u hashpen .venv/bin/python -c "import secrets; print(secrets.token_hex(32))"
sudo -u hashpen nano .env
```

В `.env`:

```
SECRET_KEY=<строка из команды выше>
SITE_URL=https://example.ru
SESSION_COOKIE_SECURE=1
YANDEX_METRIKA_ID=
```

Загрузить пачку готовых статей в markdown:

```bash
cd /srv/hashpen
sudo -u hashpen .venv/bin/flask --app wsgi import-md ./articles
```

## 5. Сервис gunicorn

```bash
cat > /etc/systemd/system/hashpen.service <<'EOF'
[Unit]
Description=Zametki blog (gunicorn)
After=network.target

[Service]
User=hashpen
Group=hashpen
WorkingDirectory=/srv/hashpen
Environment=PYTHONUNBUFFERED=1
RuntimeDirectory=hashpen
ExecStart=/srv/hashpen/.venv/bin/gunicorn --workers 3 --bind unix:/run/hashpen/gunicorn.sock wsgi:app
Restart=always
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now hashpen
systemctl status hashpen --no-pager
```

## 6. nginx

```bash
cat > /etc/nginx/sites-available/hashpen <<'EOF'
server {
    listen 80;
    server_name example.ru www.example.ru;

    client_max_body_size 10m;   # для загрузки картинок

    location /static/ {
        alias /srv/hashpen/app/static/;
        expires 7d;
        access_log off;
    }

    location / {
        proxy_pass http://unix:/run/hashpen/gunicorn.sock;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF

ln -sf /etc/nginx/sites-available/hashpen /etc/nginx/sites-enabled/hashpen
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
```

Firewall:

```bash
ufw allow OpenSSH && ufw allow 'Nginx Full' && ufw enable
```

Проверка: `http://1.2.3.4` или `http://example.ru`.

## 7. HTTPS (нужен домен, направленный на IP сервера)

```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d example.ru -d www.example.ru
```

Certbot сам продлит сертификат. Пока HTTPS нет, поставьте в `.env`
`SESSION_COOKIE_SECURE=0`, иначе вход автора не будет работать по http.

## 8. Бэкап базы

```bash
mkdir -p /srv/backups && chown hashpen:hashpen /srv/backups
cat > /etc/cron.daily/hashpen-backup <<'EOF'
#!/bin/sh
d=$(date +%F)
sqlite3 /srv/hashpen/instance/blog.db ".backup '/srv/backups/blog-$d.db'"
find /srv/backups -name 'blog-*.db' -mtime +14 -delete
EOF
chmod +x /etc/cron.daily/hashpen-backup
```

## Обновление сайта

После правок кода — залить файлы заново и перезапустить:

```bash
scp -r blog/app blog/wsgi.py root@1.2.3.4:/srv/hashpen/   # с компьютера
ssh root@1.2.3.4 "chown -R hashpen:hashpen /srv/hashpen && systemctl restart hashpen"
```

Папку `instance` (база) и файл `.env` не перезаписывать.

Если менялся рендер markdown:

```bash
cd /srv/hashpen && sudo -u hashpen .venv/bin/flask --app wsgi rebuild
```

## Полезное

```bash
journalctl -u hashpen -f          # логи приложения
tail -f /var/log/nginx/error.log  # логи nginx
systemctl restart hashpen         # перезапуск после изменений
```

## Настройка входа автора

После обновления кода перезапустите службу — недостающие таблицы в базе создадутся сами:

```bash
systemctl restart hashpen
```

Затем задайте пароль и второй фактор:

```bash
cd /srv/hashpen
sudo -u hashpen .venv/bin/pip install qrcode          # необязательно, для QR-кода в терминале
sudo -u hashpen .venv/bin/flask --app wsgi set-password
sudo -u hashpen .venv/bin/flask --app wsgi setup-2fa
```

Обе команды печатают строки для `.env` — впишите их:

```bash
sudo -u hashpen nano /srv/hashpen/.env
systemctl restart hashpen
```

Резервные коды сохраните отдельно от телефона: по ним можно войти, если аутентификатор потерян.

Вход: `https://example.ru/login`. **Важно:** пока сайт работает по http, в `.env` должно быть
`SESSION_COOKIE_SECURE=0`, иначе браузер не сохранит cookie сессии и вход не сработает.
После выпуска сертификата верните `1` и перезапустите службу.

Если забыли пароль — просто выполните `set-password` заново и замените строку в `.env`.

## Картинки в статьях

Загруженные файлы лежат в `/srv/hashpen/instance/uploads`. Flask умеет отдавать их сам,
но лучше поручить это nginx — добавьте в блок `server` перед `location /`:

```nginx
    location /uploads/ {
        alias /srv/hashpen/instance/uploads/;
        expires 30d;
        access_log off;
    }
```

Затем `nginx -t && systemctl reload nginx`. Права, если nginx отдаёт 403:

```bash
chmod o+x /srv/hashpen/instance && chmod -R o+rX /srv/hashpen/instance/uploads
```

Размер загружаемого файла ограничен с двух сторон: `client_max_body_size 10m` в nginx
и `MAX_UPLOAD_MB=10` в `.env`. Меняйте оба вместе.

Бэкап картинок (база копируется отдельно, см. выше):

```bash
tar czf /srv/backups/uploads-$(date +%F).tgz -C /srv/hashpen/instance uploads
```

## Отдельные страницы

Новая таблица создаётся сама при запуске, миграций руками не нужно:

```bash
systemctl restart hashpen
```

Страницы появятся по адресам вроде `https://example.ru/about`. Управление — ссылка «Страницы сайта»
в сайдбаре после входа. Ничего в nginx менять не нужно.

## Обновление работающего сайта (настройки и версии базы)

Новая версия добавляет таблицу настроек. Порядок обычный:

```bash
# с компьютера — всю папку app целиком
scp -r app install.sh root@СЕРВЕР:/srv/hashpen/

# на сервере
chown -R hashpen:hashpen /srv/hashpen
systemctl restart hashpen
```

Схема обновится сама при запуске (`PRAGMA user_version`), данные не трогаются.
Проверить версию и накатить вручную:

```bash
cd /srv/hashpen && sudo -u hashpen .venv/bin/flask --app wsgi db-upgrade
```

Перед обновлением всё же сделайте копию — минутное дело:

```bash
sqlite3 /srv/hashpen/instance/blog.db ".backup '/srv/backups/before-update.db'"
```

После перезапуска название, описание, цвета и Метрика правятся на самом сайте: «Настройки сайта» в меню слева.
Значения из `.env` продолжают работать как значения по умолчанию, пока настройка ни разу не сохранена.
