import asyncio
import base64
from types import SimpleNamespace

import httpx
import pytest
from openai import APIConnectionError

from app.core.errors import APIError
from app.services.providers.demo import DemoProvider
from app.services.providers.openai import OpenAIProvider


def test_demo_provider_has_four_options():
    result = __import__("asyncio").run(DemoProvider().ocr(b"", "image/png"))
    assert result.is_demo is True
    assert len(result.options) == 4
    assert result.correct_answer


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
    option_schema = seen["text"]["format"]["schema"]["$defs"]["QuestionOption"]
    assert option_schema["additionalProperties"] is False


def test_openai_connection_errors_map_to_stable_api_error():
    class FakeResponses:
        async def create(self, **kwargs):
            request = httpx.Request("POST", "https://api.openai.com/v1/responses")
            raise APIConnectionError(request=request)

    class FakeClient:
        responses = FakeResponses()

    provider = OpenAIProvider(api_key="test", client=FakeClient())
    with pytest.raises(APIError) as caught:
        asyncio.run(provider.ocr(b"hello", "image/png"))
    assert caught.value.code == "provider_connection_error"
