from __future__ import annotations

from typing import Any, Protocol

from app.schemas.upload import OcrResult


class AIProvider(Protocol):
    async def ocr(
        self,
        image_bytes: bytes,
        mime_type: str,
        request_id: str | None = None,
    ) -> OcrResult: ...

    async def analyze(self, payload: Any) -> Any: ...
