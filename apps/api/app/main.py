from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.database import create_session_factory
from app.core.errors import install_error_handlers
from app.core.rate_limit import RateLimiter


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    app = FastAPI(title="AI 公考错题诊断系统")
    app.state.settings = resolved
    app.state.session_factory = create_session_factory(resolved.database_url)
    app.state.auth_rate_limiter = RateLimiter(limit=10, window_seconds=60)
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
        return {"status": "ok", "provider_mode": resolved.effective_provider_mode}

    return app


app = create_app()
