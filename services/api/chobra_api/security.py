"""Sessions, CSRF, signed download links and secret encryption (spec section 26)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import AuthSession, User

SESSION_COOKIE = "chobra_session"
CSRF_COOKIE = "chobra_csrf"
CSRF_HEADER = "X-CSRF-Token"


def _key(material: str, label: str) -> bytes:
    if material:
        return hashlib.sha256(f"{label}:{material}".encode()).digest()
    # Development fallback: a per-installation key file, never committed.
    path = settings.objects_dir / f".{label}.key"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(secrets.token_bytes(32))
        os.chmod(path, 0o600)
    return path.read_bytes()


def signing_key() -> bytes:
    return _key(settings.signing_key, "signing")


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def now() -> datetime:
    return datetime.now(timezone.utc)


def create_session(db: Session, user: User) -> tuple[str, AuthSession]:
    token = secrets.token_urlsafe(32)
    record = AuthSession(
        token_hash=token_hash(token),
        csrf_token=secrets.token_urlsafe(24),
        user_id=user.id,
        expires_at=now() + timedelta(days=settings.session_max_days),
    )
    db.add(record)
    db.flush()
    return token, record


def load_session(db: Session, token: str | None) -> tuple[AuthSession, User] | None:
    if not token:
        return None
    record = db.execute(select(AuthSession).where(AuthSession.token_hash == token_hash(token))).scalar_one_or_none()
    if record is None or record.revoked_at is not None:
        return None
    moment = now()
    if record.expires_at <= moment or record.last_seen_at + timedelta(hours=settings.session_idle_hours) <= moment:
        return None
    if (moment - record.last_seen_at).total_seconds() > 60:
        record.last_seen_at = moment
    user = db.get(User, record.user_id)
    return (record, user) if user else None


def sign_link(object_key: str, ttl_seconds: int = 300) -> str:
    expires = int(time.time()) + ttl_seconds
    mac = hmac.new(signing_key(), f"{object_key}|{expires}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"{expires}.{mac}"


def verify_link(object_key: str, signature: str) -> bool:
    try:
        expires_text, mac = signature.split(".", 1)
        expires = int(expires_text)
    except ValueError:
        return False
    if expires < time.time():
        return False
    expected = hmac.new(signing_key(), f"{object_key}|{expires}".encode(), hashlib.sha256).hexdigest()[:32]
    return hmac.compare_digest(expected, mac)


def encrypt_secret(plaintext: str) -> str:
    nonce = secrets.token_bytes(12)
    data = AESGCM(_key(settings.secrets_key, "secrets")).encrypt(nonce, plaintext.encode(), b"chobra-provider-key")
    return base64.b64encode(nonce + data).decode()


def decrypt_secret(ciphertext: str) -> str:
    raw = base64.b64decode(ciphertext)
    return AESGCM(_key(settings.secrets_key, "secrets")).decrypt(raw[:12], raw[12:], b"chobra-provider-key").decode()
