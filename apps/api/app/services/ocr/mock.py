"""Deterministic QuestionSplitOCR-shaped demo provider."""

from __future__ import annotations

from app.services.ocr.types import Response


def _point(x: int, y: int) -> dict[str, int]:
    return {"X": x, "Y": y}


def _polygon(left: int, top: int, right: int, bottom: int) -> dict[str, object]:
    return {
        "LeftTop": _point(left, top),
        "RightTop": _point(right, top),
        "RightBottom": _point(right, bottom),
        "LeftBottom": _point(left, bottom),
    }


def _element(
    index: int,
    text: str,
    coord: dict[str, object],
    *,
    group_type: str | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {"Index": index, "Text": text, "Coord": coord}
    if group_type is not None:
        value["GroupType"] = group_type
    return value


def _page_one_groups() -> list[dict[str, object]]:
    return [
        {
            "Question": [
                _element(
                    0,
                    "1. 下列句子中，没有语病的一项是？",
                    _polygon(60, 40, 840, 100),
                    group_type="multiple-choice",
                )
            ],
            "Option": [
                _element(
                    0, "A. 他认真研究并听取了大家的意见。", _polygon(80, 115, 820, 150)
                ),
                _element(
                    1, "B. 学校开展了丰富多彩的阅读活动。", _polygon(80, 160, 820, 195)
                ),
                _element(
                    2, "C. 通过这次学习，使我提高了认识。", _polygon(80, 205, 820, 240)
                ),
            ],
            "Figure": [],
            "Table": [],
            "Answer": [_element(0, "B", _polygon(690, 245, 830, 270))],
            "Parse": [
                _element(
                    0, "B 项搭配完整，其他选项存在语病。", _polygon(80, 245, 650, 275)
                )
            ],
            "Coord": [_polygon(40, 25, 860, 280)],
        },
        {
            "Question": [
                _element(
                    0,
                    "2. 某数增加 20% 后为 120，原数是多少？",
                    _polygon(60, 300, 840, 360),
                    group_type="arithmetic",
                )
            ],
            "Option": [
                _element(0, "A. 90", _polygon(100, 375, 300, 410)),
                _element(1, "B. 100", _polygon(340, 375, 560, 410)),
                _element(2, "C. 110", _polygon(600, 375, 820, 410)),
            ],
            "Figure": [],
            "Table": [],
            "Answer": [_element(0, "B", _polygon(690, 425, 830, 450))],
            "Parse": [_element(0, "120÷(1+20%)=100。", _polygon(80, 425, 650, 455))],
            "Coord": [_polygon(40, 285, 860, 465)],
        },
        {
            "Question": [
                _element(
                    0,
                    "3. 观察图形变化规律，选择最合适的一项。",
                    _polygon(60, 490, 840, 545),
                    group_type="multiple-choice",
                )
            ],
            "Option": [
                _element(0, "A. 图形顺时针旋转", _polygon(80, 690, 330, 735)),
                _element(1, "B. 图形逆时针旋转", _polygon(345, 690, 600, 735)),
                _element(2, "C. 图形保持不变", _polygon(615, 690, 840, 735)),
            ],
            "Figure": [_element(0, "演示图形序列", _polygon(120, 555, 780, 675))],
            "Table": [],
            "Answer": [_element(0, "A", _polygon(690, 745, 830, 770))],
            "Parse": [
                _element(0, "每一步均顺时针旋转 90°。", _polygon(80, 745, 650, 775))
            ],
            "Coord": [_polygon(40, 475, 860, 785)],
        },
        {
            "Question": [
                _element(
                    0,
                    "4. 根据表格，比较甲、乙两组的增长量。",
                    _polygon(60, 805, 840, 855),
                    group_type="problem-solving",
                )
            ],
            "Option": [],
            "Figure": [],
            "Table": [
                _element(
                    0, "甲组：120→150；乙组：90→135", _polygon(130, 870, 770, 1010)
                )
            ],
            "Answer": [_element(0, "乙组增长量更大", _polygon(560, 1030, 830, 1060))],
            "Parse": [
                _element(0, "甲增长 30，乙增长 45。", _polygon(80, 1030, 540, 1065))
            ],
            "Coord": [_polygon(40, 790, 860, 1080)],
        },
    ]


def _later_page_groups(page_number: int) -> list[dict[str, object]]:
    return [
        {
            "Question": [
                _element(
                    0,
                    f"1. 这是演示 PDF 第 {page_number} 页的言语理解题。",
                    _polygon(60, 80, 840, 150),
                    group_type="multiple-choice",
                )
            ],
            "Option": [
                _element(0, "A. 本页选项一", _polygon(90, 180, 430, 230)),
                _element(1, "B. 本页选项二", _polygon(470, 180, 810, 230)),
            ],
            "Figure": [],
            "Table": [],
            "Answer": [_element(0, "A", _polygon(690, 250, 830, 280))],
            "Parse": [_element(0, "演示页解析内容。", _polygon(80, 250, 650, 290))],
            "Coord": [_polygon(40, 55, 860, 310)],
        },
        {
            "Question": [
                _element(
                    0,
                    f"2. 这是演示 PDF 第 {page_number} 页的资料分析题。",
                    _polygon(60, 360, 840, 430),
                    group_type="problem-solving",
                )
            ],
            "Option": [],
            "Figure": [],
            "Table": [
                _element(
                    0, f"第 {page_number} 页演示表格", _polygon(130, 460, 770, 690)
                )
            ],
            "Answer": [_element(0, "请人工核算", _polygon(600, 720, 830, 750))],
            "Parse": [
                _element(0, "先读取表格，再比较差值。", _polygon(80, 720, 570, 760))
            ],
            "Coord": [_polygon(40, 335, 860, 780)],
        },
    ]


class MockOCRProvider:
    """Offline multi-question fixture that is always identified as demo data."""

    name = "mock"
    is_demo = True
    is_configured = True

    async def recognize_questions(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        pdf_page_number: int = 1,
    ) -> Response:
        del file_bytes, filename, content_type
        page_number = max(1, pdf_page_number)
        groups = (
            _page_one_groups() if page_number == 1 else _later_page_groups(page_number)
        )
        return Response.model_validate(
            {
                "QuestionInfo": [
                    {
                        "Angle": 0.0,
                        "Height": 1200,
                        "Width": 900,
                        "OrgHeight": 1200,
                        "OrgWidth": 900,
                        "ResultList": groups,
                    }
                ],
                "RequestId": f"mock-question-split-page-{page_number}",
            }
        )
