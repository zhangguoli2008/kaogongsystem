"""Central factory for OCR providers, independent from AI providers."""

from __future__ import annotations

from app.core.config import Settings
from app.services.ocr.base import OCRProvider
from app.services.ocr.mock import MockOCRProvider
from app.services.ocr.tencent import TencentOCRProvider


def create_ocr_provider(settings: Settings) -> OCRProvider:
    if settings.ocr_provider == "mock":
        return MockOCRProvider()
    if settings.ocr_provider == "tencent_question_split":
        return TencentOCRProvider(settings)
    raise ValueError(f"Unsupported OCR provider: {settings.ocr_provider}")
