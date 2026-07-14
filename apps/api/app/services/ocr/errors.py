"""Safe domain errors for OCR providers."""

from __future__ import annotations

from requests import exceptions as requests_exceptions
from tencentcloud.common.exception.tencent_cloud_sdk_exception import (
    TencentCloudSDKException,
)


class OCRProviderError(Exception):
    """An OCR failure safe to expose without upstream error details."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        retryable: bool,
        provider_code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable
        self.provider_code = provider_code
        self.request_id = request_id


def _error(
    status_code: int,
    code: str,
    message: str,
    retryable: bool,
    *,
    provider_code: str | None = None,
    request_id: str | None = None,
) -> OCRProviderError:
    return OCRProviderError(
        status_code=status_code,
        code=code,
        message=message,
        retryable=retryable,
        provider_code=provider_code,
        request_id=request_id,
    )


def not_configured_error() -> OCRProviderError:
    return _error(503, "OCR_NOT_CONFIGURED", "OCR 服务未配置", False)


def map_provider_exception(exc: Exception) -> OCRProviderError:
    """Map an upstream exception without retaining its original message."""

    if isinstance(exc, OCRProviderError):
        return exc
    if isinstance(exc, (TimeoutError, requests_exceptions.Timeout)):
        return _error(504, "OCR_PROVIDER_TIMEOUT", "OCR 服务响应超时", True)
    if isinstance(exc, (ConnectionError, requests_exceptions.ConnectionError)):
        return _error(502, "OCR_PROVIDER_ERROR", "OCR 服务暂时不可用", True)
    if not isinstance(exc, TencentCloudSDKException):
        return _error(502, "OCR_PROVIDER_ERROR", "OCR 服务暂时不可用", False)

    # TencentCloudSDKException exposes structured fields through these accessors.
    # Never retain get_message(): it may contain credentials or request payloads.
    provider_code = exc.get_code() or None
    request_id = exc.get_request_id() or None
    normalized = (provider_code or "").casefold()
    metadata = {"provider_code": provider_code, "request_id": request_id}

    if normalized == "failedoperation.imagedecodefailed":
        return _error(
            422,
            "OCR_IMAGE_DECODE_FAILED",
            "无法解析上传的图片",
            False,
            **metadata,
        )
    if normalized == "failedoperation.unopenerror":
        return _error(
            503,
            "OCR_SERVICE_NOT_OPEN",
            "OCR 服务未开通",
            False,
            **metadata,
        )
    if normalized in {
        "invalidparametervalue.invalidparametervaluelimit",
        "limitexceeded.toolargefileerror",
    }:
        return _error(
            413,
            "OCR_FILE_TOO_LARGE",
            "上传文件过大",
            False,
            **metadata,
        )
    if normalized == "resourceunavailable.inarrears":
        return _error(
            503,
            "OCR_ACCOUNT_IN_ARREARS",
            "OCR 账户欠费",
            False,
            **metadata,
        )
    if normalized == "resourceunavailable.resourcepackagerunout":
        return _error(
            503,
            "OCR_RESOURCE_PACKAGE_RUN_OUT",
            "OCR 资源包已用尽",
            False,
            **metadata,
        )
    if normalized == "resourcessoldout.chargestatusexception":
        return _error(
            503,
            "OCR_BILLING_ERROR",
            "OCR 计费状态异常",
            False,
            **metadata,
        )
    if normalized == "invalidcredential" or normalized.startswith("authfailure."):
        return _error(
            503,
            "OCR_CREDENTIAL_ERROR",
            "OCR 服务凭证无效",
            False,
            **metadata,
        )
    if normalized == "requestlimitexceeded" or normalized.startswith(
        "requestlimitexceeded."
    ):
        return _error(
            429,
            "OCR_RATE_LIMITED",
            "OCR 请求过于频繁",
            True,
            **metadata,
        )
    if normalized == "requesttimeout" or normalized.startswith("requesttimeout."):
        return _error(
            504,
            "OCR_PROVIDER_TIMEOUT",
            "OCR 服务响应超时",
            True,
            **metadata,
        )
    if normalized in {
        "failedoperation.ocrfailed",
        "failedoperation.unknowerror",
    }:
        return _error(
            502,
            "OCR_PROVIDER_ERROR",
            "OCR 服务暂时不可用",
            True,
            **metadata,
        )
    if normalized.startswith("internalerror"):
        return _error(
            502,
            "OCR_PROVIDER_ERROR",
            "OCR 服务暂时不可用",
            True,
            **metadata,
        )
    if any(
        normalized == code or normalized.startswith(f"{code}.")
        for code in {
            "clientnetworkerror",
            "servernetworkerror",
            "servererror",
            "serviceunavailable",
        }
    ):
        return _error(
            502,
            "OCR_PROVIDER_ERROR",
            "OCR 服务暂时不可用",
            True,
            **metadata,
        )
    return _error(
        502,
        "OCR_PROVIDER_ERROR",
        "OCR 服务暂时不可用",
        False,
        **metadata,
    )
