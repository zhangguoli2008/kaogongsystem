"""Pure normalization from Tencent QuestionSplitOCR data to API schemas."""

from __future__ import annotations

import re
from collections.abc import Iterable
from uuid import uuid4

from app.schemas.ocr import (
    OcrMedia,
    OcrOption,
    OcrPoint,
    OcrPolygon,
    OcrQuestion,
    OcrQuestionType,
    OcrResult,
    OcrSource,
    OcrTextElement,
)
from app.services.ocr.types import Element, Point, Polygon, Response, ResultList
from app.services.ocr_contract import API_NAME


class NoQuestionDetected(ValueError):
    """Raised when Tencent returns no usable question group."""


_QUESTION_TYPE_MAP: dict[str, OcrQuestionType] = {
    "multiple-choice": "multiple_choice_unknown",
    "fill-in-the-blank": "fill_blank",
    "problem-solving": "problem_solving",
    "arithmetic": "arithmetic",
}
_QUESTION_NUMBER_PATTERNS = (
    re.compile(r"^\s*第(?P<number>\d+)题"),
    re.compile(r"^\s*[（(](?P<number>\d+)[）)]"),
    re.compile(r"^\s*(?P<number>\d+)[.、．）]"),
)
_OPTION_WITH_DELIMITER = re.compile(
    r"^\s*(?P<label>[A-Za-zＡ-Ｚａ-ｚ])(?:[.、．:：]|\s)+(?P<text>.*)$",
    re.DOTALL,
)
_OPTION_WITH_PARENS = re.compile(
    r"^\s*[（(]\s*(?P<label>[A-Za-zＡ-Ｚａ-ｚ])\s*[）)]\s*(?P<text>.*)$",
    re.DOTALL,
)
_FULLWIDTH_UPPER_A = ord("Ａ")
_FULLWIDTH_UPPER_Z = ord("Ｚ")
_FULLWIDTH_LOWER_A = ord("ａ")
_FULLWIDTH_LOWER_Z = ord("ｚ")
_ASCII_UPPER_A = ord("A")
_ASCII_LOWER_A = ord("a")


def _sort_by_index(items: Iterable[Element]) -> list[Element]:
    return sorted(
        items,
        key=lambda item: (
            item.index is None,
            item.index if item.index is not None else 0,
        ),
    )


def _point(value: Point | None) -> OcrPoint | None:
    if value is None:
        return None
    return OcrPoint(x=value.x, y=value.y)


def _polygon(value: Polygon | None) -> OcrPolygon | None:
    if value is None:
        return None
    return OcrPolygon(
        left_top=_point(value.left_top),
        right_top=_point(value.right_top),
        right_bottom=_point(value.right_bottom),
        left_bottom=_point(value.left_bottom),
    )


def _text_element(value: Element) -> OcrTextElement:
    return OcrTextElement(
        index=value.index,
        text=value.text,
        coord=_polygon(value.coord),
    )


def _media(value: Element) -> OcrMedia:
    return OcrMedia(
        index=value.index,
        text=value.text,
        coord=_polygon(value.coord),
    )


def _join_text(elements: Iterable[Element]) -> str:
    return "\n".join(
        element.text for element in _sort_by_index(elements) if element.text is not None
    )


def _recognized_text(elements: Iterable[Element]) -> str | None:
    text = _join_text(elements)
    return text if text.strip() else None


def _question_number(value: str | None) -> str | None:
    if value is None:
        return None
    for pattern in _QUESTION_NUMBER_PATTERNS:
        match = pattern.match(value)
        if match:
            return match.group("number")
    return None


def _ascii_option_label(value: str) -> str:
    codepoint = ord(value)
    if _FULLWIDTH_UPPER_A <= codepoint <= _FULLWIDTH_UPPER_Z:
        return chr(_ASCII_UPPER_A + codepoint - _FULLWIDTH_UPPER_A)
    if _FULLWIDTH_LOWER_A <= codepoint <= _FULLWIDTH_LOWER_Z:
        return chr(_ASCII_LOWER_A + codepoint - _FULLWIDTH_LOWER_A).upper()
    return value.upper()


