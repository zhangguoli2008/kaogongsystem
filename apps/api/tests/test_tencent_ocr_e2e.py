"""One-call opt-in smoke test for Tencent QuestionSplitOCR.

Configuration guards always run; only the real call is skipped unless
RUN_TENCENT_QUESTION_SPLIT_OCR_E2E=1. The test never prints credentials,
request bodies, image bytes, or ImageBase64.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import sys
from typing import Any

import pytest

from app.core.config import Settings
from app.services.ocr.normalizer import normalize_question_split_response
from app.services.storage import (
    EmptyFile,
    InvalidImage,
    InvalidPdf,
    UnsupportedImageType,
    inspect_file,
)
from app.services.ocr.tencent import TencentOCRProvider


RUN_REAL_OCR = os.getenv("RUN_TENCENT_QUESTION_SPLIT_OCR_E2E") == "1"


def _base64_length(raw_bytes: int) -> int:
    return 4 * ((raw_bytes + 2) // 3)


def _load_user_sample(
    configured_path: str | None, *, max_base64_bytes: int
) -> tuple[Path, bytes, str]:
    if not configured_path:
        pytest.fail("TENCENT_QUESTION_SPLIT_OCR_E2E_IMAGE is required")

    image_path = Path(configured_path).expanduser().resolve()
    if not image_path.is_file():
        pytest.fail("TENCENT_QUESTION_SPLIT_OCR_E2E_IMAGE is not a local file")

    try:
        if _base64_length(image_path.stat().st_size) > max_base64_bytes:
            pytest.fail("sample Base64 exceeds MAX_UPLOAD_BYTES")
        image_bytes = image_path.read_bytes()
    except OSError:
        pytest.fail("TENCENT_QUESTION_SPLIT_OCR_E2E_IMAGE is not readable")
    if _base64_length(len(image_bytes)) > max_base64_bytes:
        pytest.fail("sample Base64 exceeds MAX_UPLOAD_BYTES")

    try:
        inspection = inspect_file(image_bytes)
    except (EmptyFile, InvalidImage, InvalidPdf, UnsupportedImageType):
        pytest.fail("sample must be a valid PNG, JPEG, or BMP image")
    if inspection.file_kind != "image":
        pytest.fail("sample must be a valid PNG, JPEG, or BMP image")
    return image_path, image_bytes, inspection.mime_type


async def _assert_invalid_sample_fails_before_sdk(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    configured_path: Path | None,
    expected_message: str,
) -> None:
    monkeypatch.setenv("TENCENTCLOUD_SECRET_ID", "unit-test-secret-id")
    monkeypatch.setenv("TENCENTCLOUD_SECRET_KEY", "unit-test-secret-key")
    if configured_path is None:
        monkeypatch.delenv("TENCENT_QUESTION_SPLIT_OCR_E2E_IMAGE", raising=False)
    else:
        monkeypatch.setenv("TENCENT_QUESTION_SPLIT_OCR_E2E_IMAGE", str(configured_path))
    sdk_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    class ForbiddenProvider:
        def __init__(self, settings: Settings) -> None:
            self.settings = settings

        async def recognize_questions(self, *args: Any, **kwargs: Any) -> Any:
            sdk_calls.append((args, kwargs))
            raise AssertionError("invalid E2E configuration reached the SDK provider")

    monkeypatch.setattr(sys.modules[__name__], "TencentOCRProvider", ForbiddenProvider)
    with pytest.raises(pytest.fail.Exception, match=expected_message):
        await test_one_real_tencent_question_split_ocr_call(tmp_path)
    assert sdk_calls == []


@pytest.mark.anyio
async def test_real_ocr_requires_an_explicit_user_sample(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await _assert_invalid_sample_fails_before_sdk(
        monkeypatch,
        tmp_path,
        configured_path=None,
        expected_message="TENCENT_QUESTION_SPLIT_OCR_E2E_IMAGE is required",
    )


@pytest.mark.anyio
async def test_real_ocr_rejects_a_missing_sample_before_sdk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await _assert_invalid_sample_fails_before_sdk(
        monkeypatch,
        tmp_path,
        configured_path=tmp_path / "missing.png",
        expected_message="TENCENT_QUESTION_SPLIT_OCR_E2E_IMAGE is not a local file",
    )


@pytest.mark.anyio
async def test_real_ocr_rejects_an_unsupported_sample_before_sdk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sample = tmp_path / "not-an-image.txt"
    sample.write_text("not an OCR image", encoding="utf-8")
    await _assert_invalid_sample_fails_before_sdk(
        monkeypatch,
        tmp_path,
        configured_path=sample,
        expected_message="sample must be a valid PNG, JPEG, or BMP image",
    )


@pytest.mark.anyio
async def test_real_ocr_rejects_a_sample_over_the_base64_budget_before_sdk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sample = tmp_path / "oversized.png"
    sample.write_bytes(b"x" * ((10 * 1024 * 1024 // 4) * 3 + 1))
    await _assert_invalid_sample_fails_before_sdk(
        monkeypatch,
        tmp_path,
        configured_path=sample,
        expected_message="sample Base64 exceeds MAX_UPLOAD_BYTES",
    )


@pytest.mark.skipif(
    not RUN_REAL_OCR,
    reason="set RUN_TENCENT_QUESTION_SPLIT_OCR_E2E=1 for one real OCR call",
)
@pytest.mark.anyio
async def test_one_real_tencent_question_split_ocr_call(tmp_path: Path) -> None:
    # The opt-in smoke must make at most one billable SDK attempt, even when
    # production retries are configured for normal traffic.
    settings = Settings().model_copy(update={"tencentcloud_ocr_max_retries": 0})
    image_path, image_bytes, mime_type = _load_user_sample(
        os.getenv("TENCENT_QUESTION_SPLIT_OCR_E2E_IMAGE"),
        max_base64_bytes=settings.max_upload_bytes,
    )
    if not settings.tencentcloud_secret_id or not settings.tencentcloud_secret_key:
        pytest.fail(
            "real OCR smoke was enabled but backend Tencent credentials are missing"
        )

    response = await TencentOCRProvider(settings).recognize_questions(
        image_bytes,
        image_path.name,
        mime_type,
        pdf_page_number=1,
    )
    result = normalize_question_split_response(
        response,
        provider="tencent_question_split",
        file_id="local-e2e-file",
        page_number=1,
    )

    assert re.fullmatch(r"[A-Za-z0-9-]{1,128}", result.request_id)
    assert result.question_count >= 1
    print(f"Tencent RequestId: {result.request_id}")
    print(f"Question count: {result.question_count}")
    for question in result.questions:
        preview = question.question_text.replace("\n", " ")[:50]
        print(f"Question {question.index}: {preview}")
