from __future__ import annotations

import base64
import importlib
import threading
from typing import Any

import anyio
import pytest
from requests import exceptions as requests_exceptions
from tencentcloud.common.exception.tencent_cloud_sdk_exception import (
    TencentCloudSDKException,
)
from tencentcloud.common.retry import NoopRetryer
from tencentcloud.ocr.v20181119 import models, ocr_client

from app.core.config import Settings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _provider_modules() -> tuple[Any, Any]:
    return (
        importlib.import_module("app.services.ocr.tencent"),
        importlib.import_module("app.services.ocr.errors"),
    )


def _sdk_response() -> models.QuestionSplitOCRResponse:
    response = models.QuestionSplitOCRResponse()
    response._deserialize(
        {
            "QuestionInfo": [
                {
                    "Angle": 0.0,
                    "Height": 800,
                    "Width": 600,
                    "ResultList": [
                        {
                            "Question": [
                                {
                                    "Index": 0,
                                    "Text": "1. 测试题",
                                    "GroupType": "multiple-choice",
                                }
                            ],
                            "Option": [],
                            "Figure": [],
                            "Table": [],
                            "Answer": [],
                            "Parse": [],
                            "Coord": [],
                        }
                    ],
                    "OrgHeight": 800,
                    "OrgWidth": 600,
                    "ImageBase64": "processed-image-must-not-leak",
                }
            ],
            "RequestId": "req-test-1",
        }
    )
    return response


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "tencentcloud_secret_id": "test-secret-id",
        "tencentcloud_secret_key": "test-secret-key",
        "tencentcloud_region": "",
        "tencentcloud_ocr_timeout_seconds": 30,
        "tencentcloud_ocr_max_retries": 2,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.anyio
async def test_tencent_provider_builds_fixed_image_request_and_reuses_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tencent, _ = _provider_modules()
    instances: list[Any] = []

    class FakeClient:
        def __init__(self, credential: Any, region: str, profile: Any) -> None:
            self.credential = credential
            self.region = region
            self.profile = profile
            self.requests: list[Any] = []
            instances.append(self)

        def QuestionSplitOCR(self, request: Any) -> models.QuestionSplitOCRResponse:
            self.requests.append(request)
            return _sdk_response()

    monkeypatch.setattr(ocr_client, "OcrClient", FakeClient)
    provider = tencent.TencentOCRProvider(_settings())
    payload = b"not-a-real-image"

    first = await provider.recognize_questions(payload, "one.jpg", "image/jpeg")
    await provider.recognize_questions(payload, "two.png", "image/png")

    assert first.request_id == "req-test-1"
    assert "processed-image-must-not-leak" not in first.model_dump_json(by_alias=True)
    assert "ImageBase64" not in first.model_dump(by_alias=True)["QuestionInfo"][0]
    assert len(instances) == 1
    assert len(instances[0].requests) == 2
    request = instances[0].requests[0]
    assert request.ImageBase64 == base64.b64encode(payload).decode("ascii")
    assert request.ImageUrl is None
    assert request.IsPdf is False
    assert request.PdfPageNumber is None
    assert request.EnableImageCrop is True
    assert request.EnableOnlyDetectBorder is False
    assert request.UseNewModel is False
    assert instances[0].region == ""
    assert instances[0].profile.httpProfile.endpoint == "ocr.tencentcloudapi.com"
    assert instances[0].profile.httpProfile.reqTimeout == 30
    assert isinstance(instances[0].profile.retryer, NoopRetryer)


@pytest.mark.anyio
async def test_tencent_provider_applies_configured_timeout_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tencent, _ = _provider_modules()
    timeouts: list[int] = []

    class FakeClient:
        def __init__(self, credential: Any, region: str, profile: Any) -> None:
            timeouts.append(profile.httpProfile.reqTimeout)

        def QuestionSplitOCR(self, request: Any) -> models.QuestionSplitOCRResponse:
            return _sdk_response()

    monkeypatch.setattr(ocr_client, "OcrClient", FakeClient)
    provider = tencent.TencentOCRProvider(
        _settings(tencentcloud_ocr_timeout_seconds=17)
    )

    await provider.recognize_questions(b"image", "question.jpg", "image/jpeg")

    assert timeouts == [17]


