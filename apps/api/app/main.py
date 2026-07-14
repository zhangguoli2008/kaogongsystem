from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.database import create_session_factory
from app.core.errors import UnexpectedErrorMiddleware, install_error_handlers
from app.core.rate_limit import RateLimiter
from app.core.readiness import ReadinessError, probe_readiness
from app.services.ocr.factory import create_ocr_provider
from app.services.ocr.service import OCRService


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    # Validate live-provider credentials before serving any traffic.  Deferring
    # this check to an OCR request would turn an operator misconfiguration into
    # a user-facing 500 response.
    resolved.validate_for_startup()
    provider_mode = resolved.effective_provider_mode
    app = FastAPI(title="AI 公考错题诊断系统")
    app.state.settings = resolved
    app.state.session_factory = create_session_factory(resolved.database_url)
    app.state.auth_rate_limiter = RateLimiter(limit=10, window_seconds=60)
    # Keep provider throttling separate so future analysis calls can share the
    # same bounded state without affecting authentication limits.
    app.state.provider_rate_limiter = RateLimiter(limit=10, window_seconds=60)
    app.state.ocr_provider = create_ocr_provider(resolved)
    app.state.ocr_service = OCRService(app.state.ocr_provider, resolved)
    app.add_middleware(UnexpectedErrorMiddleware)
    if resolved.allowed_hosts != ["*"]:
        app.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=resolved.allowed_hosts,
        )
    # Added last so the configured CORS policy also wraps unexpected responses.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    app.include_router(api_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "provider_mode": provider_mode}

    @app.get("/ready")
    async def ready(request: Request):
        try:
            await probe_readiness(
                request.app.state.session_factory,
                request.app.state.settings.upload_dir,
            )
        except ReadinessError:
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        return {"status": "ready", "provider_mode": provider_mode}

    return app


app = create_app()
