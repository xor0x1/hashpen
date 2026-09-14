"""Настройка входа автора: пишет пароль, ключ 2FA и резервные коды прямо в .env.

Запуск на сервере:
    cd /srv/zametki
    sudo -u zametki .venv/bin/python setup-auth.py
"""
import base64
import getpass
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import quote

from werkzeug.security import generate_password_hash

ENV = Path(__file__).resolve().parent / ".env"
KEYS = ("ADMIN_PASSWORD_HASH", "ADMIN_TOTP_SECRET", "ADMIN_BACKUP_CODE_HASHES")
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def ask_password():
    while True:
        p1 = getpass.getpass("Новый пароль (ввод не виден): ")
        if len(p1) < 10:
            print("  Слишком короткий: нужно минимум 10 символов.")
            continue
        if p1 != getpass.getpass("Повторите пароль: "):
            print("  Пароли не совпали, попробуйте ещё раз.")
            continue
        return p1


def main():
    if not ENV.exists():
        sys.exit(f"Не найден файл {ENV}. Сначала скопируйте .env.example в .env.")

    password = ask_password()
    secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    codes = ["".join(secrets.choice(ALPHABET) for _ in range(5)) + "-" +
             "".join(secrets.choice(ALPHABET) for _ in range(5)) for _ in range(8)]

    lines = [ln for ln in ENV.read_text(encoding="utf-8").splitlines()
             if not re.match(r"\s*(%s)\s*=" % "|".join(KEYS), ln)]
    while lines and not lines[-1].strip():
        lines.pop()
    lines += [
        "",
        "# Вход автора (создано setup-auth.py)",
        f"ADMIN_PASSWORD_HASH={generate_password_hash(password)}",
        f"ADMIN_TOTP_SECRET={secret}",
        "ADMIN_BACKUP_CODE_HASHES=" + "|".join(generate_password_hash(c) for c in codes),
    ]
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ENV.chmod(0o600)

    issuer = "Заметки"
    uri = (f"otpauth://totp/{quote(issuer)}:admin?secret={secret}"
           f"&issuer={quote(issuer)}&algorithm=SHA1&digits=6&period=30")

    print(f"\nГотово: {ENV} обновлён.\n")
    print("1) Добавьте сайт в приложение-аутентификатор (Google Authenticator, Aegis, 2FAS).")
    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(uri)
        qr.print_ascii(invert=True)
    except ImportError:
        print("   (QR-код: .venv/bin/pip install qrcode — либо введите ключ вручную)")
    print(f"   Ключ для ручного ввода: {secret}")

    print("\n2) Резервные коды — каждый работает один раз, сохраните их вне телефона:\n")
    for c in codes:
        print(f"   {c}")
    print("\n3) Перезапустите сайт:  systemctl restart zametki")
    print("   Затем закройте это окно терминала — в нём остались ключ и коды.")


if __name__ == "__main__":
    main()
