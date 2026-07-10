import asyncio
import base64
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError

from app.core.errors import APIError
from app.core.errors import request_id_for
from app.schemas.analysis import AnalysisInput, AnalysisResult
from app.schemas.question import ExamModule, QuestionOption
from app.services.providers.demo import DemoProvider
from app.services.providers.openai import OpenAIProvider
from starlette.requests import Request


def analysis_input() -> AnalysisInput:
    return AnalysisInput(
        stem="某地区第二季度生产总值为多少亿元？",
        options=[
            QuestionOption(label="A", content="120亿元"),
            QuestionOption(label="B", content="132亿元"),
        ],
        user_answer="A",
        correct_answer="B",
        original_explanation="第二季度生产总值=120×(1+10%)=132亿元。",
        ocr_raw_text="OCR 原文",
        module=ExamModule.DATA,
    )


def test_request_id_helper_reuses_header_and_generated_value():
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/ocr",
            "headers": [(b"x-request-id", b"local-header")],
        }
    )
    assert request_id_for(request) == "local-header"
    assert request_id_for(request) == "local-header"


def test_demo_provider_has_four_options():
    result = __import__("asyncio").run(DemoProvider().ocr(b"", "image/png"))
    assert result.is_demo is True
    assert len(result.options) == 4
    assert result.correct_answer


def test_demo_provider_returns_deterministic_structured_analysis():
    first = asyncio.run(DemoProvider().analyze(analysis_input()))
    second = asyncio.run(DemoProvider().analyze(analysis_input()))

    assert first == second
    assert first.is_demo is True
    assert first.provider_name == "demo"
    assert first.knowledge_points
    assert first.cause_analysis
    assert first.correct_approach


def test_analysis_schemas_forbid_extra_top_level_fields():
    assert AnalysisInput.model_json_schema()["additionalProperties"] is False
    assert AnalysisResult.model_json_schema()["additionalProperties"] is False


def test_openai_provider_sends_data_url_and_strict_schema():
    seen = {}

    class FakeResponses:
        async def create(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(
                output_text=(
                    '{"stem":"题干","options":[{"label":"A","content":"甲"}],'
                    '"user_answer":"A","correct_answer":"A",'
                    '"original_explanation":"解析","raw_text":"原文","is_demo":true}'
                ),
                _request_id="req_test",
            )

    class FakeClient:
        responses = FakeResponses()

    provider = OpenAIProvider(api_key="test", model="test-model", client=FakeClient())
    result = asyncio.run(provider.ocr(b"hello", "image/png"))

    assert result.is_demo is False
    image = seen["input"][0]["content"][1]
    assert image["type"] == "input_image"
    assert image["image_url"] == "data:image/png;base64," + base64.b64encode(b"hello").decode()
    assert seen["text"]["format"]["type"] == "json_schema"
    assert seen["text"]["format"]["strict"] is True
    assert seen["text"]["format"]["schema"]["additionalProperties"] is False
    assert "user_answer" in seen["text"]["format"]["schema"]["required"]
    option_schema = seen["text"]["format"]["schema"]["$defs"]["QuestionOption"]
    assert option_schema["additionalProperties"] is False


def test_openai_provider_analyze_uses_strict_schema_and_keeps_raw_response():
    seen = {}
    raw_response = {
        "cause_analysis": "将增长率与增长量混淆。",
        "knowledge_points": ["增长率"],
        "correct_approach": "用增长量除以基期量。",
        "study_advice": "复习增长率公式。",
        "suggested_error_reason": "计算错",
    }

    class FakeResponses:
        async def create(self, **kwargs):
            seen.update(kwargs)
            return SimpleNamespace(output_text=__import__("json").dumps(raw_response))

    class FakeClient:
        responses = FakeResponses()

    provider = OpenAIProvider(api_key="test", model="test-model", client=FakeClient())
    result = asyncio.run(provider.analyze(analysis_input(), request_id="local-456"))

    assert result.is_demo is False
    assert result.provider_name == "openai"
    assert result.model_name == "test-model"
    assert result.raw_response == raw_response
    assert seen["text"]["format"]["type"] == "json_schema"
    assert seen["text"]["format"]["strict"] is True
    assert seen["text"]["format"]["schema"]["additionalProperties"] is False
    assert "suggested_error_reason" in seen["text"]["format"]["schema"]["required"]


def test_openai_connection_errors_map_to_stable_api_error(caplog):
    class FakeResponses:
        async def create(self, **kwargs):
            request = httpx.Request("POST", "https://api.openai.com/v1/responses")
            raise APIConnectionError(request=request)

    class FakeClient:
        responses = FakeResponses()

    provider = OpenAIProvider(api_key="test", client=FakeClient())
    with pytest.raises(APIError) as caught:
        with caplog.at_level("WARNING"):
            asyncio.run(provider.ocr(b"hello", "image/png", request_id="local-123"))
    assert caught.value.code == "provider_connection_error"
    assert any(
        getattr(record, "local_request_id", None) == "local-123"
        for record in caplog.records
    )


def test_openai_client_disables_sdk_retries(monkeypatch):
    seen = {}

    class FakeClient:
        def __init__(self, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr("app.services.providers.openai.AsyncOpenAI", FakeClient)
    OpenAIProvider(api_key="test")
    assert seen["max_retries"] == 0
    assert seen["timeout"] == 60.0