@pytest.mark.anyio
async def test_pdf_page_is_set_only_for_canonical_pdf_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tencent, _ = _provider_modules()
    requests: list[Any] = []

    class FakeClient:
        def __init__(self, credential: Any, region: str, profile: Any) -> None:
            pass

        def QuestionSplitOCR(self, request: Any) -> models.QuestionSplitOCRResponse:
            requests.append(request)
            return _sdk_response()

    monkeypatch.setattr(ocr_client, "OcrClient", FakeClient)
    provider = tencent.TencentOCRProvider(_settings())

    await provider.recognize_questions(b"pdf", "one.pdf", "application/pdf")
    await provider.recognize_questions(
        b"pdf", "two.pdf", "application/pdf", pdf_page_number=7
    )
    await provider.recognize_questions(
        b"image", "misleading.pdf", "image/jpeg", pdf_page_number=9
    )

    assert [(item.IsPdf, item.PdfPageNumber) for item in requests] == [
        (True, 1),
        (True, 7),
        (False, None),
    ]


@pytest.mark.anyio
async def test_missing_credentials_fail_only_when_provider_is_called() -> None:
    tencent, errors = _provider_modules()
    provider = tencent.TencentOCRProvider(
        _settings(tencentcloud_secret_id=None, tencentcloud_secret_key=None)
    )

    with pytest.raises(errors.OCRProviderError) as caught:
        await provider.recognize_questions(b"image", "question.jpg", "image/jpeg")

    assert caught.value.code == "OCR_NOT_CONFIGURED"
    assert caught.value.status_code == 503
    assert caught.value.retryable is False
    assert "test-secret" not in str(caught.value)


@pytest.mark.anyio
async def test_image_decode_sdk_error_is_mapped_without_original_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tencent, errors = _provider_modules()

    class FakeClient:
        def __init__(self, credential: Any, region: str, profile: Any) -> None:
            pass

        def QuestionSplitOCR(self, request: Any) -> models.QuestionSplitOCRResponse:
            raise TencentCloudSDKException(
                "FailedOperation.ImageDecodeFailed",
                "SDK detail contains test-secret-key and raw-base64",
                "req-decode-1",
            )

    monkeypatch.setattr(ocr_client, "OcrClient", FakeClient)
    provider = tencent.TencentOCRProvider(_settings())

    with pytest.raises(errors.OCRProviderError) as caught:
        await provider.recognize_questions(b"raw-base64", "bad.jpg", "image/jpeg")

    assert caught.value.code == "OCR_IMAGE_DECODE_FAILED"
    assert caught.value.status_code == 422
    assert caught.value.retryable is False
    assert caught.value.provider_code == "FailedOperation.ImageDecodeFailed"
    assert caught.value.request_id == "req-decode-1"
    assert "SDK detail" not in str(caught.value)
    assert "test-secret-key" not in str(caught.value)
    assert "raw-base64" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.anyio
async def test_internal_error_retries_at_most_configured_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tencent, errors = _provider_modules()
    attempts = 0
    delays: list[float] = []

    class FakeClient:
        def __init__(self, credential: Any, region: str, profile: Any) -> None:
            pass

        def QuestionSplitOCR(self, request: Any) -> models.QuestionSplitOCRResponse:
            nonlocal attempts
            attempts += 1
            raise TencentCloudSDKException(
                "InternalError",
                "sensitive upstream detail",
                f"req-{attempts}",
            )

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(ocr_client, "OcrClient", FakeClient)
    provider = tencent.TencentOCRProvider(
        _settings(tencentcloud_ocr_max_retries=2),
        sleep=fake_sleep,
        jitter=lambda: 0.0,
    )

    with pytest.raises(errors.OCRProviderError) as caught:
        await provider.recognize_questions(b"image", "question.jpg", "image/jpeg")

    assert caught.value.code == "OCR_PROVIDER_ERROR"
    assert caught.value.retryable is True
    assert attempts == 3
    assert delays == [0.25, 0.5]


