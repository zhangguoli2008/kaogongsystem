from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Final
from uuid import uuid4

from fastapi import UploadFile
from PIL import Image, UnidentifiedImageError


ALLOWED_FORMATS: Final[dict[str, tuple[str, str]]] = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}
ALLOWED_MIME_TYPES: Final[frozenset[str]] = frozenset(
    mime for mime, _extension in ALLOWED_FORMATS.values()
)


class UnsupportedImageType(Exception):
    """The image format is not one of the formats accepted by the service."""


class InvalidImage(Exception):
    """The payload claims to be an image but cannot be decoded safely."""


class UploadTooLarge(Exception):
    """The payload exceeded the configured upload limit."""


def inspect_image(raw: bytes) -> tuple[str, str]:
    """Verify and fully decode an image, returning canonical MIME and suffix."""

    try:
        # verify() checks the file structure without decoding pixels.  A second
        # open is required because verify() invalidates the image object.
        with Image.open(BytesIO(raw)) as image:
            image.verify()
        with Image.open(BytesIO(raw)) as image:
            detected = image.format
            image.load()
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        OSError,
        ValueError,
        SyntaxError,
    ) as exc:
        raise InvalidImage from exc

    if detected not in ALLOWED_FORMATS:
        raise UnsupportedImageType
    return ALLOWED_FORMATS[detected]


async def save_image(
    file: UploadFile,
    *,
    upload_dir: Path,
    max_upload_bytes: int,
) -> tuple[str, str, str, int]:
    """Validate and persist an uploaded image.

    The returned tuple is ``(storage_name, canonical_mime, original_name,
    size_bytes)``.  Files are addressed solely by a random UUID and canonical
    extension; the client-provided name never becomes part of a path.
    """

    if file.content_type and file.content_type not in ALLOWED_MIME_TYPES:
        raise UnsupportedImageType

    raw = await file.read(max_upload_bytes + 1)
    if len(raw) > max_upload_bytes:
        raise UploadTooLarge

    mime_type, extension = inspect_image(raw)
    storage_name = f"{uuid4().hex}{extension}"
    upload_dir.mkdir(parents=True, exist_ok=True)
    target = upload_dir / storage_name
    # UUID names cannot contain path separators; resolve defensively in case a
    # future naming change ever violates that invariant.
    if target.parent.resolve() != upload_dir.resolve():
        raise InvalidImage
    target.write_bytes(raw)
    return storage_name, mime_type, file.filename or "upload", len(raw)


def image_path(upload_dir: Path, storage_name: str) -> Path:
    """Resolve a storage name under ``upload_dir`` without path traversal."""

    candidate = (upload_dir / storage_name).resolve()
    root = upload_dir.resolve()
    if candidate.parent != root or candidate.name != storage_name:
        raise ValueError("invalid storage name")
    return candidate
