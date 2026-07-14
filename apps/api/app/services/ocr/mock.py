"""Deterministic QuestionSplitOCR-shaped demo provider."""

from __future__ import annotations

from app.services.ocr.types import Response


class MockOCRProvider:
    """Offline multi-question fixture that is always identified as demo data."""

    name = "mock"
    is_demo = True

    async def recognize_questions(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        pdf_page_number: int = 1,
    ) -> Response:
        del file_bytes, filename, content_type, pdf_page_number
        return Response.model_validate(
            {
                "QuestionInfo": [
                    {
                        "Angle": 0.0,
                        "Height": 1200,
                        "Width": 900,
                        "OrgHeight": 1200,
                        "OrgWidth": 900,
                        "ResultList": [
                            {
                                "Question": [
                                    {
                                        "Index": 0,
                                        "Text": "1. 某数增加 20% 后为 120，原数是多少？",
                                        "GroupType": "question",
                                    }
                                ],
                                "Option": [
                                    {"Index": 0, "Text": "A. 90"},
                                    {"Index": 1, "Text": "B. 100"},
                                ],
                                "Figure": [
                                    {"Index": 0, "Text": "演示图形"},
                                ],
                                "Table": [],
                                "Answer": [],
                                "Parse": [],
                                "Coord": [],
                            },
                            {
                                "Question": [
                                    {
                                        "Index": 1,
                                        "Text": "2. 根据表格比较两组数据。",
                                        "GroupType": "question",
                                    }
                                ],
                                "Option": [],
                                "Figure": [],
                                "Table": [
                                    {"Index": 0, "Text": "演示表格"},
                                ],
                                "Answer": [],
                                "Parse": [],
                                "Coord": [],
                            },
                        ],
                    }
                ],
                "RequestId": "mock-question-split-v1",
            }
        )