@pytest.mark.anyio
async def test_retryable_sdk_error_is_attempted_once_when_retries_are_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tencent, errors = _provider_modules()
    attempts = 0
    delays: list[float] = []

    class FakeClient:
        def __init__(self, credential: Any, region: str, profile: Any) -> None:
            pass

        def QuestionSplitOCR(self, request: Any) -> models.QuestionSplitOCRResponse:
            nonlocal attempts
            attempts += 1
            raise TencentCloudSDKException(
                "InternalError",
                "sensitive upstream detail",
                "req-no-retry",
            )

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(ocr_client, "OcrClient", FakeClient)
    provider = tencent.TencentOCRProvider(
        _settings(tencentcloud_ocr_max_retries=0),
        sleep=fake_sleep,
        jitter=lambda: 0.0,
    )

    with pytest.raises(errors.OCRProviderError):
        await provider.recognize_questions(b"image", "question.jpg", "image/jpeg")

    assert attempts == 1
    assert delays == []


@pytest.mark.parametrize(
    ("provider_code", "status_code", "domain_code", "retryable"),
    [
        ("FailedOperation.DownLoadError", 502, "OCR_PROVIDER_ERROR", False),
        (
            "FailedOperation.ImageDecodeFailed",
            422,
            "OCR_IMAGE_DECODE_FAILED",
            False,
        ),
        ("FailedOperation.OcrFailed", 502, "OCR_PROVIDER_ERROR", True),
        ("FailedOperation.UnKnowError", 502, "OCR_PROVIDER_ERROR", True),
        (
            "FailedOperation.UnOpenError",
            503,
            "OCR_SERVICE_NOT_OPEN",
            False,
        ),
        (
            "InvalidParameterValue.InvalidParameterValueLimit",
            413,
            "OCR_FILE_TOO_LARGE",
            False,
        ),
        (
            "LimitExceeded.TooLargeFileError",
            413,
            "OCR_FILE_TOO_LARGE",
            False,
        ),
        (
            "ResourceUnavailable.InArrears",
            503,
            "OCR_ACCOUNT_IN_ARREARS",
            False,
        ),
        (
            "ResourceUnavailable.ResourcePackageRunOut",
            503,
            "OCR_RESOURCE_PACKAGE_RUN_OUT",
            False,
        ),
        (
            "ResourcesSoldOut.ChargeStatusException",
            503,
            "OCR_BILLING_ERROR",
            False,
        ),
        ("AuthFailure.SignatureFailure", 503, "OCR_CREDENTIAL_ERROR", False),
        ("InvalidCredential", 503, "OCR_CREDENTIAL_ERROR", False),
        ("RequestLimitExceeded", 429, "OCR_RATE_LIMITED", True),
        ("RequestLimitExceeded.UinLimitExceeded", 429, "OCR_RATE_LIMITED", True),
        ("InternalError", 502, "OCR_PROVIDER_ERROR", True),
        ("InternalError.ServiceError", 502, "OCR_PROVIDER_ERROR", True),
        ("ClientNetworkError", 502, "OCR_PROVIDER_ERROR", True),
        ("ServerNetworkError", 502, "OCR_PROVIDER_ERROR", True),
        ("ServerError", 502, "OCR_PROVIDER_ERROR", True),
        ("ServiceUnavailable", 502, "OCR_PROVIDER_ERROR", True),
        ("RequestTimeout", 504, "OCR_PROVIDER_TIMEOUT", True),
        ("InvalidParameter", 502, "OCR_PROVIDER_ERROR", False),
        ("InvalidParameter.BadValue", 502, "OCR_PROVIDER_ERROR", False),
        ("UnsupportedOperation", 502, "OCR_PROVIDER_ERROR", False),
    ],
)
def test_sdk_error_mapping_is_safe_and_complete(
    provider_code: str,
    status_code: int,
    domain_code: str,
    retryable: bool,
) -> None:
    _, errors = _provider_modules()
    original_message = "secret-id raw-image-base64 original SDK details"

    mapped = errors.map_provider_exception(
        TencentCloudSDKException(provider_code, original_message, "req-map-1")
    )

    assert mapped.status_code == status_code
    assert mapped.code == domain_code
    assert mapped.retryable is retryable
    assert mapped.provider_code == provider_code
    assert mapped.request_id == "req-map-1"
    assert original_message not in str(mapped)
    assert "secret-id" not in str(mapped)
    assert "raw-image-base64" not in repr(mapped)


