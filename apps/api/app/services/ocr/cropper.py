"""In-memory, coordinate-safe crop generation for normalized OCR results."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from io import BytesIO
import math
from typing import Literal

from PIL import Image

from app.schemas.ocr import OcrPolygon, OcrQuestion, OcrResult
from app.services.ocr.types import Response
from app.services.storage import InvalidImage, UnsupportedImageType, inspect_image


CropKind = Literal["question", "figure", "table", "option"]


@dataclass(frozen=True)
class CropArtifact:
    kind: CropKind
    question_position: int
    item_position: int | None
    png_bytes: bytes
    original_name: str


@dataclass(frozen=True)
class CropBatch:
    artifacts: tuple[CropArtifact, ...]
    warnings: tuple[str, ...]


def _decode_image(raw: bytes) -> Image.Image:
    inspect_image(raw)
    with Image.open(BytesIO(raw)) as image:
        image.load()
        return image.convert("RGB")


def _corrected_image(encoded: str | None) -> Image.Image | None:
    if not encoded:
        return None
    try:
        raw = base64.b64decode(encoded, validate=True)
        return _decode_image(raw)
    except (ValueError, TypeError, InvalidImage, UnsupportedImageType, OSError):
        return None


def _polygon_points(polygon: OcrPolygon | None) -> list[tuple[int, int]]:
    if polygon is None:
        return []
    return [
        (point.x, point.y)
        for point in (
            polygon.left_top,
            polygon.right_top,
            polygon.right_bottom,
            polygon.left_bottom,
        )
        if point is not None
    ]


def _question_polygons(question: OcrQuestion) -> list[OcrPolygon]:
    if question.coord:
        return question.coord
    candidates = [
        *(element.coord for element in question.question_elements),
        *(option.coord for option in question.options),
        *(media.coord for media in question.figures),
        *(media.coord for media in question.tables),
    ]
    return [polygon for polygon in candidates if polygon is not None]


def _png_crop(
    image: Image.Image,
    polygons: list[OcrPolygon],
    *,
    label: str,
    warnings: list[str],
) -> bytes | None:
    points = [point for polygon in polygons for point in _polygon_points(polygon)]
    if not points:
        warnings.append(f"{label}缺少有效坐标，未生成裁剪图")
        return None
    left = math.floor(min(point[0] for point in points))
    top = math.floor(min(point[1] for point in points))
    right = math.ceil(max(point[0] for point in points))
    bottom = math.ceil(max(point[1] for point in points))
    clamped = (
        max(0, min(image.width, left)),
        max(0, min(image.height, top)),
        max(0, min(image.width, right)),
        max(0, min(image.height, bottom)),
    )
    if clamped != (left, top, right, bottom):
        warnings.append(f"{label}坐标越界，已安全限制在图片范围内")
    if clamped[2] <= clamped[0] or clamped[3] <= clamped[1]:
        warnings.append(f"{label}坐标没有有效面积，未生成裁剪图")
        return None
    with image.crop(clamped) as crop:
        output = BytesIO()
        crop.save(output, format="PNG")
        return output.getvalue()


def _artifact(
    *,
    image: Image.Image,
    polygons: list[OcrPolygon],
    kind: CropKind,
    question_position: int,
    item_position: int | None,
    warnings: list[str],
) -> CropArtifact | None:
    names = {
        "question": "整题",
        "figure": "图形",
        "table": "表格",
        "option": "选项",
    }
    label = names[kind]
    png = _png_crop(image, polygons, label=label, warnings=warnings)
    if png is None:
        return None
    item_suffix = "" if item_position is None else f"-{item_position + 1}"
    return CropArtifact(
        kind=kind,
        question_position=question_position,
        item_position=item_position,
        png_bytes=png,
        original_name=(
            f"ocr-question-{question_position + 1}-{kind}{item_suffix}.png"
        ),
    )


def build_crop_batch(
    raw_response: Response,
    result: OcrResult,
    *,
    source_raw: bytes,
    source_file_kind: str,
) -> CropBatch:
    """Build all PNG crops without persisting source or corrected image bytes."""

    source_image = _decode_image(source_raw) if source_file_kind == "image" else None
    corrected: dict[int, Image.Image | None] = {}
    global_warnings: list[str] = []
    artifacts: list[CropArtifact] = []
    try:
        for info_index, info in enumerate(raw_response.question_info or []):
            corrected[info_index] = _corrected_image(info.image_base64)
            if info.image_base64 and corrected[info_index] is None:
                global_warnings.append("OCR 矫正图无效，已忽略该图")

        if source_file_kind == "pdf" and not any(corrected.values()):
            global_warnings.append("PDF 未返回可用矫正图，已保留原文件")
            return CropBatch(artifacts=(), warnings=tuple(global_warnings))

        for question_position, question in enumerate(result.questions):
            image = corrected.get(question.source_info_index) or source_image
            if image is None:
                question.warnings.append("未找到可用图片，未生成裁剪图")
                continue

            question_artifact = _artifact(
                image=image,
                polygons=_question_polygons(question),
                kind="question",
                question_position=question_position,
                item_position=None,
                warnings=question.warnings,
            )
            if question_artifact is not None:
                artifacts.append(question_artifact)

            for kind, items in (
                ("figure", question.figures),
                ("table", question.tables),
            ):
                for item_position, item in enumerate(items):
                    artifact = _artifact(
                        image=image,
                        polygons=[item.coord] if item.coord is not None else [],
                        kind=kind,
                        question_position=question_position,
                        item_position=item_position,
                        warnings=question.warnings,
                    )
                    if artifact is not None:
                        artifacts.append(artifact)

            if question.figures:
                for item_position, option in enumerate(question.options):
                    artifact = _artifact(
                        image=image,
                        polygons=[option.coord] if option.coord is not None else [],
                        kind="option",
                        question_position=question_position,
                        item_position=item_position,
                        warnings=question.warnings,
                    )
                    if artifact is not None:
                        artifacts.append(artifact)

        return CropBatch(
            artifacts=tuple(artifacts),
            warnings=tuple(global_warnings),
        )
    finally:
        if source_image is not None:
            source_image.close()
        for image in corrected.values():
            if image is not None:
                image.close()
