"""FastAPI application factory.

This is the only place the pieces of Step 1 get wired together:
settings, structured logging, exception handlers, request logging
middleware, and route registration. Later steps add new routers here
without touching how the app is built.
"""

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from scout.api.exceptions import register_exception_handlers
from scout.api.routes.affiliate import router as affiliate_router
from scout.api.routes.cart import router as cart_router
from scout.api.routes.catalog import router as catalog_router
from scout.api.routes.chat import router as chat_router
from scout.api.routes.chat_stream import router as chat_stream_router
from scout.api.routes.checkout import router as checkout_router
from scout.api.routes.health import router as health_router
from scout.api.routes.memory import router as memory_router
from scout.api.routes.orders import router as orders_router
from scout.api.routes.protected_actions import router as protected_actions_router
from scout.api.routes.saved_products import router as saved_products_router
from scout.api.routes.stores import router as stores_router
from scout.config import get_settings
from scout.logging_config import configure_logging

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build and return a configured FastAPI application instance."""
    settings = get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title=settings.app_name, version="0.1.0")

    # CORS - Step 14's React frontend runs on a different origin
    # (http://localhost:5173 in development) than this API, so the
    # browser needs an explicit allow-list; never "*" (CLAUDE.md
    # section 7 - the API layer must not silently open itself to every
    # origin). allow_credentials stays False since Scout does not use
    # cookies for authentication yet.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        # Step 15's cart endpoints add PATCH/PUT/DELETE to Step 14's
        # GET/POST - every method Scout's API actually exposes must be
        # explicit here (never "*"), or the browser blocks the request
        # before it reaches this API at all.
        allow_headers=["Content-Type", "Accept"],
    )

    register_exception_handlers(app)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        """Log every request with a correlation ID, method, path, and duration."""
        request_id = str(uuid.uuid4())
        start_time = time.perf_counter()

        logger.info(
            "request_started",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
            },
        )

        response = await call_next(request)

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        response.headers["X-Request-ID"] = request_id
        return response

    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(chat_stream_router)
    app.include_router(cart_router)
    app.include_router(catalog_router)
    app.include_router(checkout_router)
    app.include_router(affiliate_router)
    app.include_router(memory_router)
    app.include_router(orders_router)
    app.include_router(protected_actions_router)
    app.include_router(saved_products_router)
    app.include_router(stores_router)

    return app