@pytest.mark.parametrize(
    ("exception", "status_code", "domain_code", "retryable"),
    [
        (TimeoutError("upstream secret"), 504, "OCR_PROVIDER_TIMEOUT", True),
        (ConnectionError("upstream secret"), 502, "OCR_PROVIDER_ERROR", True),
        (
            requests_exceptions.Timeout("upstream secret"),
            504,
            "OCR_PROVIDER_TIMEOUT",
            True,
        ),
        (
            requests_exceptions.ConnectionError("upstream secret"),
            502,
            "OCR_PROVIDER_ERROR",
            True,
        ),
        (RuntimeError("upstream secret"), 502, "OCR_PROVIDER_ERROR", False),
    ],
)
def test_local_error_mapping_is_safe(
    exception: Exception,
    status_code: int,
    domain_code: str,
    retryable: bool,
) -> None:
    _, errors = _provider_modules()

    mapped = errors.map_provider_exception(exception)

    assert (mapped.status_code, mapped.code, mapped.retryable) == (
        status_code,
        domain_code,
        retryable,
    )
    assert "upstream secret" not in str(mapped)
    assert mapped.provider_code is None
    assert mapped.request_id is None


@pytest.mark.parametrize(
    ("incoming_code", "status_code", "message", "retryable"),
    [
        ("OCR_NOT_CONFIGURED", 503, "OCR 服务未配置", False),
        ("OCR_IMAGE_DECODE_FAILED", 422, "无法解析上传的图片", False),
        ("OCR_SERVICE_NOT_OPEN", 503, "OCR 服务未开通", False),
        ("OCR_FILE_TOO_LARGE", 413, "上传文件过大", False),
        ("OCR_ACCOUNT_IN_ARREARS", 503, "OCR 账户欠费", False),
        ("OCR_RESOURCE_PACKAGE_RUN_OUT", 503, "OCR 资源包已用尽", False),
        ("OCR_BILLING_ERROR", 503, "OCR 计费状态异常", False),
        ("OCR_CREDENTIAL_ERROR", 503, "OCR 服务凭证无效", False),
        ("OCR_RATE_LIMITED", 429, "OCR 请求过于频繁", True),
        ("OCR_PROVIDER_TIMEOUT", 504, "OCR 服务响应超时", True),
        ("OCR_PROVIDER_ERROR", 502, "OCR 服务暂时不可用", False),
        ("UNTRUSTED_DOMAIN_CODE", 502, "OCR 服务暂时不可用", False),
    ],
)
def test_existing_domain_errors_are_rebuilt_from_safe_allowlist(
    incoming_code: str,
    status_code: int,
    message: str,
    retryable: bool,
) -> None:
    _, errors = _provider_modules()
    secret = "secret-id raw-image-base64 original domain detail"
    original = errors.OCRProviderError(
        status_code=418,
        code=incoming_code,
        message=secret,
        retryable=not retryable,
        provider_code=secret,
        request_id=secret,
    )
    original.__cause__ = RuntimeError(secret)
    original.__context__ = RuntimeError(secret)
    try:
        raise original
    except errors.OCRProviderError as caught:
        original = caught

    mapped = errors.map_provider_exception(original)

    assert mapped is not original
    assert (mapped.status_code, mapped.code, mapped.message, mapped.retryable) == (
        status_code,
        incoming_code
        if incoming_code != "UNTRUSTED_DOMAIN_CODE"
        else "OCR_PROVIDER_ERROR",
        message,
        retryable,
    )
    assert mapped.provider_code is None
    assert mapped.request_id is None
    assert mapped.__traceback__ is None
    assert mapped.__cause__ is None
    assert mapped.__context__ is None
    rendered = f"{mapped!s} {mapped!r} {vars(mapped)!r}"
    assert secret not in rendered


