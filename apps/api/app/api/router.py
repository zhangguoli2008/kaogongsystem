from fastapi import APIRouter

from app.api.routes.auth import router as auth_router
from app.api.routes.analytics import router as analytics_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.providers import router as providers_router
from app.api.routes.questions import router as questions_router
from app.api.routes.reviews import router as reviews_router
from app.api.routes.uploads import router as uploads_router
from app.models.analysis import Analysis  # noqa: F401

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(questions_router)
api_router.include_router(reviews_router)
api_router.include_router(analytics_router)
api_router.include_router(dashboard_router)
api_router.include_router(uploads_router)
api_router.include_router(providers_router)
