from fastapi import APIRouter, Request

from app.api.deps import CurrentUser
from app.api.routes.auth import router as auth_router
from app.api.routes.analytics import router as analytics_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.providers import router as providers_router
from app.api.routes.questions import router as questions_router
from app.api.routes.reviews import router as reviews_router
from app.api.routes.uploads import router as uploads_router
from app.models.analysis import Analysis  # noqa: F401
from app.schemas.ocr import OcrStatus
from app.services.ocr_contract import API_NAME, USE_NEW_MODEL

api_router = APIRouter(prefix="/api/v1")


@api_router.get("/ocr/status", tags=["ocr"], response_model=OcrStatus)
async def ocr_status(request: Request, current_user: CurrentUser) -> OcrStatus:
    del current_user
    settings = request.app.state.settings
    configured = settings.ocr_provider == "mock" or bool(
        settings.tencentcloud_secret_id and settings.tencentcloud_secret_key
    )
    return OcrStatus(
        provider=settings.ocr_provider,
        configured=configured,
        api_name=API_NAME,
        supports_multi_question=True,
        supports_pdf=True,
        supports_options=True,
        use_new_model=USE_NEW_MODEL,
    )


api_router.include_router(auth_router)
api_router.include_router(questions_router)
api_router.include_router(reviews_router)
api_router.include_router(analytics_router)
api_router.include_router(dashboard_router)
api_router.include_router(uploads_router)
api_router.include_router(providers_router)
