from io import BytesIO
import asyncio
import base64
import hashlib
from pathlib import Path
from uuid import UUID

from fastapi import UploadFile
from PIL import Image
import pytest
from pypdf import PdfWriter
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base
from app.models.upload import UploadedAsset
from app.services.storage import InvalidFilename, InvalidImage, inspect_image, save_image


def register(client, email: str):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "strong-pass-123"},
    )
    assert response.status_code == 201, response.text
    return dict(response.cookies)


def png_bytes() -> bytes:
    image = Image.new("RGB", (4, 4), "white")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def image_bytes(image_format: str, *, size: tuple[int, int] = (640, 800)) -> bytes:
    image = Image.new("RGB", size, "white")
    output = BytesIO()
    image.save(output, format=image_format)
    return output.getvalue()


def pdf_bytes(*, page_count: int = 2) -> bytes:
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=612, height=792)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def upload_question_image(client, cookies, raw: bytes, *, filename="question.png"):
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": (filename, raw, "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_uploaded_asset_table_is_registered():
    assert "uploaded_assets" in Base.metadata.tables
    assert UploadedAsset.__tablename__ == "uploaded_assets"


@pytest.mark.parametrize(
    ("image_format", "canonical_mime", "suffix"),
    [
        ("JPEG", "image/jpeg", ".jpg"),
        ("PNG", "image/png", ".png"),
        ("BMP", "image/bmp", ".bmp"),
    ],
)
def test_accepts_supported_images_by_decoded_content(
    client, image_format, canonical_mime, suffix
):
    cookies = register(client, f"upload-{image_format.lower()}@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={
            "file": (
                "misleading.webp",
                image_bytes(image_format),
                "application/octet-stream",
            )
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["mime_type"] == canonical_mime
    assert payload["storage_name"].endswith(suffix)
    assert payload["file_kind"] == "image"
    assert payload["width"] == 640
    assert payload["height"] == 800
    assert payload["page_count"] is None
    assert payload["warnings"] == ["图片分辨率较低，可能影响文字识别准确率"]


def test_accepts_pdf_and_returns_page_count(client):
    cookies = register(client, "upload-pdf@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.jpg", pdf_bytes(page_count=2), "image/jpeg")},
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["mime_type"] == "application/pdf"
    assert payload["storage_name"].endswith(".pdf")
    assert payload["file_kind"] == "pdf"
    assert payload["page_count"] == 2
    assert payload["width"] is None
    assert payload["height"] is None
    assert isinstance(payload["warnings"], list)


@pytest.mark.parametrize(
    ("label", "raw"),
    [
        pytest.param("webp", image_bytes("WEBP"), id="webp"),
        pytest.param("gif", image_bytes("GIF"), id="gif"),
        pytest.param(
            "svg", b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', id="svg"
        ),
        pytest.param(
            "heic",
            b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00heicmif1",
            id="heic",
        ),
        pytest.param("tiff", image_bytes("TIFF"), id="tiff"),
    ],
)
def test_rejects_unsupported_content_even_with_supported_declaration(client, label, raw):
    cookies = register(client, f"upload-{label}@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.png", raw, "image/png")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "OCR_UNSUPPORTED_FILE_TYPE"
    assert not client.app.state.settings.upload_dir.exists()


def test_rejects_corrupted_supported_image_by_real_signature(client):
    cookies = register(client, "upload-corrupt-signature@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.png", b"\x89PNG\r\n\x1a\ntruncated", "image/png")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "OCR_IMAGE_DECODE_FAILED"


def test_rejects_empty_file(client):
    cookies = register(client, "upload-empty@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.png", b"", "image/png")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "OCR_EMPTY_FILE"
    assert not client.app.state.settings.upload_dir.exists()


def test_rejects_empty_filename(client):
    cookies = register(client, "upload-empty-name@example.com")
    boundary = "empty-filename-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename=""\r\n'
        "Content-Type: image/png\r\n\r\n"
    ).encode() + png_bytes() + f"\r\n--{boundary}--\r\n".encode()
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        content=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "OCR_INVALID_FILENAME"
    assert not client.app.state.settings.upload_dir.exists()


def test_rejects_invalid_pdf_with_pdf_signature(client):
    cookies = register(client, "upload-invalid-pdf@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.pdf", b"%PDF-1.7\ntruncated", "application/pdf")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "OCR_INVALID_PDF"
    assert not client.app.state.settings.upload_dir.exists()


def test_rejects_unknown_random_bytes_as_unsupported(client):
    cookies = register(client, "upload-random@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.png", b"random bytes", "image/png")},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "OCR_UNSUPPORTED_FILE_TYPE"
    assert not client.app.state.settings.upload_dir.exists()


def test_rejects_when_actual_base64_payload_exceeds_ten_mib(client):
    cookies = register(client, "upload-base64-size@example.com")
    raw = image_bytes("BMP", size=(1800, 1500))
    limit = 10 * 1024 * 1024
    assert len(raw) < limit
    assert len(base64.b64encode(raw)) > limit

    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.bmp", raw, "image/bmp")},
    )

    assert response.status_code == 413
    assert response.json()["code"] == "OCR_FILE_TOO_LARGE"
    assert not client.app.state.settings.upload_dir.exists()


def test_accepts_when_actual_base64_payload_equals_ten_mib(client):
    cookies = register(client, "upload-base64-boundary@example.com")
    limit = 10 * 1024 * 1024
    raw_size = limit // 4 * 3
    raw = png_bytes().ljust(raw_size, b"\x00")
    assert len(base64.b64encode(raw)) == limit

    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.png", raw, "image/png")},
    )

    assert response.status_code == 201, response.text


