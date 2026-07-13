from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Final
from uuid import uuid4
import warnings

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
MAX_IMAGE_PIXELS: Final[int] = 25_000_000
MAX_ORIGINAL_NAME_BYTES: Final[int] = 500


class UnsupportedImageType(Exception):
    """The image format is not one of the formats accepted by the service."""


class InvalidImage(Exception):
    """The payload claims to be an image but cannot be decoded safely."""


class UploadTooLarge(Exception):
    """The payload exceeded the configured upload limit."""


class FilenameTooLong(Exception):
    """The client-provided display name exceeds the metadata limit."""


class InvalidFilename(Exception):
    """The client-provided display name contains control characters."""


def inspect_image(raw: bytes) -> tuple[str, str]:
    """Verify and fully decode an image, returning canonical MIME and suffix."""

    try:
        # Treat Pillow's decompression-bomb warning as an error.  The explicit
        # dimension check also enforces a lower, application-specific limit
        # where Pillow itself would otherwise only emit a warning at a much
        # larger default threshold.
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            # verify() checks the file structure without decoding pixels.  A
            # second open is required because verify() invalidates the object.
            with Image.open(BytesIO(raw)) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise InvalidImage
                image.verify()
            with Image.open(BytesIO(raw)) as image:
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise InvalidImage
                detected = image.format
                image.load()
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

    original_name = file.filename or "upload"
    if any(ord(char) < 32 or ord(char) == 127 for char in original_name):
        raise InvalidFilename
    if len(original_name.encode("utf-8")) > MAX_ORIGINAL_NAME_BYTES:
        raise FilenameTooLong

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
    return storage_name, mime_type, original_name, len(raw)


def image_path(upload_dir: Path, storage_name: str) -> Path:
    """Resolve a storage name under ``upload_dir`` without path traversal."""

    candidate = (upload_dir / storage_name).resolve()
    root = upload_dir.resolve()
    if candidate.parent != root or candidate.name != storage_name:
        raise ValueError("invalid storage name")
    return candidate
