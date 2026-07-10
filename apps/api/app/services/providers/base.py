from __future__ import annotations

from typing import Protocol

from app.schemas.analysis import AnalysisInput, AnalysisResult
from app.schemas.upload import OcrResult


class AIProvider(Protocol):
    async def ocr(
        self,
        image_bytes: bytes,
        mime_type: str,
        request_id: str | None = None,
    ) -> OcrResult: ...

    async def analyze(
        self, payload: AnalysisInput, request_id: str | None = None
    ) -> AnalysisResult: ...
