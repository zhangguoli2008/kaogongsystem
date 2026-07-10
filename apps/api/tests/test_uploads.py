from io import BytesIO

from PIL import Image

from app.models.base import Base
from app.models.upload import UploadedAsset


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
