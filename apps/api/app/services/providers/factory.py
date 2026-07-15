from __future__ import annotations

from app.core.config import Settings
from app.services.providers.base import AIProvider
from app.services.providers.demo import DemoProvider
from app.services.providers.openai import OpenAIProvider


def get_provider(settings: Settings) -> AIProvider:
    if settings.effective_provider_mode == "demo":
        return DemoProvider()
    if not settings.openai_api_key:
        # ``effective_provider_mode`` normally prevents this, but keeping the
        # guard here makes the factory safe when called with a custom Settings.
        raise ValueError("PROVIDER_MODE=live requires OPENAI_API_KEY")
    return OpenAIProvider(api_key=settings.openai_api_key, model=settings.openai_model)
