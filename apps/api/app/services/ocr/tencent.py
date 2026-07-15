"""Tencent QuestionSplitOCR provider."""

from __future__ import annotations

import base64
import random
from collections.abc import Awaitable, Callable
from typing import Any

import anyio
from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.common.retry import NoopRetryer
from tencentcloud.ocr.v20181119 import models, ocr_client

from app.core.config import Settings
from app.services.ocr.errors import (
    OCRProviderError,
    map_provider_exception,
    not_configured_error,
)
from app.services.ocr.types import Response
from app.services.ocr_contract import (
    ENABLE_IMAGE_CROP,
    ENABLE_ONLY_DETECT_BORDER,
    ENDPOINT,
    USE_NEW_MODEL,
)


Sleep = Callable[[float], Awaitable[None]]
Jitter = Callable[[], float]


class TencentOCRProvider:
    """Async adapter around Tencent Cloud's synchronous official OCR SDK."""

    name = "tencent_question_split"
    is_demo = False

    def __init__(
        self,
        settings: Settings,
        *,
        sleep: Sleep = anyio.sleep,
        jitter: Jitter | None = None,
    ) -> None:
        self._settings = settings
        self._sleep = sleep
        self._jitter = jitter or (lambda: random.uniform(0.0, 0.1))
        self._client: Any | None = None

    @property
    def is_configured(self) -> bool:
        return bool(
            self._settings.tencentcloud_secret_id
            and self._settings.tencentcloud_secret_key
        )

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        secret_id = self._settings.tencentcloud_secret_id
        secret_key = self._settings.tencentcloud_secret_key
        if not secret_id or not secret_key:
            raise not_configured_error()

        cloud_credential = credential.Credential(secret_id, secret_key)
        http_profile = HttpProfile(
            endpoint=ENDPOINT,
            reqTimeout=self._settings.tencentcloud_ocr_timeout_seconds,
        )
        client_profile = ClientProfile(
            httpProfile=http_profile,
            retryer=NoopRetryer(),
        )
        self._client = ocr_client.OcrClient(
            cloud_credential,
            self._settings.tencentcloud_region,
            client_profile,
        )
        return self._client

    @staticmethod
    def _request(
        file_bytes: bytes,
        *,
        content_type: str,
        pdf_page_number: int,
    ) -> models.QuestionSplitOCRRequest:
        request = models.QuestionSplitOCRRequest()
        request.ImageBase64 = base64.b64encode(file_bytes).decode("ascii")
        request.IsPdf = content_type == "application/pdf"
        if request.IsPdf:
            request.PdfPageNumber = pdf_page_number
        request.EnableImageCrop = ENABLE_IMAGE_CROP
        request.EnableOnlyDetectBorder = ENABLE_ONLY_DETECT_BORDER
        request.UseNewModel = USE_NEW_MODEL
        return request

    async def recognize_questions(
        self,
        file_bytes: bytes,
        filename: str,
        content_type: str,
        pdf_page_number: int = 1,
    ) -> Response:
        del filename
        client_error: OCRProviderError | None
        try:
            client = self._get_client()
        except Exception as exc:
            client_error = map_provider_exception(exc).with_traceback(None)
        else:
            client_error = None
        if client_error is not None:
            raise client_error

        request = self._request(
            file_bytes,
            content_type=content_type,
            pdf_page_number=pdf_page_number,
        )
        max_retries = min(max(0, self._settings.tencentcloud_ocr_max_retries), 2)
        for attempt in range(max_retries + 1):
            try:
                sdk_response = await anyio.to_thread.run_sync(
                    client.QuestionSplitOCR,
                    request,
                )
                return Response.model_validate_json(sdk_response.to_json_string())
            except Exception as exc:
                mapped = map_provider_exception(exc)
            if not mapped.retryable or attempt >= max_retries:
                raise mapped
            delay = 0.25 * (2**attempt) + max(0.0, self._jitter())
            await self._sleep(delay)

        raise OCRProviderError(
            status_code=502,
            code="OCR_PROVIDER_ERROR",
            message="OCR 服务暂时不可用",
            retryable=False,
        )
