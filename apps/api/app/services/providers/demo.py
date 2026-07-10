from __future__ import annotations

from app.schemas.question import QuestionOption
from app.schemas.upload import OcrResult


class DemoProvider:
    """Deterministic offline provider used by local demos and tests."""

    async def ocr(self, image_bytes: bytes, mime_type: str) -> OcrResult:
        del image_bytes, mime_type
        return OcrResult(
            stem="某地区2024年第一季度生产总值为120亿元，第二季度比第一季度增长10%，第二季度生产总值为多少亿元？",
            options=[
                QuestionOption(label="A", content="120亿元"),
                QuestionOption(label="B", content="126亿元"),
                QuestionOption(label="C", content="132亿元"),
                QuestionOption(label="D", content="144亿元"),
            ],
            user_answer="B",
            correct_answer="C",
            original_explanation="第二季度生产总值=120×(1+10%)=132亿元。",
            raw_text="某地区2024年第一季度生产总值为120亿元，第二季度比第一季度增长10%。",
            is_demo=True,
        )

    async def analyze(self, payload):
        raise NotImplementedError("analysis provider is implemented in Task 5")
