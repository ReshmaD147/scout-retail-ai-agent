"""Centralized exception handling.

Every error path - our own application errors, request validation
errors, HTTP errors, and truly unexpected exceptions - is caught here
and turned into a consistent JSON response of the shape:
    {"error": "<message>", "code": "<CODE>", "message": "<message>", "details": <optional>}

`code`/`message` were added in Step 12 for scout/api/routes/chat.py's
structured errors (e.g. {"code": "WORKFLOW_TIMEOUT", "message": ...});
`error` is kept, unchanged, as the original Step 1 key so no existing
caller or test that only reads `error` breaks.

No raw stack traces are ever returned to the client.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ScoutAppError(Exception):
    """Base class for application-specific errors raised inside Scout.

    Later steps (agents, orders, inventory) should raise subclasses of
    this instead of generic Exceptions, so errors carry an HTTP status
    code and a safe, user-facing message.
    """

    def __init__(self, message: str, status_code: int = 500, code: str = "INTERNAL_ERROR") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        """A short, stable, machine-readable error category (e.g.
        "WORKFLOW_TIMEOUT", "TOOL_UNAVAILABLE") - added in Step 12 so
        API clients can branch on a fixed code instead of parsing
        `message` text. Defaults to a generic value so every pre-Step-12
        call site that does not pass one still works unchanged."""


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all exception handlers to the given FastAPI app."""

    @app.exception_handler(ScoutAppError)
    async def handle_scout_app_error(request: Request, exc: ScoutAppError) -> JSONResponse:
        logger.warning(
            "application_error",
            extra={"path": request.url.path, "error": exc.message, "code": exc.code},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message, "code": exc.code, "message": exc.message},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # exc.errors() is NOT guaranteed to be plain-JSON-serializable:
        # Pydantic v2 includes the raised exception object itself under
        # each error's ctx["error"] when a field_validator raises
        # ValueError (Step 12's ChatRequest blank-string checks do
        # exactly this) - json.dumps chokes on a raw ValueError.
        # jsonable_encoder is FastAPI's own fallback (it is what the
        # framework's default validation-error handler uses internally)
        # and safely stringifies anything it cannot serialize directly.
        safe_errors = jsonable_encoder(exc.errors())
        logger.warning(
            "validation_error",
            extra={"path": request.url.path, "errors": safe_errors},
        )
        return JSONResponse(
            status_code=422,
            content={"error": "Invalid request", "details": safe_errors},
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        logger.warning(
            "http_exception",
            extra={
                "path": request.url.path,
                "status_code": exc.status_code,
                "detail": exc.detail,
            },
        )
        return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.error(
            "unhandled_exception",
            exc_info=exc,
            extra={"path": request.url.path},
        )
        return JSONResponse(status_code=500, content={"error": "Internal server error"})
