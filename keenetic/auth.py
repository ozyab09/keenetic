"""Keenetic router authentication via challenge-response (MD5 + SHA256)."""

import hashlib
import sys

import keenetic.config as config

from keenetic.session import KeeneticSession


def get_challenge(session: KeeneticSession) -> tuple[str, str]:
    """Gets realm and challenge from the router (a 401 code is expected)."""
    _, headers, status = session.get("/auth", return_headers=True)
    if status != 401:
        print(f"[!] Expected HTTP 401, got {status}")
        sys.exit(1)

    realm = headers.get("X-NDM-Realm")
    challenge = headers.get("X-NDM-Challenge")
    if not realm or not challenge:
        print("[!] Router did not return X-NDM-Realm / X-NDM-Challenge")
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
    """Sends the password hash and obtains the session cookie."""
    payload = {"login": login, "password": password_hash}
    data, status = session.post_json("/auth", payload)
    if status != 200:
        print(f"[!] Authentication failed: HTTP {status}")
        print(f"    Response: {data.decode('utf-8', errors='replace')}")
        sys.exit(1)
    print("[✓] Authentication successful")


def auth_flow(session: KeeneticSession, password: str):
    """Full authentication flow: challenge → hash → login."""
    realm, challenge = get_challenge(session)
    print(f"[*] Keenetic {realm}, challenge: {challenge[:16]}...")
    password_hash = compute_password_hash(config.LOGIN, realm, password, challenge)
    authenticate(session, config.LOGIN, realm, password_hash)
