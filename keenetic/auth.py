"""Авторизация на роутере Keenetic через challenge-response (MD5 + SHA256)."""

import hashlib
import sys

import keenetic.config as config

from keenetic.session import KeeneticSession


def get_challenge(session: KeeneticSession) -> tuple[str, str]:
    """Получает realm и challenge от роутера (код 401 — норма)."""
    _, headers, status = session.get("/auth", return_headers=True)
    if status != 401:
        print(f"[!] Ожидался код 401, получен {status}")
        sys.exit(1)

    realm = headers.get("X-NDM-Realm")
    challenge = headers.get("X-NDM-Challenge")
    if not realm or not challenge:
        print("[!] Роутер не вернул X-NDM-Realm / X-NDM-Challenge")
        sys.exit(1)
    return realm, challenge


def compute_password_hash(login: str, realm: str, password: str, challenge: str) -> str:
    """MD5(login:realm:password) → SHA256(challenge + md5_part)."""
    md5_part = hashlib.md5(
        f"{login}:{realm}:{password}".encode("utf-8")
    ).hexdigest()

    if config.DEBUG:
        print(f"[DEBUG] md5_part={md5_part}")

    return hashlib.sha256(
        (challenge + md5_part).encode("utf-8")
    ).hexdigest()


def authenticate(session: KeeneticSession, login: str, realm: str, password_hash: str):
    """Отправляет хэш пароля, получает сессионную cookie."""
    payload = {"login": login, "password": password_hash}
    data, status = session.post_json("/auth", payload)
    if status != 200:
        print(f"[!] Ошибка авторизации: HTTP {status}")
        print(f"    Ответ: {data.decode('utf-8', errors='replace')}")
        sys.exit(1)
    print("[✓] Авторизация успешна")


def auth_flow(session: KeeneticSession, password: str):
    """Полный цикл авторизации: challenge → hash → login."""
    realm, challenge = get_challenge(session)
    print(f"[*] Keenetic {realm}, challenge: {challenge[:16]}...")
    password_hash = compute_password_hash(config.LOGIN, realm, password, challenge)
    authenticate(session, config.LOGIN, realm, password_hash)
