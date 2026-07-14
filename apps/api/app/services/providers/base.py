from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from app.schemas.analysis import AnalysisImage, AnalysisInput, AnalysisResult
from app.schemas.analytics import AnalyticsAdviceInput, AnalyticsAdviceResult
from app.schemas.upload import OcrResult


class AIProvider(Protocol):
    async def ocr(
        self,
        image_bytes: bytes,
        mime_type: str,
        request_id: str | None = None,
    ) -> OcrResult: ...

    async def analyze(
        self,
        payload: AnalysisInput,
        request_id: str | None = None,
        *,
        images: Sequence[AnalysisImage] = (),
    ) -> AnalysisResult: ...

    async def advise(
        self, payload: AnalyticsAdviceInput, request_id: str | None = None
    ) -> AnalyticsAdviceResult: ...
