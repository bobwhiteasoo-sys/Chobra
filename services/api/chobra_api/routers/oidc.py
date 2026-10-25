"""Browser sign-in: code + PKCE, signed browser transaction, verified ID token."""
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from .. import oidc
from ..access import load_roles
from ..config import settings
from ..deps import DbDep
from ..errors import ApiError, body
from ..models import User
from ..security import create_session, signing_key
from .core import _set_cookies

router = APIRouter()
COOKIE = "chobra_oidc"


def client():
    return httpx.Client(timeout=httpx.Timeout(10.0), follow_redirects=False)


def finish(response):
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get("/auth/oidc/start")
def start(next: str = "/"):
    oidc.configured(settings)
    try:
        with client() as http:
            metadata = oidc.discovery(http, settings)
        data, cookie = oidc.transaction(signing_key(), next)
        response = RedirectResponse(oidc.authorization_url(metadata, settings, data), status_code=302)
        response.set_cookie(COOKIE, cookie, max_age=oidc.TTL, httponly=True, secure=settings.secure_cookies, samesite="lax", path="/api/v1/auth/oidc")
        return finish(response)
    except (httpx.HTTPError, ValueError, TypeError):
        raise ApiError(503, "OIDC_UNAVAILABLE", "Провайдер входа временно недоступен.") from None


@router.get("/auth/oidc/callback")
def callback(request: Request, db: DbDep):
    try:
        oidc.configured(settings)
        params = request.query_params
        if any(len(params.getlist(k)) > 1 for k in ("state", "code", "error", "iss")):
            raise oidc.failed()
        data = oidc.read_transaction(request.cookies.get(COOKIE), params.get("state"), signing_key())
        if params.get("error") or not params.get("code") or len(params["code"]) > 4096:
            raise oidc.failed()
        if "iss" in params and params["iss"] != settings.oidc_issuer:
            raise oidc.failed()
        with client() as http:
            metadata = oidc.discovery(http, settings)
            claims = oidc.exchange(http, metadata, settings, params["code"], data)
        user = db.execute(select(User).where(User.oidc_issuer == settings.oidc_issuer, User.oidc_subject == claims["sub"])).scalar_one_or_none()
        if user is None:
            name = claims.get("name") or claims.get("preferred_username") or "Пользователь"
            email = claims.get("email") if claims.get("email_verified") is True else None
            user = User(oidc_issuer=settings.oidc_issuer, oidc_subject=claims["sub"], display_name=str(name)[:200],
                        email=email[:300] if isinstance(email, str) else None, locale="ru")
            db.add(user)
            db.flush()
        roles = load_roles(db, user)
        token, session = create_session(db, user)
        db.commit()
        response = RedirectResponse(oidc.safe_next(data.get("next")) if roles else "/onboarding", status_code=303)
        _set_cookies(response, token, session.csrf_token)
    except ApiError as exc:
        response = JSONResponse(body(exc.code, exc.message), status_code=exc.status)
    except (httpx.HTTPError, ValueError, TypeError):
        response = JSONResponse(body("OIDC_UNAVAILABLE", "Провайдер входа временно недоступен. Начните вход заново."), status_code=503)
    # Providers MUST consume authorization codes once; PKCE binds the code to this browser
    # transaction. Deleting the cookie also prevents ordinary browser callback replay.
    response.delete_cookie(COOKIE, path="/api/v1/auth/oidc", secure=settings.secure_cookies, httponly=True, samesite="lax")
    return finish(response)
