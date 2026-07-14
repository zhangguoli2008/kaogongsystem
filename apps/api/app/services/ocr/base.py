"""Contract shared by live and demo OCR providers."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.services.ocr.types import Response


@runtime_checkable
class OCRProvider(Protocol):
    name: str
    is_demo: bool

    async def recognize_questions(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        pdf_page_number: int = 1,
    ) -> Response: ...
