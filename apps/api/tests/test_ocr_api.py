from __future__ import annotations

import base64
import logging
from io import BytesIO

from PIL import Image
import pytest
from pypdf import PdfWriter

from app.core.errors import APIError
from app.schemas.ocr import OcrQuestion, OcrResult, OcrSource
from app.services.ocr.errors import OCRProviderError
from app.services.ocr.service import OCRService
from app.services.ocr.tencent import TencentOCRProvider
from app.services.ocr.types import Response


def register(client, email: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "strong-pass-123"},
    )
    assert response.status_code == 201, response.text
    return dict(response.cookies)


def image_bytes(color: str = "white") -> bytes:
    image = Image.new("RGB", (80, 100), color)
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def upload_image(client, cookies, *, color: str = "white") -> dict[str, object]:
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("question.png", image_bytes(color), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def upload_pdf(client, cookies) -> dict[str, object]:
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=612, height=792)
    output = BytesIO()
    writer.write(output)
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={"file": ("questions.pdf", output.getvalue(), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def result_for(file_id: str, *, page_number: int = 1) -> OcrResult:
    return OcrResult(
        provider="spy",
        api_name="QuestionSplitOCR",
        request_id="provider-request-1",
        page_number=page_number,
        question_count=1,
        source=OcrSource(file_id=file_id, image_url=f"/uploads/{file_id}"),
        questions=[
            OcrQuestion(
                temporary_id="temporary-1",
                source_info_index=0,
                question_type="unknown",
                question_text="1. 测试题",
                full_text="1. 测试题",
            )
        ],
        is_demo=True,
    )


class SpyService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def recognize(
        self,
        session,
        *,
        user_id: str,
        asset,
        pdf_page_number: int,
        local_request_id: str,
    ) -> OcrResult:
        self.calls.append(
            {
                "session": session,
                "user_id": user_id,
                "asset": asset,
                "pdf_page_number": pdf_page_number,
                "local_request_id": local_request_id,
            }
        )
        return result_for(asset.id, page_number=pdf_page_number)


class RaisingService:
    def __init__(self, error: APIError) -> None:
        self.error = error
        self.calls = 0

    async def recognize(self, *args, **kwargs) -> OcrResult:
        del args, kwargs
        self.calls += 1
        raise self.error


class CountingProvider:
    name = "counting"
    is_demo = True
    is_configured = True

    def __init__(self, *, include_processed_image: bool = False) -> None:
        self.calls = 0
        self.include_processed_image = include_processed_image

    async def recognize_questions(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        pdf_page_number: int = 1,
    ) -> Response:
        del file_bytes, filename, content_type, pdf_page_number
        self.calls += 1
        info: dict[str, object] = {
            "Width": 80,
            "Height": 100,
            "OrgWidth": 80,
            "OrgHeight": 100,
            "ResultList": [
                {
                    "Question": [
                        {
                            "Index": 0,
                            "Text": "1. API 集成测试题",
                            "GroupType": "multiple-choice",
                        }
                    ],
                    "Option": [
                        {"Index": 0, "Text": "A. 甲"},
                        {"Index": 1, "Text": "B. 乙"},
                    ],
                    "Answer": [{"Index": 0, "Text": "A"}],
                    "Parse": [{"Index": 0, "Text": "图片原有解析"}],
                }
            ],
        }
        if self.include_processed_image:
            info["ImageBase64"] = base64.b64encode(image_bytes("blue")).decode()
        return Response.model_validate(
            {
                "QuestionInfo": [info],
                "RequestId": f"counting-request-{self.calls}",
            }
        )


class EmptyProvider:
    name = "empty"
    is_demo = True
    is_configured = True

    async def recognize_questions(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        pdf_page_number: int = 1,
    ) -> Response:
        del file_bytes, filename, content_type, pdf_page_number
        return Response.model_validate(
            {"QuestionInfo": None, "RequestId": "empty-request-1"}
        )


class UnsafeFailingProvider:
    name = "unsafe-failure"
    is_demo = False
    is_configured = True

    def __init__(self, secret: str) -> None:
        self.secret = secret

    async def recognize_questions(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        pdf_page_number: int = 1,
    ) -> Response:
        del file_bytes, filename, content_type, pdf_page_number
        raise OCRProviderError(
            status_code=418,
            code="UNTRUSTED_PROVIDER_CODE",
            message=self.secret,
            retryable=False,
            provider_code=self.secret,
            request_id=self.secret,
        )


def test_ocr_requires_authentication(client) -> None:
    response = client.post("/api/v1/ocr", json={"upload_id": "missing"})

    assert response.status_code == 401
    assert response.json()["code"] == "invalid_session"


def test_ocr_uses_owned_asset_and_reusable_service_without_ai_provider(
    client, monkeypatch
) -> None:
    cookies = register(client, "ocr-route@example.com")
    uploaded = upload_image(client, cookies)
    service = SpyService()
    client.app.state.ocr_service = service

    def forbidden_ai_provider(*args, **kwargs):
        del args, kwargs
        raise AssertionError("legacy AI OCR provider must not be called")

    monkeypatch.setattr(
        "app.api.routes.providers.get_provider", forbidden_ai_provider, raising=False
    )
    response = client.post(
        "/api/v1/ocr",
        cookies=cookies,
        headers={"X-Request-ID": "local-api-request"},
        json={
            "upload_id": uploaded["id"],
            "idempotency_key": "accepted-but-not-authoritative",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["request_id"] == "provider-request-1"
    assert len(service.calls) == 1
    call = service.calls[0]
    assert call["user_id"]
    assert call["asset"].id == uploaded["id"]
    assert call["pdf_page_number"] == 1
    assert call["local_request_id"] == "local-api-request"


def test_ocr_passes_explicit_pdf_page_and_never_forwards_client_key(client) -> None:
    cookies = register(client, "ocr-page@example.com")
    uploaded = upload_pdf(client, cookies)
    service = SpyService()
    client.app.state.ocr_service = service

    response = client.post(
        "/api/v1/ocr",
        cookies=cookies,
        json={
            "upload_id": uploaded["id"],
            "pdf_page_number": 3,
            "idempotency_key": "client-retry-3",
        },
    )

    assert response.status_code == 200, response.text
    assert service.calls[0]["pdf_page_number"] == 3
    assert response.json()["page_number"] == 3


@pytest.mark.parametrize("page_number", [0, -1])
def test_ocr_rejects_non_positive_pdf_page(client, page_number: int) -> None:
    cookies = register(client, f"ocr-invalid-page-{page_number}@example.com")
    uploaded = upload_image(client, cookies)

    response = client.post(
        "/api/v1/ocr",
        cookies=cookies,
        headers={"X-Request-ID": "invalid-page-request"},
        json={"upload_id": uploaded["id"], "pdf_page_number": page_number},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert "pdf_page_number" in response.json()["field_errors"]
    assert response.json()["request_id"] == "invalid-page-request"


def test_ocr_rejects_oversized_client_idempotency_key(client) -> None:
    cookies = register(client, "ocr-long-key@example.com")
    uploaded = upload_image(client, cookies)

    response = client.post(
        "/api/v1/ocr",
        cookies=cookies,
        json={"upload_id": uploaded["id"], "idempotency_key": "x" * 129},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert "idempotency_key" in response.json()["field_errors"]


@pytest.mark.parametrize(
    "forbidden",
    [
        {"Action": "GeneralAccurateOCR"},
        {"endpoint": "attacker.example"},
        {"SecretId": "must-not-be-accepted"},
        {"UseNewModel": True},
    ],
)
def test_ocr_rejects_server_controlled_extra_fields(client, forbidden) -> None:
    cookies = register(client, f"ocr-extra-{next(iter(forbidden))}@example.com")
    uploaded = upload_image(client, cookies)

    response = client.post(
        "/api/v1/ocr",
        cookies=cookies,
        json={"upload_id": uploaded["id"], **forbidden},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert next(iter(forbidden)) in response.json()["field_errors"]


def test_ocr_hides_assets_owned_by_another_user(client) -> None:
    owner = register(client, "ocr-owner@example.com")
    uploaded = upload_image(client, owner)
    other = register(client, "ocr-other@example.com")
    service = SpyService()
    client.app.state.ocr_service = service

    response = client.post(
        "/api/v1/ocr", cookies=other, json={"upload_id": uploaded["id"]}
    )

    assert response.status_code == 404
    assert response.json()["code"] == "OCR_SOURCE_NOT_FOUND"
    assert service.calls == []


def test_demo_ocr_returns_editable_multi_question_draft_without_saving(client) -> None:
    cookies = register(client, "ocr-multi@example.com")
    uploaded = upload_image(client, cookies)

    response = client.post(
        "/api/v1/ocr", cookies=cookies, json={"upload_id": uploaded["id"]}
    )

    assert response.status_code == 200, response.text
    payload = response.json()
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
    assert payload["provider"] == "mock"
    assert payload["api_name"] == "QuestionSplitOCR"
    assert payload["request_id"] == "mock-question-split-page-1"
    assert payload["question_count"] == 4
    assert len(payload["questions"]) == 4
    assert payload["source"]["file_id"] == uploaded["id"]
    assert payload["is_demo"] is True
    rendered = response.text
    for forbidden in (
        "ImageBase64",
        "image_base64",
        "correct_answer",
        "original_explanation",
        str(client.app.state.settings.upload_dir),
    ):
        assert forbidden not in rendered

    questions = client.get("/api/v1/questions", cookies=cookies).json()
    assert questions["total"] == 0


@pytest.mark.parametrize(
    ("status_code", "code", "message"),
    [
        (409, "OCR_IN_PROGRESS", "OCR 任务正在处理中"),
        (429, "OCR_RATE_LIMITED", "OCR 请求过于频繁"),
        (504, "OCR_PROVIDER_TIMEOUT", "OCR 服务响应超时"),
        (502, "OCR_PROVIDER_ERROR", "OCR 服务暂时不可用"),
    ],
)
def test_ocr_service_errors_use_standard_request_id_envelope(
    client, status_code: int, code: str, message: str
) -> None:
    cookies = register(client, f"ocr-error-{code.lower()}@example.com")
    uploaded = upload_image(client, cookies)
    service = RaisingService(APIError(status_code, code, message))
    client.app.state.ocr_service = service

    response = client.post(
        "/api/v1/ocr",
        cookies=cookies,
        headers={"X-Request-ID": f"local-{code.lower()}"},
        json={"upload_id": uploaded["id"]},
    )

    assert response.status_code == status_code
    assert response.headers["X-Request-ID"] == f"local-{code.lower()}"
    assert response.json() == {
        "code": code,
        "message": message,
        "field_errors": None,
        "request_id": f"local-{code.lower()}",
    }
    assert service.calls == 1


def test_no_question_uses_required_public_error_code(client) -> None:
    cookies = register(client, "ocr-empty@example.com")
    uploaded = upload_image(client, cookies)
    client.app.state.ocr_service = OCRService(
        EmptyProvider(), client.app.state.settings
    )

    response = client.post(
        "/api/v1/ocr",
        cookies=cookies,
        headers={"X-Request-ID": "local-empty"},
        json={"upload_id": uploaded["id"]},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "OCR_NO_QUESTION"
    assert response.json()["request_id"] == "local-empty"


@pytest.mark.parametrize(
    ("secret_id", "secret_key"),
    [(None, None), ("fake-id", None), (None, "fake-key")],
)
def test_missing_tencent_credentials_returns_not_configured_without_sdk_call(
    client, monkeypatch, secret_id: str | None, secret_key: str | None
) -> None:
    marker = f"{bool(secret_id)}-{bool(secret_key)}"
    cookies = register(client, f"ocr-unconfigured-{marker}@example.com")
    uploaded = upload_image(client, cookies)
    settings = client.app.state.settings
    settings.ocr_provider = "tencent_question_split"
    settings.tencentcloud_secret_id = secret_id
    settings.tencentcloud_secret_key = secret_key
    client.app.state.ocr_service = OCRService(TencentOCRProvider(settings), settings)

    def forbidden_sdk(*args, **kwargs):
        del args, kwargs
        raise AssertionError("Tencent SDK must not be created without credentials")

    monkeypatch.setattr("app.services.ocr.tencent.ocr_client.OcrClient", forbidden_sdk)
    response = client.post(
        "/api/v1/ocr",
        cookies=cookies,
        headers={"X-Request-ID": "local-unconfigured"},
        json={"upload_id": uploaded["id"]},
    )

    assert response.status_code == 503
    assert response.json()["code"] == "OCR_NOT_CONFIGURED"
    assert response.json()["request_id"] == "local-unconfigured"


def test_client_idempotency_key_never_overrides_server_canonical_key(client) -> None:
    cookies = register(client, "ocr-idempotent@example.com")
    uploaded = upload_image(client, cookies)
    provider = CountingProvider()
    client.app.state.ocr_service = OCRService(provider, client.app.state.settings)

    first = client.post(
        "/api/v1/ocr",
        cookies=cookies,
        json={"upload_id": uploaded["id"], "idempotency_key": "client-first"},
    )
    second = client.post(
        "/api/v1/ocr",
        cookies=cookies,
        json={"upload_id": uploaded["id"], "idempotency_key": "client-second"},
    )

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert provider.calls == 1
    question = first.json()["questions"][0]
    assert question["recognized_answer"] == "A"
    assert question["recognized_parse"] == "图片原有解析"
    assert "correct_answer" not in question


def test_same_client_key_cannot_merge_different_files(client) -> None:
    cookies = register(client, "ocr-key-files@example.com")
    first_upload = upload_image(client, cookies, color="red")
    second_upload = upload_image(client, cookies, color="green")
    provider = CountingProvider()
    client.app.state.ocr_service = OCRService(provider, client.app.state.settings)

    first = client.post(
        "/api/v1/ocr",
        cookies=cookies,
        json={"upload_id": first_upload["id"], "idempotency_key": "same-client-key"},
    )
    second = client.post(
        "/api/v1/ocr",
        cookies=cookies,
        json={"upload_id": second_upload["id"], "idempotency_key": "same-client-key"},
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["source"]["file_id"] != second.json()["source"]["file_id"]
    assert provider.calls == 2


def test_image_pdf_page_is_normalized_before_server_idempotency(client) -> None:
    cookies = register(client, "ocr-image-page@example.com")
    uploaded = upload_image(client, cookies)
    provider = CountingProvider()
    client.app.state.ocr_service = OCRService(provider, client.app.state.settings)

    first = client.post(
        "/api/v1/ocr",
        cookies=cookies,
        json={"upload_id": uploaded["id"], "pdf_page_number": 1},
    )
    second = client.post(
        "/api/v1/ocr",
        cookies=cookies,
        json={"upload_id": uploaded["id"], "pdf_page_number": 9},
    )

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert second.json()["page_number"] == 1
    assert provider.calls == 1


def test_ocr_response_and_structured_log_do_not_leak_sensitive_payloads(
    client, caplog
) -> None:
    cookies = register(client, "ocr-safe-log@example.com")
    uploaded = upload_image(client, cookies)
    provider = CountingProvider(include_processed_image=True)
    client.app.state.ocr_service = OCRService(provider, client.app.state.settings)

    with caplog.at_level(logging.INFO, logger="app.services.ocr.service"):
        response = client.post(
            "/api/v1/ocr",
            cookies=cookies,
            headers={"X-Request-ID": "local-safe-log"},
            json={
                "upload_id": uploaded["id"],
                "idempotency_key": "client-key-must-not-be-logged",
            },
        )

    assert response.status_code == 200, response.text
    records = [
        record
        for record in caplog.records
        if record.getMessage() == "OCR request completed"
    ]
    assert len(records) == 1
    record = records[0]
    assert record.local_request_id == "local-safe-log"
    assert record.provider == "counting"
    assert record.api_name == "QuestionSplitOCR"
    assert record.provider_request_id == "counting-request-1"
    assert record.duration_ms >= 0
    assert record.success is True
    assert record.question_count == 1
    assert record.error_code is None
    assert record.file_size == len(image_bytes())
    assert record.pdf_page_number == 1

    safe_rendering = " ".join(
        str(value)
        for key, value in vars(record).items()
        if key
        in {
            "msg",
            "local_request_id",
            "user_id",
            "provider",
            "api_name",
            "provider_request_id",
            "duration_ms",
            "success",
            "question_count",
            "error_code",
            "file_size",
            "pdf_page_number",
        }
    )
    for forbidden in (
        "ImageBase64",
        "client-key-must-not-be-logged",
        str(client.app.state.settings.upload_dir),
    ):
        assert forbidden not in response.text
        assert forbidden not in safe_rendering


def test_untrusted_provider_error_is_sanitized_in_api_and_logs(client, caplog) -> None:
    secret = "provider-secret-base64-and-private-path"
    cookies = register(client, "ocr-unsafe-provider@example.com")
    uploaded = upload_image(client, cookies)
    client.app.state.ocr_service = OCRService(
        UnsafeFailingProvider(secret), client.app.state.settings
    )

    with caplog.at_level(logging.INFO, logger="app.services.ocr.service"):
        response = client.post(
            "/api/v1/ocr",
            cookies=cookies,
            headers={"X-Request-ID": "local-safe-error"},
            json={"upload_id": uploaded["id"]},
        )

    assert response.status_code == 502
    assert response.json()["code"] == "OCR_PROVIDER_ERROR"
    assert response.json()["request_id"] == "local-safe-error"
    assert secret not in response.text
    assert secret not in " ".join(record.getMessage() for record in caplog.records)
    assert secret not in " ".join(str(vars(record)) for record in caplog.records)


def test_status_has_explicit_schema_and_never_calls_service_or_sdk(
    client, monkeypatch
) -> None:
    cookies = register(client, "ocr-status-api@example.com")
    settings = client.app.state.settings
    settings.ocr_provider = "tencent_question_split"
    settings.tencentcloud_secret_id = "fake-configured-id"
    settings.tencentcloud_secret_key = "fake-configured-key"

    class ForbiddenService:
        async def recognize(self, *args, **kwargs):
            del args, kwargs
            raise AssertionError("status must not call OCR service")

    client.app.state.ocr_service = ForbiddenService()

    def forbidden_sdk(*args, **kwargs):
        del args, kwargs
        raise AssertionError("status must not create Tencent SDK client")

    monkeypatch.setattr("app.services.ocr.tencent.ocr_client.OcrClient", forbidden_sdk)
    response = client.get("/api/v1/ocr/status", cookies=cookies)

    assert response.status_code == 200
    assert response.json() == {
        "provider": "tencent_question_split",
        "configured": True,
        "api_name": "QuestionSplitOCR",
        "supports_multi_question": True,
        "supports_pdf": True,
        "supports_options": True,
        "use_new_model": False,
    }
    assert "fake-configured-id" not in response.text
    assert "fake-configured-key" not in response.text

    schema = client.app.openapi()["paths"]["/api/v1/ocr/status"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]
    assert schema["$ref"].endswith("/OcrStatus")