def test_save_image_calculates_sha256(client):
    raw = png_bytes()
    upload = UploadFile(file=BytesIO(raw), filename="question.png")

    stored = asyncio.run(
        save_image(
            upload,
            upload_dir=client.app.state.settings.upload_dir,
            max_upload_bytes=client.app.state.settings.max_upload_bytes,
        )
    )

    assert stored.sha256 == hashlib.sha256(raw).hexdigest()
    assert (client.app.state.settings.upload_dir / stored.storage_name).read_bytes() == raw


def test_rejects_non_image(client):
    cookies = register(client, "upload-type@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("notes.txt", b"not an image", "text/plain")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "OCR_UNSUPPORTED_FILE_TYPE"


def test_rejects_oversized_image_before_writing(client):
    cookies = register(client, "upload-size@example.com")
    client.app.state.settings.max_upload_bytes = 10
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.png", png_bytes(), "image/png")},
    )
    assert response.status_code == 413
    assert response.json()["code"] == "OCR_FILE_TOO_LARGE"
    assert not client.app.state.settings.upload_dir.exists()


def test_rejects_unsupported_image_format(client):
    cookies = register(client, "upload-format@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.gif", b"GIF89a", "image/gif")},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "OCR_UNSUPPORTED_FILE_TYPE"


def test_rejects_original_filename_that_exceeds_metadata_limit(client):
    cookies = register(client, "upload-name@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("a" * 501, png_bytes(), "image/png")},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "filename_too_long"


def test_rejects_control_characters_in_original_filename(client):
    upload = UploadFile(file=BytesIO(png_bytes()), filename="question\x00.png")
    with pytest.raises(InvalidFilename):
        asyncio.run(
            save_image(
                upload,
                upload_dir=client.app.state.settings.upload_dir,
                max_upload_bytes=client.app.state.settings.max_upload_bytes,
            )
        )


def test_rejects_images_above_pixel_safety_limit():
    image = Image.new("1", (5001, 5001), 0)
    output = BytesIO()
    image.save(output, format="PNG")
    with pytest.raises(InvalidImage):
        inspect_image(output.getvalue())


def test_upload_download_is_scoped_and_uses_random_extension(client):
    first = register(client, "upload-first@example.com")
    uploaded = upload_question_image(client, first, png_bytes(), filename="../../evil.txt")

    assert uploaded["mime_type"] == "image/png"
    assert uploaded["original_name"] == "../../evil.txt"
    assert uploaded["storage_name"].endswith(".png")
    assert "/" not in uploaded["storage_name"]
    storage_id = UUID(Path(uploaded["storage_name"]).stem)
    assert storage_id.version == 4

    download = client.get(f"/api/v1/uploads/{uploaded['id']}", cookies=first)
    assert download.status_code == 200
    assert download.content == png_bytes()
    assert download.headers["content-type"].startswith("image/png")

    second = register(client, "upload-second@example.com")
    assert client.get(f"/api/v1/uploads/{uploaded['id']}", cookies=second).status_code == 404


def test_database_commit_failure_removes_persisted_file(client, monkeypatch):
    cookies = register(client, "upload-commit-failure@example.com")

    async def fail_commit(_session):
        raise RuntimeError("commit failed")

    monkeypatch.setattr(AsyncSession, "commit", fail_commit)

    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.png", png_bytes(), "image/png")},
    )

    assert response.status_code == 500
    upload_dir = client.app.state.settings.upload_dir
    assert upload_dir.is_dir()
    assert list(upload_dir.iterdir()) == []


def test_demo_ocr_returns_editable_fields(client):
    cookies = register(client, "upload-ocr@example.com")
    uploaded = upload_question_image(client, cookies, png_bytes())
    response = client.post(
        "/api/v1/ocr", cookies=cookies, json={"upload_id": uploaded["id"]}
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["is_demo"] is True
    assert payload["stem"]
    assert len(payload["options"]) == 4


def test_ocr_is_rate_limited_per_user(client):
    cookies = register(client, "upload-ocr-rate@example.com")
    uploaded = upload_question_image(client, cookies, png_bytes())
    for _ in range(10):
        response = client.post(
            "/api/v1/ocr", cookies=cookies, json={"upload_id": uploaded["id"]}
        )
        assert response.status_code == 200
    response = client.post(
        "/api/v1/ocr", cookies=cookies, json={"upload_id": uploaded["id"]}
    )
    assert response.status_code == 429
    assert response.json()["code"] == "provider_rate_limited"


def test_ocr_provider_error_reuses_response_request_id(client, caplog, monkeypatch):
    cookies = register(client, "upload-ocr-request-id@example.com")
    uploaded = upload_question_image(client, cookies, png_bytes())

    class FailingProvider:
        async def ocr(self, image_bytes, mime_type, request_id=None):
            del image_bytes, mime_type
            import logging

            logging.getLogger("test.provider").warning(
                "provider failure", extra={"local_request_id": request_id}
            )
            from app.core.errors import APIError

            raise APIError(502, "provider_connection_error", "OCR 服务连接失败")

    monkeypatch.setattr(
        "app.api.routes.providers.get_provider", lambda settings: FailingProvider()
    )
    with caplog.at_level("WARNING", logger="test.provider"):
        response = client.post(
            "/api/v1/ocr", cookies=cookies, json={"upload_id": uploaded["id"]}
        )

    assert response.status_code == 502
    request_id = response.json()["request_id"]
    assert any(
        getattr(record, "local_request_id", None) == request_id
        for record in caplog.records
    )
