"""Single error contract: code, message, details, request_id (spec section 18)."""
from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

request_id_var: ContextVar[str] = ContextVar("request_id", default="")
log = logging.getLogger("chobra.api")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def not_found(what: str = "Объект") -> ApiError:
    # The same answer for "does not exist" and "not yours": an id in the URL grants nothing (AUTH-001).
    return ApiError(404, "NOT_FOUND", f"{what} не найден или недоступен")


def forbidden(message: str = "Недостаточно прав для этого действия") -> ApiError:
    return ApiError(403, "FORBIDDEN", message)


def conflict(code: str, message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError(409, code, message, details)


def body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details or {}, "request_id": request_id_var.get()}


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):  # noqa: ANN001
        rid = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:20]}"
        request_id_var.set(rid)
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(body(exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"path": ".".join(str(p) for p in e.get("loc", [])), "message": e.get("msg", "")} for e in exc.errors()]
        return JSONResponse(body("VALIDATION_ERROR", "Запрос не прошел проверку", {"errors": errors}), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
        return JSONResponse(body(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error %s", request_id_var.get())
        return JSONResponse(body("INTERNAL", "Внутренняя ошибка. Сообщите идентификатор обращения."), status_code=500)
