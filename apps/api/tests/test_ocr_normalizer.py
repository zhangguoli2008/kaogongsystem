from __future__ import annotations

import json
from uuid import UUID

import pytest

from app.schemas.ocr import OcrResult
from app.services.ocr.normalizer import (
    NoQuestionDetected,
    normalize_question_split_response,
)
from app.services.ocr.types import Response


def point(x: int, y: int) -> dict[str, int]:
    return {"X": x, "Y": y}


def polygon(seed: int = 0) -> dict[str, dict[str, int]]:
    return {
        "LeftTop": point(seed + 1, seed + 2),
        "RightTop": point(seed + 3, seed + 4),
        "RightBottom": point(seed + 5, seed + 6),
        "LeftBottom": point(seed + 7, seed + 8),
    }


def element(
    text: str | None,
    *,
    index: int | None = 0,
    coord: dict[str, object] | None = None,
    group_type: str | None = None,
    nested_results: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    value: dict[str, object] = {
        "Index": index,
        "Text": text,
        "GroupType": group_type,
        "ResultList": nested_results,
    }
    if coord is not None:
        value["Coord"] = coord
    return value


def result_list(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "Question": [
            element(
                "第二行含公式 x²+y²=1",
                index=1,
                coord=polygon(40),
            ),
            element(
                "1. 2024年，3∶2 的值是？",
                index=0,
                coord=polygon(0),
                group_type="multiple-choice",
            ),
        ],
        "Option": [
            element("B．6", index=1, coord=polygon(20)),
            element("A、5", index=0, coord=polygon(10)),
        ],
        "Answer": [element("A", index=0)],
        "Parse": [element("因为 3∶2=1.5。", index=0)],
        "Figure": [],
        "Table": [],
        "Coord": [polygon(50)],
    }
    value.update(overrides)
    return value


def question_info(
    results: list[dict[str, object]] | None,
    *,
    image_base64: str = "secret-image-payload",
    width: int = 600,
    height: int = 800,
    org_width: int = 1200,
    org_height: int = 1600,
    angle: float = 1.25,
) -> dict[str, object]:
    return {
        "Angle": angle,
        "Height": height,
        "Width": width,
        "ResultList": results,
        "OrgHeight": org_height,
        "OrgWidth": org_width,
        "ImageBase64": image_base64,
    }


def response(*infos: dict[str, object], request_id: str = "request-123") -> Response:
    return Response.model_validate(
        {"QuestionInfo": list(infos), "RequestId": request_id}
    )


def normalize(raw: Response, **overrides: object) -> OcrResult:
    kwargs: dict[str, object] = {
        "provider": "tencent",
        "file_id": "file-123",
        "page_number": 2,
    }
    kwargs.update(overrides)
    return normalize_question_split_response(raw, **kwargs)


def test_raw_response_accepts_pascal_case_and_never_serializes_image_base64() -> None:
    raw = response(question_info([result_list()]))

    assert raw.question_info[0].image_base64 == "secret-image-payload"
    assert "secret-image-payload" not in repr(raw)
    assert "ImageBase64" not in raw.model_dump(by_alias=True)["QuestionInfo"][0]
    assert "secret-image-payload" not in raw.model_dump_json(by_alias=True)


def test_official_result_list_derives_metadata_from_question_elements() -> None:
    official_result = {
        "Question": [
            {
                "Text": "题干第二行",
                "Index": 2,
                "Coord": polygon(10),
                "GroupType": None,
                "ResultList": None,
            },
            {
                "Text": "01. 题干第一行",
                "Index": 1,
                "Coord": polygon(0),
                "GroupType": "multiple-choice",
                "ResultList": [],
            },
        ],
        "Option": [],
        "Figure": [],
        "Table": [],
        "Answer": [],
        "Parse": [],
        "Coord": [polygon(20)],
    }

    actual = normalize(response(question_info([official_result])))

    question = actual.questions[0]
    assert question.index == 0
    assert question.question_number == "01"
    assert question.question_type == "multiple_choice_unknown"
    assert question.raw_group_type == "multiple-choice"
    assert question.question_text == "01. 题干第一行\n题干第二行"
    assert question.full_text == question.question_text
    assert [item.text for item in question.question_elements] == [
        "01. 题干第一行",
        "题干第二行",
    ]


def test_normalizes_official_single_question_shape_without_semantic_rewrites() -> None:
    raw = response(question_info([result_list()]))

    actual = normalize(raw, is_demo=True)

    assert actual.provider == "tencent"
    assert actual.api_name == "QuestionSplitOCR"
    assert actual.request_id == "request-123"
    assert actual.page_number == 2
    assert actual.question_count == 1
    assert actual.is_demo is True
    assert actual.source.model_dump() == {
        "file_id": "file-123",
        "image_url": "/uploads/file-123",
        "original_width": 1200,
        "original_height": 1600,
        "processed_width": 600,
        "processed_height": 800,
        "angle": 1.25,
    }

    question = actual.questions[0]
    UUID(question.temporary_id)
    assert question.index == 0
    assert question.source_info_index == 0
    assert question.question_number == "1"
    assert question.question_type == "multiple_choice_unknown"
    assert question.question_text == (
        "1. 2024年，3∶2 的值是？\n第二行含公式 x²+y²=1"
    )
    assert question.full_text == (
        "1. 2024年，3∶2 的值是？\n第二行含公式 x²+y²=1\nA、5\nB．6"
    )
    assert [item.text for item in question.question_elements] == [
        "1. 2024年，3∶2 的值是？",
        "第二行含公式 x²+y²=1",
    ]
    assert [option.model_dump() for option in question.options] == [
        {
            "label": "A",
            "text": "5",
            "raw_text": "A、5",
            "coord": {
                "left_top": {"x": 11, "y": 12},
                "right_top": {"x": 13, "y": 14},
                "right_bottom": {"x": 15, "y": 16},
                "left_bottom": {"x": 17, "y": 18},
            },
        },
        {
            "label": "B",
            "text": "6",
            "raw_text": "B．6",
            "coord": {
                "left_top": {"x": 21, "y": 22},
                "right_top": {"x": 23, "y": 24},
                "right_bottom": {"x": 25, "y": 26},
                "left_bottom": {"x": 27, "y": 28},
            },
        },
    ]
    assert question.recognized_answer == "A"
    assert question.recognized_parse == "因为 3∶2=1.5。"
    assert question.raw_group_type == "multiple-choice"
    assert question.coord[0].right_bottom.model_dump() == {"x": 55, "y": 56}
    assert question.warnings == []


def test_flattens_multiple_question_infos_in_local_order() -> None:
    first = question_info(
        [
            result_list(Question=[element("5. 第五题")]),
            result_list(Question=[element("3. 第三题")]),
        ]
    )
    second = question_info(
        [result_list(Question=[element("6. 第六题")])],
        width=300,
        height=400,
        org_width=900,
        org_height=1000,
        angle=9.0,
    )

    actual = normalize(response(first, second))

    assert [question.index for question in actual.questions] == [0, 1, 2]
    assert [question.source_info_index for question in actual.questions] == [0, 0, 1]
    assert [question.question_number for question in actual.questions] == ["5", "3", "6"]
    assert len({question.temporary_id for question in actual.questions}) == 3
    assert actual.question_count == 3
    assert actual.source.original_width == 1200
    assert actual.source.processed_width == 600
    assert actual.source.angle == 1.25


@pytest.mark.parametrize(
    ("raw_number", "expected"),
    [
        ("1.", "1"),
        ("1、", "1"),
        ("1．", "1"),
        ("1）", "1"),
        ("(1)", "1"),
        ("（1）", "1"),
        ("第1题", "1"),
        ("01.", "01"),
        ("101.", "101"),
        ("题号未知", None),
    ],
)
def test_normalizes_only_supported_question_number_shapes(
    raw_number: str, expected: str | None
) -> None:
    actual = normalize(
        response(
            question_info(
                [result_list(Question=[element(f"{raw_number} 题干")])]
            )
        )
    )

    assert actual.questions[0].question_number == expected


@pytest.mark.parametrize(
    ("raw_type", "expected"),
    [
        ("multiple-choice", "multiple_choice_unknown"),
        ("fill-in-the-blank", "fill_blank"),
        ("problem-solving", "problem_solving"),
        ("arithmetic", "arithmetic"),
        ("single-choice", "unknown"),
        (None, "unknown"),
    ],
)
def test_maps_only_explicit_tencent_question_types(
    raw_type: str | None, expected: str
) -> None:
    actual = normalize(
        response(
            question_info(
                [
                    result_list(
                        Question=[element("1. 题干", group_type=raw_type)]
                    )
                ]
            )
        )
    )

    assert actual.questions[0].question_type == expected


@pytest.mark.parametrize(
    ("raw_text", "expected_label", "expected_text"),
    [
        ("A.甲", "A", "甲"),
        ("B、乙", "B", "乙"),
        ("C．丙", "C", "丙"),
        ("D 丁", "D", "丁"),
        ("E:戊", "E", "戊"),
        ("F：己", "F", "己"),
        ("(G)庚", "G", "庚"),
        ("（H）辛", "H", "辛"),
        ("Ｉ．壬", "I", "壬"),
    ],
)
def test_parses_supported_option_labels_without_changing_body(
    raw_text: str, expected_label: str, expected_text: str
) -> None:
    actual = normalize(
        response(
            question_info(
                [result_list(Option=[element(raw_text)], Answer=[], Parse=[])]
            )
        )
    )

    option = actual.questions[0].options[0]
    assert option.label == expected_label
    assert option.text == expected_text
    assert option.raw_text == raw_text


def test_falls_back_to_ordered_labels_and_warns_for_unparseable_options() -> None:
    options = [
        element("没有标签，年份2024不应被修改", index=1),
        element("??第二项", index=None),
    ]

    actual = normalize(
        response(question_info([result_list(Option=options, Answer=[], Parse=[])]))
    )

    question = actual.questions[0]
    assert [(item.label, item.text, item.raw_text) for item in question.options] == [
        ("A", "没有标签，年份2024不应被修改", "没有标签，年份2024不应被修改"),
        ("B", "??第二项", "??第二项"),
    ]
    assert question.warnings == [
        "选项“没有标签，年份2024不应被修改”无法识别标签，已按顺序使用 A",
        "选项“??第二项”无法识别标签，已按顺序使用 B",
    ]


def test_keeps_figure_and_table_only_question_with_missing_polygon_points() -> None:
    incomplete_polygon = {
        "LeftTop": point(1, 2),
        "RightTop": point(3, 4),
        "RightBottom": None,
        "LeftBottom": point(7, 8),
    }
    raw_result = result_list(
        Question=[],
        Option=[],
        Answer=[],
        Parse=[],
        Figure=[element(None, index=2, coord=incomplete_polygon)],
        Table=[element("", index=1, coord=polygon(70))],
    )

    actual = normalize(response(question_info([raw_result])))

    question = actual.questions[0]
    assert question.question_text == ""
    assert question.full_text == ""
    assert len(question.figures) == 1
    assert question.figures[0].model_dump() == {
        "index": 2,
        "text": None,
        "coord": {
            "left_top": {"x": 1, "y": 2},
            "right_top": {"x": 3, "y": 4},
            "right_bottom": None,
            "left_bottom": {"x": 7, "y": 8},
        },
        "asset_id": None,
        "image_url": None,
    }
    assert len(question.tables) == 1
    assert question.tables[0].index == 1
    assert question.tables[0].text == ""
    assert question.tables[0].asset_id is None
    assert question.tables[0].image_url is None


def test_sorts_question_answer_parse_figure_and_table_elements_stably() -> None:
    raw_result = result_list(
        Question=[element("末", index=None), element("首", index=0)],
        Answer=[element("后", index=None), element("前", index=1)],
        Parse=[element("乙", index=None), element("甲", index=0)],
        Figure=[element("图2", index=None), element("图1", index=3)],
        Table=[element("表2", index=None), element("表1", index=2)],
    )

    question = normalize(response(question_info([raw_result]))).questions[0]

    assert question.question_text == "首\n末"
    assert question.recognized_answer == "前\n后"
    assert question.recognized_parse == "甲\n乙"
    assert [item.text for item in question.figures] == ["图1", "图2"]
    assert [item.text for item in question.tables] == ["表1", "表2"]


def test_empty_answer_and_parse_text_normalize_to_null() -> None:
    raw_result = result_list(
        Answer=[element("", index=0), element("", index=1)],
        Parse=[element(None, index=0), element("", index=1)],
    )

    question = normalize(response(question_info([raw_result]))).questions[0]

    assert question.recognized_answer is None
    assert question.recognized_parse is None


def test_full_text_keeps_question_options_and_table_but_excludes_answer_and_figure() -> None:
    raw_result = result_list(
        Question=[element("1. 题干", group_type="multiple-choice")],
        Option=[element("B.乙", index=2), element("A.甲", index=1)],
        Figure=[element("base64-or-crop-position", index=0)],
        Table=[element("", index=2), element("表格正文", index=1)],
        Answer=[element("A", index=0)],
        Parse=[element("答案解析", index=0)],
    )

    question = normalize(response(question_info([raw_result]))).questions[0]

    assert question.full_text == "1. 题干\nA.甲\nB.乙\n表格正文"
    assert "base64-or-crop-position" not in question.full_text
    assert "答案解析" not in question.full_text


def test_group_type_falls_back_through_official_element_groups() -> None:
    raw_result = result_list(
        Question=[element("1. 题干")],
        Option=[element("A.甲", group_type="fill-in-the-blank")],
        Answer=[element("A", group_type="arithmetic")],
    )

    question = normalize(response(question_info([raw_result]))).questions[0]

    assert question.raw_group_type == "fill-in-the-blank"
    assert question.question_type == "fill_blank"


def test_ignores_empty_groups_and_raises_when_no_valid_question_remains() -> None:
    empty = result_list(
        Question=[],
        Option=[],
        Figure=[],
        Table=[],
        Answer=[element("A")],
        Parse=[element("解析")],
    )

    with pytest.raises(NoQuestionDetected, match="未识别到有效题目"):
        normalize(response(question_info([empty])))

    blank_question = result_list(
        Question=[element("", index=0), element("", index=1)],
        Option=[],
        Figure=[],
        Table=[],
        Answer=[],
        Parse=[],
    )
    with pytest.raises(NoQuestionDetected, match="未识别到有效题目"):
        normalize(response(question_info([blank_question])))

    with pytest.raises(NoQuestionDetected, match="未识别到有效题目"):
        normalize(response(question_info([])))

    with pytest.raises(NoQuestionDetected, match="未识别到有效题目"):
        normalize(response(question_info(None)))

    with pytest.raises(NoQuestionDetected, match="未识别到有效题目"):
        normalize(response())


def test_final_schema_cannot_leak_provider_payload_or_future_answer_fields() -> None:
    actual = normalize(response(question_info([result_list()])))
    payload = actual.model_dump()
    serialized = json.dumps(payload, ensure_ascii=False)

    assert "ImageBase64" not in serialized
    assert "image_base64" not in serialized
    assert "secret-image-payload" not in serialized
    assert "correct_answer" not in serialized
    assert "confidence" not in serialized
    assert "ai_parse" not in serialized
    assert set(payload) == {
        "provider",
        "api_name",
        "request_id",
        "page_number",
        "question_count",
        "source",
        "warnings",
        "questions",
        "is_demo",
    }
