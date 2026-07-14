from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
from io import BytesIO
from pathlib import Path
from typing import Final, Iterator
from uuid import uuid4
import warnings

from fastapi import UploadFile
from PIL import Image, ImageChops, ImageFilter, ImageStat, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PyPdfError


ALLOWED_FORMATS: Final[dict[str, tuple[str, str]]] = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "BMP": ("image/bmp", ".bmp"),
}
MAX_IMAGE_PIXELS: Final[int] = 25_000_000
MAX_ORIGINAL_NAME_BYTES: Final[int] = 500
MIN_OCR_SHORT_SIDE: Final[int] = 600
MIN_OCR_LONG_SIDE: Final[int] = 800
QUALITY_SAMPLE_SIZE: Final[tuple[int, int]] = (256, 256)
DARK_MEAN_THRESHOLD: Final[float] = 40.0
BRIGHT_MEAN_THRESHOLD: Final[float] = 245.0
BLUR_EDGE_THRESHOLD: Final[float] = 3.0


class UnsupportedImageType(Exception):
    """The decoded content is not one of the accepted file types."""


class InvalidImage(Exception):
    """A payload with a supported image signature cannot be fully decoded."""


class InvalidPdf(Exception):
    """A payload with a PDF signature cannot be parsed safely."""


class EmptyFile(Exception):
    """The uploaded payload has no content."""


class UploadTooLarge(Exception):
    """The Base64-encoded payload exceeded the configured upload limit."""


class FilenameTooLong(Exception):
    """The client-provided display name exceeds the metadata limit."""


class InvalidFilename(Exception):
    """The client-provided display name contains control characters."""


class EmptyFilename(InvalidFilename):
    """The client did not provide a meaningful display name."""


@dataclass(frozen=True)
class FileInspection:
    mime_type: str
    extension: str
    file_kind: str
    width: int | None = None
    height: int | None = None
    page_count: int | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class StoredUpload:
    storage_name: str
    mime_type: str
    original_name: str
    size_bytes: int
    file_kind: str
    width: int | None
    height: int | None
    page_count: int | None
    warnings: tuple[str, ...]
    sha256: str

    def __iter__(self) -> Iterator[str | int]:
        """Preserve the legacy four-value unpacking contract."""

        yield self.storage_name
        yield self.mime_type
        yield self.original_name
        yield self.size_bytes


@dataclass(frozen=True)
class StoredGeneratedPNG:
    storage_name: str
    original_name: str
    size_bytes: int


def _quality_warnings(image: Image.Image) -> tuple[str, ...]:
    warnings_found: list[str] = []
    short_side, long_side = sorted(image.size)
    if short_side < MIN_OCR_SHORT_SIDE or long_side < MIN_OCR_LONG_SIDE:
        warnings_found.append("图片分辨率可能偏低，建议至少使用 600×800 像素")

    sample = image.convert("L")
    sample.thumbnail(QUALITY_SAMPLE_SIZE, Image.Resampling.BILINEAR)
    mean_brightness = ImageStat.Stat(sample).mean[0]
    if mean_brightness < DARK_MEAN_THRESHOLD:
        warnings_found.append("图片可能过暗，建议提高光线或亮度")
    elif mean_brightness > BRIGHT_MEAN_THRESHOLD:
        warnings_found.append("图片可能过曝，建议避免强光并重新拍摄")
    else:
        blurred = sample.filter(ImageFilter.GaussianBlur(radius=2))
        edge_strength = ImageStat.Stat(ImageChops.difference(sample, blurred)).mean[0]
        if edge_strength < BLUR_EDGE_THRESHOLD:
            warnings_found.append("图片可能模糊，建议重新拍摄或扫描")
    return tuple(warnings_found)


def _inspect_supported_image(raw: bytes) -> FileInspection:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw)) as image:
                width, height = image.size
                if width * height > MAX_IMAGE_PIXELS:
                    raise InvalidImage
                image.verify()
            with Image.open(BytesIO(raw)) as image:
                width, height = image.size
                if width * height > MAX_IMAGE_PIXELS:
                    raise InvalidImage
                detected = image.format
                image.load()
                quality_warnings = _quality_warnings(image)
    except (
        UnidentifiedImageError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
        OSError,
        ValueError,
        SyntaxError,
    ) as exc:
        raise InvalidImage from exc

    if detected not in ALLOWED_FORMATS:
        raise UnsupportedImageType
    mime_type, extension = ALLOWED_FORMATS[detected]
    return FileInspection(
        mime_type=mime_type,
        extension=extension,
        file_kind="image",
        width=width,
        height=height,
        warnings=quality_warnings,
    )


