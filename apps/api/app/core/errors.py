import logging
from collections import defaultdict
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)


class APIError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        field_errors: dict[str, list[str]] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field_errors = field_errors


def request_id_for(request: Request) -> str:
    """Return one request ID shared by handlers, provider logs and responses."""

    existing = getattr(request.state, "request_id", None)
    if existing:
        return existing
    resolved = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = resolved
    return resolved


def _request_id(request: Request) -> str:
    # Kept as a private compatibility alias for existing error middleware code.
    return request_id_for(request)


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    field_errors: dict[str, list[str]] | None = None,
    request_id: str | None = None,
) -> JSONResponse:
    resolved_request_id = request_id or _request_id(request)
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": message,
            "field_errors": field_errors,
            "request_id": resolved_request_id,
        },
        headers={"X-Request-ID": resolved_request_id},
    )


class UnexpectedErrorMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        try:
            await self.app(scope, receive, send)
        except Exception:
            request = Request(scope)
            request_id = _request_id(request)
            logger.exception(
                "Unhandled application exception",
                extra={"request_id": request_id},
            )
            response = _error_response(
                request,
                status_code=500,
                code="internal_server_error",
                message="服务器内部错误",
                request_id=request_id,
            )
            await response(scope, receive, send)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def handle_api_error(request: Request, exc: APIError) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            field_errors=exc.field_errors,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        errors: dict[str, list[str]] = defaultdict(list)
        for error in exc.errors():
            location = error["loc"]
            field = ".".join(str(part) for part in location if part != "body")
            errors[field or "body"].append(error["msg"])
        return _error_response(
            request,
            status_code=422,
            code="validation_error",
            message="请求参数无效",
            field_errors=dict(errors),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = "not_found" if exc.status_code == 404 else "http_error"
        return _error_response(
            request,
            status_code=exc.status_code,
            code=code,
            message=str(exc.detail),
        )
