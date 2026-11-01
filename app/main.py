import logging

import httpx
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from app.auth import JwksCache
from app.cache import TTLCache
from app.config import Settings, get_settings
from app.db import make_engine, make_sessionmaker
from app.email import EmailSender, make_email_sender
from app.ratelimit import RateLimiter
from app.routers import (
    admin,
    auth,
    curtailment,
    events,
    exports,
    flag,
    forecast,
    geo,
    grid,
    health,
    hydro,
    market,
    news,
    newsletter,
    plants,
    rankings,
    reports,
    system,
)

logger = logging.getLogger("app")


def _validation_message(exc: RequestValidationError) -> str:
    parts = []
    for error in exc.errors():
        location = ".".join(str(p) for p in error.get("loc", ()) if p != "body")
        parts.append(f"{location}: {error.get('msg', 'invalid')}" if location else error["msg"])
    return "Invalid parameters: " + "; ".join(parts)


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, RequestValidationError):
        raise TypeError(f"unexpected exception type: {type(exc).__name__}")
    return JSONResponse(status_code=422, content={"detail": _validation_message(exc)})


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal error."})


class SelectiveGZipMiddleware(GZipMiddleware):
    """Compress JSON responses; skip exports and PDFs, which are already compressed."""

    def __init__(self, app: ASGIApp, minimum_size: int = 1024) -> None:
        super().__init__(app, minimum_size=minimum_size)
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            path: str = scope["path"]
            if path.startswith("/v1/exports") or path.endswith("/pdf"):
                await self._app(scope, receive, send)
                return
        await super().__call__(scope, receive, send)


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    email_sender: EmailSender | None = None,
    web_transport: httpx.BaseTransport | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    engine = engine or make_engine(settings.database_url)

    app = FastAPI(
        title="spillway-api",
        version="0.1.0",
        description="Public and admin API of the energy data platform (Phase 1).",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = make_sessionmaker(engine)
    app.state.cache = TTLCache(settings.CACHE_TTL_SECONDS)
    app.state.newsletter_limiter = RateLimiter(settings.NEWSLETTER_RATE_LIMIT_PER_MINUTE, 60.0)
    app.state.auth_limiter = RateLimiter(settings.AUTH_RATE_LIMIT_PER_MINUTE, 60.0)
    app.state.export_limiter = RateLimiter(settings.EXPORT_RATE_LIMIT_PER_MINUTE, 60.0)
    app.state.email_sender = email_sender or make_email_sender(settings)
    app.state.jwks = JwksCache(settings.cognito_jwks_url)
    app.state.web_transport = web_transport

    if settings.AUTH_DISABLED:
        logger.warning("AUTH_DISABLED=true: /v1/admin/* routes have no authentication (local only)")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_url],
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.add_middleware(SelectiveGZipMiddleware)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    for module in (
        curtailment,
        plants,
        rankings,
        reports,
        exports,
        flag,
        forecast,
        news,
        system,
        hydro,
        grid,
        geo,
        market,
        newsletter,
        auth,
        events,
        admin,
        health,
    ):
        app.include_router(module.router)
    app.include_router(news.admin_router)
    return app


app = create_app()