def inspect_image(raw: bytes) -> tuple[str, str]:
    """Verify and fully decode an image, returning canonical MIME and suffix."""

    inspection = _inspect_supported_image(raw)
    return inspection.mime_type, inspection.extension


def _inspect_pdf(raw: bytes) -> FileInspection:
    try:
        with BytesIO(raw) as stream:
            reader = PdfReader(stream)
            page_count = len(reader.pages)
    except (PyPdfError, OSError, ValueError, TypeError) as exc:
        raise InvalidPdf from exc
    if page_count < 1:
        raise InvalidPdf
    return FileInspection(
        mime_type="application/pdf",
        extension=".pdf",
        file_kind="pdf",
        page_count=page_count,
    )


def _has_supported_image_signature(raw: bytes) -> bool:
    return (
        raw.startswith(b"\x89PNG\r\n\x1a\n")
        or raw.startswith(b"\xff\xd8\xff")
        or raw.startswith(b"BM")
    )


def _inspect_file(raw: bytes) -> FileInspection:
    if raw.startswith(b"%PDF-"):
        return _inspect_pdf(raw)
    if _has_supported_image_signature(raw):
        return _inspect_supported_image(raw)
    raise UnsupportedImageType


def inspect_file(raw: bytes) -> FileInspection:
    """Fully decode a stored upload and return canonical content metadata."""

    if not raw:
        raise EmptyFile
    return _inspect_file(raw)


async def save_image(
    file: UploadFile,
    *,
    upload_dir: Path,
    max_upload_bytes: int,
) -> StoredUpload:
    """Validate and persist a question image or PDF by decoded content."""

    original_name = file.filename
    if original_name is None or not original_name.strip():
        raise EmptyFilename
    if any(ord(char) < 32 or ord(char) == 127 for char in original_name):
        raise InvalidFilename
    if len(original_name.encode("utf-8")) > MAX_ORIGINAL_NAME_BYTES:
        raise FilenameTooLong

    raw = await file.read(max_upload_bytes + 1)
    if not raw:
        raise EmptyFile
    if len(base64.b64encode(raw)) > max_upload_bytes:
        raise UploadTooLarge

    inspection = _inspect_file(raw)
    sha256 = hashlib.sha256(raw).hexdigest()
    storage_name = f"{uuid4().hex}{inspection.extension}"
    target = upload_dir / storage_name
    upload_dir.mkdir(parents=True, exist_ok=True)
    if target.parent.resolve() != upload_dir.resolve():
        raise InvalidImage
    try:
        target.write_bytes(raw)
    except Exception:
        target.unlink(missing_ok=True)
        raise

    return StoredUpload(
        storage_name=storage_name,
        mime_type=inspection.mime_type,
        original_name=original_name,
        size_bytes=len(raw),
        file_kind=inspection.file_kind,
        width=inspection.width,
        height=inspection.height,
        page_count=inspection.page_count,
        warnings=inspection.warnings,
        sha256=sha256,
    )


def image_path(upload_dir: Path, storage_name: str) -> Path:
    """Resolve a storage name under ``upload_dir`` without path traversal."""

    candidate = (upload_dir / storage_name).resolve()
    root = upload_dir.resolve()
    if candidate.parent != root or candidate.name != storage_name:
        raise ValueError("invalid storage name")
    return candidate


def save_generated_png(
    raw: bytes,
    *,
    upload_dir: Path,
    original_name: str,
    storage_name: str | None = None,
) -> StoredGeneratedPNG:
    """Validate and safely persist a server-generated PNG crop."""

    mime_type, extension = inspect_image(raw)
    if mime_type != "image/png" or extension != ".png":
        raise InvalidImage
    resolved_storage_name = storage_name or f"{uuid4().hex}.png"
    target = image_path(upload_dir, resolved_storage_name)
    upload_dir.mkdir(parents=True, exist_ok=True)
    try:
        target.write_bytes(raw)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    return StoredGeneratedPNG(
        storage_name=resolved_storage_name,
        original_name=original_name,
        size_bytes=len(raw),
    )
