"""QR sign in: no web endpoint may approve a login; Telegram is the identity proof."""
from datetime import timedelta
import hmac
import secrets
import uuid
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, Response
from sqlalchemy import select, func, delete

from ..config import settings
from ..deps import DbDep
from ..errors import ApiError
from ..models import TelegramLogin, User
from ..security import now, token_hash, create_session
from .core import _me, _set_cookies

router = APIRouter()
BROWSER_COOKIE = "chobra_tg_browser"


def same_origin(request: Request):
    origin = request.headers.get("origin")
    allowed = {settings.public_url.rstrip('/'), str(request.base_url).rstrip('/')}
    # The reverse proxy preserves Host, while upstream itself is plain HTTP.
    allowed.add("https://" + request.headers.get("host", ""))
    if origin and origin.rstrip('/') not in allowed:
        raise ApiError(403, "ORIGIN_REJECTED", "Откройте вход на сайте Chobra")
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise ApiError(403, "ORIGIN_REJECTED", "Откройте вход на сайте Chobra")


@router.post("/auth/telegram/challenge", status_code=201)
def challenge(request: Request, response: Response, db: DbDep):
    same_origin(request)
    if not settings.telegram_bot_token:
        raise ApiError(503, "TELEGRAM_DISABLED", "Telegram-вход ещё не настроен на сервере")
    browser = request.cookies.get(BROWSER_COOKIE) or secrets.token_urlsafe(32)
    hashed = token_hash(browser)
    count = db.scalar(select(func.count()).select_from(TelegramLogin).where(TelegramLogin.browser_hash == hashed, TelegramLogin.created_at > now() - timedelta(minutes=1)))
    if count >= 5:
        raise ApiError(429, "TRY_LATER", "Подождите минуту перед обновлением QR-кода")
    # Bound storage and invalidate previous pending challenges from this browser.
    db.execute(delete(TelegramLogin).where(TelegramLogin.expires_at < now() - timedelta(days=1)))
    for old in db.scalars(select(TelegramLogin).where(TelegramLogin.browser_hash == hashed, TelegramLogin.status.in_(["pending", "approved"]))):
        old.status = "expired"
    start = secrets.token_urlsafe(24)
    row = TelegramLogin(start_hash=token_hash(start), browser_hash=hashed, display_code=secrets.token_hex(3).upper(), expires_at=now() + timedelta(minutes=5))
    db.add(row); db.commit()
    response.headers["Cache-Control"] = "no-store"
    response.set_cookie(BROWSER_COOKIE, browser, httponly=True, secure=settings.secure_cookies, samesite="strict", max_age=600, path="/api/v1/auth/telegram")
    return {"id": str(row.id), "code": row.display_code, "expires_at": row.expires_at.isoformat(), "url": f"https://t.me/{settings.telegram_bot_username}?start=login_{start}"}


def bound_challenge(request, db, challenge_id, lock=False):
    row = db.scalar(select(TelegramLogin).where(TelegramLogin.id == challenge_id).with_for_update()) if lock else db.get(TelegramLogin, challenge_id)
    browser = request.cookies.get(BROWSER_COOKIE, "")
    if not row or not browser or not hmac.compare_digest(row.browser_hash, token_hash(browser)):
        raise ApiError(404, "CHALLENGE_NOT_FOUND", "Запрос входа не найден. Обновите QR-код")
    if row.expires_at <= now() or row.status == "expired":
        raise ApiError(410, "CHALLENGE_EXPIRED", "Срок QR-кода истёк. Создайте новый")
    return row


@router.get("/auth/telegram/challenge/{challenge_id}")
def status(challenge_id: uuid.UUID, request: Request, response: Response, db: DbDep):
    response.headers["Cache-Control"] = "no-store"
    row = bound_challenge(request, db, challenge_id)
    return {"status": row.status}


@router.post("/auth/telegram/challenge/{challenge_id}/consume")
def consume(challenge_id: uuid.UUID, request: Request, response: Response, db: DbDep):
    same_origin(request)
    row = bound_challenge(request, db, challenge_id, lock=True)
    if row.status != "approved" or not row.user_id:
        raise ApiError(409, "NOT_APPROVED", "Подтвердите вход в Telegram")
    row.status = "consumed"
    user = db.get(User, row.user_id)
    token, session = create_session(db, user)
    db.commit()
    _set_cookies(response, token, session.csrf_token)
    response.headers["Cache-Control"] = "no-store"
    return _me(db, user, session)
