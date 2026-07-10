from io import BytesIO
import asyncio

from fastapi import UploadFile
from PIL import Image
import pytest

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


def test_rejects_non_image(client):
    cookies = register(client, "upload-type@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("notes.txt", b"not an image", "text/plain")},
    )
    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_image_type"


def test_rejects_corrupted_image(client):
    cookies = register(client, "upload-corrupt@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.png", b"not an image", "image/png")},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "invalid_image"


def test_rejects_oversized_image_before_writing(client):
    cookies = register(client, "upload-size@example.com")
    client.app.state.settings.max_upload_bytes = 10
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.png", png_bytes(), "image/png")},
    )
    assert response.status_code == 413
    assert response.json()["code"] == "upload_too_large"


def test_rejects_unsupported_image_format(client):
    cookies = register(client, "upload-format@example.com")
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.gif", b"GIF89a", "image/gif")},
    )
    assert response.status_code == 415
    assert response.json()["code"] == "unsupported_image_type"


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

    download = client.get(f"/api/v1/uploads/{uploaded['id']}", cookies=first)
    assert download.status_code == 200
    assert download.content == png_bytes()
    assert download.headers["content-type"].startswith("image/png")

    second = register(client, "upload-second@example.com")
    assert client.get(f"/api/v1/uploads/{uploaded['id']}", cookies=second).status_code == 404


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