@pytest.mark.parametrize(
    ("provider_code", "expected_domain_code"),
    [
        ("FailedOperation.OcrFailed", "OCR_PROVIDER_ERROR"),
        ("FailedOperation.UnKnowError", "OCR_PROVIDER_ERROR"),
        ("RequestLimitExceeded", "OCR_RATE_LIMITED"),
        ("InternalError", "OCR_PROVIDER_ERROR"),
        ("ClientNetworkError", "OCR_PROVIDER_ERROR"),
        ("RequestTimeout", "OCR_PROVIDER_TIMEOUT"),
    ],
)
@pytest.mark.anyio
async def test_transient_sdk_errors_stop_after_three_total_attempts(
    monkeypatch: pytest.MonkeyPatch,
    provider_code: str,
    expected_domain_code: str,
) -> None:
    tencent, errors = _provider_modules()
    attempts = 0

    class FakeClient:
        def __init__(self, credential: Any, region: str, profile: Any) -> None:
            pass

        def QuestionSplitOCR(self, request: Any) -> models.QuestionSplitOCRResponse:
            nonlocal attempts
            attempts += 1
            raise TencentCloudSDKException(provider_code, "private detail", "req-final")

    async def no_wait(delay: float) -> None:
        pass

    monkeypatch.setattr(ocr_client, "OcrClient", FakeClient)
    provider = tencent.TencentOCRProvider(
        _settings(tencentcloud_ocr_max_retries=2),
        sleep=no_wait,
        jitter=lambda: 0.0,
    )

    with pytest.raises(errors.OCRProviderError) as caught:
        await provider.recognize_questions(b"image", "question.png", "image/png")

    assert caught.value.code == expected_domain_code
    assert attempts == 3


@pytest.mark.anyio
async def test_provider_defensively_caps_unvalidated_retry_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tencent, errors = _provider_modules()
    attempts = 0

    class FakeClient:
        def __init__(self, credential: Any, region: str, profile: Any) -> None:
            pass

        def QuestionSplitOCR(self, request: Any) -> models.QuestionSplitOCRResponse:
            nonlocal attempts
            attempts += 1
            raise TencentCloudSDKException(
                "InternalError", "private detail", "req-capped"
            )

    async def no_wait(delay: float) -> None:
        pass

    monkeypatch.setattr(ocr_client, "OcrClient", FakeClient)
    provider = tencent.TencentOCRProvider(
        _settings().model_copy(update={"tencentcloud_ocr_max_retries": 99}),
        sleep=no_wait,
        jitter=lambda: 0.0,
    )

    with pytest.raises(errors.OCRProviderError):
        await provider.recognize_questions(b"image", "question.png", "image/png")

    assert attempts == 3


@pytest.mark.parametrize(
    "provider_code",
    [
        "FailedOperation.DownLoadError",
        "FailedOperation.ImageDecodeFailed",
        "FailedOperation.UnOpenError",
        "InvalidParameterValue.InvalidParameterValueLimit",
        "LimitExceeded.TooLargeFileError",
        "ResourceUnavailable.InArrears",
        "ResourceUnavailable.ResourcePackageRunOut",
        "ResourcesSoldOut.ChargeStatusException",
        "AuthFailure.SignatureFailure",
        "InvalidParameter",
        "UnsupportedOperation",
    ],
)
@pytest.mark.anyio
async def test_non_retryable_sdk_errors_are_attempted_once(
    monkeypatch: pytest.MonkeyPatch,
    provider_code: str,
) -> None:
    tencent, errors = _provider_modules()
    attempts = 0

    class FakeClient:
        def __init__(self, credential: Any, region: str, profile: Any) -> None:
            pass

        def QuestionSplitOCR(self, request: Any) -> models.QuestionSplitOCRResponse:
            nonlocal attempts
            attempts += 1
            raise TencentCloudSDKException(provider_code, "private detail", "req-once")

    async def forbidden_sleep(delay: float) -> None:
        raise AssertionError("non-retryable failures must not sleep")

    monkeypatch.setattr(ocr_client, "OcrClient", FakeClient)
    provider = tencent.TencentOCRProvider(
        _settings(), sleep=forbidden_sleep, jitter=lambda: 0.0
    )

    with pytest.raises(errors.OCRProviderError):
        await provider.recognize_questions(b"image", "question.png", "image/png")

    assert attempts == 1