def _fallback_option_label(position: int) -> str:
    return chr(_ASCII_UPPER_A + position)


def _option(value: Element, position: int, warnings: list[str]) -> OcrOption:
    raw_text = value.text or ""
    match = _OPTION_WITH_PARENS.fullmatch(raw_text) or _OPTION_WITH_DELIMITER.fullmatch(
        raw_text
    )
    if match:
        label = _ascii_option_label(match.group("label"))
        text = match.group("text")
    else:
        label = _fallback_option_label(position)
        text = raw_text
        warnings.append(f"选项“{raw_text}”无法识别标签，已按顺序使用 {label}")
    return OcrOption(
        label=label,
        text=text,
        raw_text=raw_text,
        coord=_polygon(value.coord),
    )


def _normalize_question(
    raw: ResultList,
    *,
    index: int,
    source_info_index: int,
) -> OcrQuestion | None:
    question_items = _sort_by_index(raw.question or [])
    option_items = _sort_by_index(raw.option or [])
    figure_items = _sort_by_index(raw.figure or [])
    table_items = _sort_by_index(raw.table or [])

    question_text = _join_text(question_items)
    has_question_text = any(
        value.text is not None and bool(value.text.strip()) for value in question_items
    )
    if not (has_question_text or option_items or figure_items or table_items):
        return None

    warnings: list[str] = []
    options = [
        _option(value, position, warnings)
        for position, value in enumerate(option_items)
    ]
    table_text = [value.text for value in table_items if value.text]
    full_text = "\n".join(
        part
        for part in (
            question_text,
            *(option.raw_text for option in options),
            *table_text,
        )
        if part
    )
    raw_group_type = _first_group_type(
        question_items,
        option_items,
        figure_items,
        table_items,
        _sort_by_index(raw.answer or []),
        _sort_by_index(raw.parse or []),
    )
    return OcrQuestion(
        temporary_id=str(uuid4()),
        index=index,
        source_info_index=source_info_index,
        question_number=_question_number(question_text),
        question_type=_QUESTION_TYPE_MAP.get(raw_group_type or "", "unknown"),
        question_text=question_text,
        full_text=full_text,
        question_elements=[_text_element(value) for value in question_items],
        options=options,
        figures=[_media(value) for value in figure_items],
        tables=[_media(value) for value in table_items],
        recognized_answer=_recognized_text(raw.answer or []),
        recognized_parse=_recognized_text(raw.parse or []),
        coord=[polygon for value in (raw.coord or []) if (polygon := _polygon(value))],
        raw_group_type=raw_group_type,
        warnings=warnings,
    )


def _first_group_type(*groups: Iterable[Element]) -> str | None:
    for group in groups:
        for element in group:
            if element.group_type:
                return element.group_type
    return None


def normalize_question_split_response(
    raw_model: Response,
    *,
    provider: str,
    file_id: str,
    page_number: int,
    is_demo: bool = False,
) -> OcrResult:
    """Normalize one Tencent response without retaining its source image bytes."""

    questions: list[OcrQuestion] = []
    for source_info_index, info in enumerate(raw_model.question_info):
        for raw_question in info.result_list or []:
            question = _normalize_question(
                raw_question,
                index=len(questions),
                source_info_index=source_info_index,
            )
            if question is not None:
                questions.append(question)

    if not questions:
        raise NoQuestionDetected("未识别到有效题目")

    first_info = raw_model.question_info[0]
    source = OcrSource(
        file_id=file_id,
        image_url=f"/uploads/{file_id}",
        original_width=first_info.org_width,
        original_height=first_info.org_height,
        processed_width=first_info.width,
        processed_height=first_info.height,
        angle=first_info.angle,
    )
    return OcrResult(
        provider=provider,
        api_name=API_NAME,
        request_id=raw_model.request_id,
        page_number=page_number,
        question_count=len(questions),
        source=source,
        warnings=[],
        questions=questions,
        is_demo=is_demo,
    )
