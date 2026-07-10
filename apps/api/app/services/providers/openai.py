from __future__ import annotations

import base64
import logging
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    RateLimitError,
)

from app.core.errors import APIError
from app.schemas.analysis import (
    AnalysisInput,
    AnalysisProviderResponse,
    AnalysisResult,
)
from app.schemas.upload import OcrResult

logger = logging.getLogger(__name__)

OCR_INSTRUCTIONS = (
    "识别图片中的一道公考题，准确转录题干、选项、作答、正确答案、解析和原始文本。"
    "仅返回指定 JSON 结构，不要添加额外字段。"
)

ANALYSIS_INSTRUCTIONS = (
    "分析这道公考错题的错误原因、知识点、正确思路和学习建议。"
    "仅返回指定 JSON 结构，不要添加额外字段。"
)


class OpenAIProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-5.5",
        client: Any | None = None,
        request_id: str | None = None,
    ) -> None:
        self.model = model
        self.request_id = request_id
        self.client = client or AsyncOpenAI(
            api_key=api_key,
            max_retries=0,
            timeout=60.0,
        )

    async def ocr(
        self,
        image_bytes: bytes,
        mime_type: str,
        request_id: str | None = None,
    ) -> OcrResult:
        encoded = base64.b64encode(image_bytes).decode()
        data_url = f"data:{mime_type};base64,{encoded}"
        local_request_id = request_id or self.request_id
        try:
            response = await self.client.responses.create(
                model=self.model,
                instructions=OCR_INSTRUCTIONS,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_text", "text": "识别这一道公考题并按结构返回。"},
                            {"type": "input_image", "image_url": data_url},
                        ],
                    }
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "ocr_result",
                        "strict": True,
                        "schema": OcrResult.model_json_schema(),
                    }
                },
            )
        except APITimeoutError as exc:
            self._log_provider_error(exc, "timeout", local_request_id=local_request_id)
            raise APIError(504, "provider_timeout", "OCR 服务响应超时") from exc
        except APIConnectionError as exc:
            self._log_provider_error(
                exc, "connection", local_request_id=local_request_id
            )
            raise APIError(502, "provider_connection_error", "OCR 服务连接失败") from exc
        except RateLimitError as exc:
            self._log_provider_error(
                exc, "rate_limit", local_request_id=local_request_id
            )
            raise APIError(429, "provider_rate_limited", "OCR 服务请求过于频繁") from exc
        except APIStatusError as exc:
            self._log_provider_error(
                exc,
                "status",
                getattr(exc.response, "status_code", None),
                local_request_id=local_request_id,
            )
            status = getattr(exc.response, "status_code", 502)
            code = "provider_rate_limited" if status == 429 else "provider_api_error"
            raise APIError(429 if status == 429 else 502, code, "OCR 服务暂时不可用") from exc
        except Exception as exc:
            # Do not leak SDK or response details through the API boundary.
            self._log_provider_error(
                exc, "unexpected", local_request_id=local_request_id
            )
            raise APIError(502, "provider_api_error", "OCR 服务暂时不可用") from exc

        try:
            result = OcrResult.model_validate_json(response.output_text)
        except (AttributeError, TypeError, ValueError) as exc:
            self._log_provider_metadata(
                category="invalid_response",
                provider_request_id=getattr(response, "_request_id", None),
                status_code=getattr(response, "status_code", 200),
                local_request_id=local_request_id,
            )
            raise APIError(502, "provider_invalid_response", "OCR 服务返回内容无效") from exc
        return result.model_copy(update={"is_demo": False})

    def _log_provider_error(
        self,
        error: Exception,
        category: str,
        status_code: int | None = None,
        *,
        local_request_id: str | None = None,
    ) -> None:
        response = getattr(error, "response", None)
        provider_request_id = (
            getattr(response, "headers", {}).get("x-request-id") if response else None
        )
        self._log_provider_metadata(
            category=category,
            provider_request_id=provider_request_id,
            status_code=status_code,
            local_request_id=local_request_id,
        )

    @staticmethod
    def _log_provider_metadata(
        *,
        category: str,
        provider_request_id: str | None,
        status_code: int | None,
        local_request_id: str | None,
    ) -> None:
        logger.warning(
            "OpenAI provider request failed",
            extra={
                "provider_category": category,
                "provider_request_id": provider_request_id,
                "provider_status_code": status_code,
                "local_request_id": local_request_id,
            },
        )

    async def analyze(
        self, payload: AnalysisInput, request_id: str | None = None
    ) -> AnalysisResult:
        local_request_id = request_id or self.request_id
        try:
            response = await self.client.responses.create(
                model=self.model,
                instructions=ANALYSIS_INSTRUCTIONS,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": payload.model_dump_json(),
                            }
                        ],
                    }
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "analysis_result",
                        "strict": True,
                        "schema": AnalysisProviderResponse.model_json_schema(),
                    }
                },
            )
        except APITimeoutError as exc:
            self._log_provider_error(exc, "timeout", local_request_id=local_request_id)
            raise APIError(504, "provider_timeout", "AI 分析服务响应超时") from exc
        except APIConnectionError as exc:
            self._log_provider_error(
                exc, "connection", local_request_id=local_request_id
            )
            raise APIError(502, "provider_connection_error", "AI 分析服务连接失败") from exc
        except RateLimitError as exc:
            self._log_provider_error(
                exc, "rate_limit", local_request_id=local_request_id
            )
            raise APIError(429, "provider_rate_limited", "AI 分析服务请求过于频繁") from exc
        except APIStatusError as exc:
            self._log_provider_error(
                exc,
                "status",
                getattr(exc.response, "status_code", None),
                local_request_id=local_request_id,
            )
            status = getattr(exc.response, "status_code", 502)
            code = "provider_rate_limited" if status == 429 else "provider_api_error"
            message = (
                "AI 分析服务请求过于频繁"
                if status == 429
                else "AI 分析服务暂时不可用"
            )
            raise APIError(429 if status == 429 else 502, code, message) from exc
        except Exception as exc:
            self._log_provider_error(
                exc, "unexpected", local_request_id=local_request_id
            )
            raise APIError(502, "provider_api_error", "AI 分析服务暂时不可用") from exc

        try:
            parsed = AnalysisProviderResponse.model_validate_json(response.output_text)
        except (AttributeError, TypeError, ValueError) as exc:
            self._log_provider_metadata(
                category="invalid_response",
                provider_request_id=getattr(response, "_request_id", None),
                status_code=getattr(response, "status_code", 200),
                local_request_id=local_request_id,
            )
            raise APIError(
                502, "provider_invalid_response", "AI 分析服务返回内容无效"
            ) from exc

        return AnalysisResult(
            **parsed.model_dump(),
            raw_response=parsed.model_dump(mode="json"),
            provider_name="openai",
            model_name=self.model,
            is_demo=False,
        )