@pytest.mark.anyio
async def test_sdk_call_runs_off_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    tencent, _ = _provider_modules()
    release = threading.Event()
    released_by_event_loop: list[bool] = []

    class FakeClient:
        def __init__(self, credential: Any, region: str, profile: Any) -> None:
            pass

        def QuestionSplitOCR(self, request: Any) -> models.QuestionSplitOCRResponse:
            released_by_event_loop.append(release.wait(timeout=0.5))
            return _sdk_response()

    async def tick() -> None:
        await anyio.sleep(0.01)
        release.set()

    monkeypatch.setattr(ocr_client, "OcrClient", FakeClient)
    provider = tencent.TencentOCRProvider(_settings())

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(tick)
        task_group.start_soon(
            provider.recognize_questions,
            b"image",
            "question.png",
            "image/png",
        )

    assert released_by_event_loop == [True]


@pytest.mark.anyio
async def test_mock_provider_is_deterministic_multi_question_official_shape() -> None:
    mock_module = importlib.import_module("app.services.ocr.mock")
    types_module = importlib.import_module("app.services.ocr.types")
    provider = mock_module.MockOCRProvider()

    first = await provider.recognize_questions(b"ignored", "sample.png", "image/png")
    second = await provider.recognize_questions(
        b"different", "other.pdf", "application/pdf"
    )

    assert isinstance(first, types_module.Response)
    assert provider.name == "mock"
    assert provider.is_demo is True
    assert first.request_id.startswith("mock-")
    assert first.model_dump(by_alias=True) == second.model_dump(by_alias=True)
    groups = [
        group for info in first.question_info or [] for group in info.result_list or []
    ]
    assert len(groups) == 4
    assert any(group.question for group in groups)
    assert any(group.figure for group in groups)
    assert any(group.table for group in groups)
    assert all(group.coord for group in groups)
    assert all(group.answer and group.parse for group in groups)
    assert all(
        element.coord is not None
        for group in groups
        for element in [
            *(group.question or []),
            *(group.option or []),
            *(group.figure or []),
            *(group.table or []),
        ]
    )
    assert [
        [question.group_type for question in group.question or []] for group in groups
    ] == [
        ["multiple-choice"],
        ["arithmetic"],
        ["multiple-choice"],
        ["problem-solving"],
    ]

    page_two = await provider.recognize_questions(
        b"ignored", "paper.pdf", "application/pdf", pdf_page_number=2
    )
    repeated_page_two = await provider.recognize_questions(
        b"different", "another.pdf", "application/pdf", pdf_page_number=2
    )
    assert page_two.model_dump(by_alias=True) == repeated_page_two.model_dump(
        by_alias=True
    )
    assert page_two.model_dump(by_alias=True) != first.model_dump(by_alias=True)
    assert page_two.request_id == "mock-question-split-page-2"
    assert "第 2 页" in (
        page_two.question_info[0].result_list[0].question[0].text or ""
    )


def test_factory_centralizes_mock_and_tencent_selection() -> None:
    base_module = importlib.import_module("app.services.ocr.base")
    factory_module = importlib.import_module("app.services.ocr.factory")
    mock_module = importlib.import_module("app.services.ocr.mock")
    tencent_module, _ = _provider_modules()

    mock_provider = factory_module.create_ocr_provider(_settings(ocr_provider="mock"))
    live_provider = factory_module.create_ocr_provider(
        _settings(ocr_provider="tencent_question_split")
    )

    assert isinstance(mock_provider, mock_module.MockOCRProvider)
    assert isinstance(live_provider, tencent_module.TencentOCRProvider)
    assert isinstance(mock_provider, base_module.OCRProvider)
    assert isinstance(live_provider, base_module.OCRProvider)
