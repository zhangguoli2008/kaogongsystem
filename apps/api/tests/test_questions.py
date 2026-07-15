from __future__ import annotations

from datetime import datetime, timedelta
import asyncio
from io import BytesIO
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.routes.questions import router as questions_router
from app.core.errors import APIError
from app.main import create_app
from app.models.analysis import Analysis
from app.models.base import Base
from app.models.question import Question
from app.models.review import UserSettings  # noqa: F401
from app.models.user import User  # noqa: F401
from app.schemas.analysis import AnalysisResult
from app.services.providers.demo import DemoProvider


@pytest.fixture
def client(test_settings):
    settings = test_settings.model_copy(
        update={"jwt_secret": "test-session-secret-at-least-32-bytes"}
    )
    engine = create_async_engine(settings.database_url)

    async def create_tables():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(create_tables())
    try:
        with TestClient(create_app(settings)) as test_client:
            yield test_client
    finally:
        asyncio.run(engine.dispose())


def question_payload(**overrides):
    payload = {
        "exam_type": "国考",
        "module": "资料分析",
        "stem": "某公司今年收入较去年增长多少？",
        "options": [
            {"label": "A", "content": "10%"},
            {"label": "B", "content": "20%"},
        ],
        "user_answer": "A",
        "correct_answer": "B",
        "original_explanation": "用增长量除以基期量。",
        "source": "2025 年真题",
        "notes": "复习计算公式",
        "knowledge_points": ["增长率", "资料分析基础"],
        "error_reason": "计算错",
        "tags": ["重点"],
    }
    payload.update(overrides)
    return payload


def register(client, email: str):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "strong-pass-123"},
    )
    assert response.status_code == 201, response.text
    return dict(response.cookies)


def create_question(client, cookies, **overrides):
    response = client.post(
        "/api/v1/questions", cookies=cookies, json=question_payload(**overrides)
    )
    assert response.status_code == 201, response.text
    return response.json()


def upload_question_image(
    client,
    cookies,
    *,
    color: str = "white",
    image_format: str = "PNG",
) -> dict:
    output = BytesIO()
    Image.new("RGB", (32, 32), color=color).save(output, format=image_format)
    suffix = image_format.casefold()
    response = client.post(
        "/api/v1/uploads/questions",
        cookies=cookies,
        files={
            "file": (
                f"question.{suffix}",
                output.getvalue(),
                f"image/{suffix}",
            )
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def ocr_metadata(source_asset_id: str, **overrides) -> dict:
    metadata = {
        "source": {"asset_id": source_asset_id},
        "question_number": "12",
        "question_type": "multiple_choice_unknown",
        "full_text": "12. OCR 识别原文",
        "question_elements": [],
        "coord": [],
        "crop": None,
        "figures": [],
        "tables": [],
        "options": [],
        "recognized_answer": "C",
        "recognized_parse": "OCR 从图片中识别出的解析",
        "warnings": [],
    }
    metadata.update(overrides)
    return metadata


def test_question_and_analysis_tables_register_with_api_router():
    assert {"questions", "analyses"}.issubset(Base.metadata.tables)


def test_question_crud_has_defaults_and_updates(client):
    cookies = register(client, "crud@example.com")
    created = create_question(client, cookies)

    assert created["exam_type"] == "国考"
    assert created["mastery_status"] == "未掌握"
    assert created["analysis_status"] == "未分析"
    assert created["knowledge_points"] == ["增长率", "资料分析基础"]

    question_id = created["id"]
    fetched = client.get(f"/api/v1/questions/{question_id}", cookies=cookies)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == question_id

    updated = client.patch(
        f"/api/v1/questions/{question_id}",
        cookies=cookies,
        json={"notes": "已掌握公式", "mastery_status": "复习中"},
    )
    assert updated.status_code == 200
    assert updated.json()["notes"] == "已掌握公式"
    assert updated.json()["mastery_status"] == "复习中"

    deleted = client.delete(f"/api/v1/questions/{question_id}", cookies=cookies)
    assert deleted.status_code == 204
    assert (
        client.get(f"/api/v1/questions/{question_id}", cookies=cookies).status_code
        == 404
    )


def test_question_persists_strict_ocr_metadata_with_server_derived_urls(client):
    cookies = register(client, "ocr-metadata@example.com")
    source = upload_question_image(client, cookies)
    crop = upload_question_image(client, cookies, color="red")
    figure = upload_question_image(client, cookies, color="green")
    table = upload_question_image(client, cookies, color="blue")
    option = upload_question_image(client, cookies, color="yellow")

    created = create_question(
        client,
        cookies,
        correct_answer="B",
        original_explanation="用户确认的解析",
        ocr_metadata=ocr_metadata(
            source["id"],
            crop={"asset_id": crop["id"]},
            figures=[
                {
                    "index": 1,
                    "text": "图形材料",
                    "coord": None,
                    "asset": {"asset_id": figure["id"]},
                }
            ],
            tables=[
                {
                    "index": 2,
                    "text": "统计表",
                    "coord": None,
                    "asset": {"asset_id": table["id"]},
                }
            ],
            options=[
                {
                    "label": "A",
                    "coord": None,
                    "asset": {"asset_id": option["id"]},
                }
            ],
        ),
    )

    metadata = created["ocr_metadata"]
    assert metadata["source"] == {
        "asset_id": source["id"],
        "image_url": f"/uploads/{source['id']}",
    }
    assert metadata["crop"]["image_url"] == f"/uploads/{crop['id']}"
    assert metadata["figures"][0]["asset"]["image_url"] == f"/uploads/{figure['id']}"
    assert metadata["tables"][0]["asset"]["image_url"] == f"/uploads/{table['id']}"
    assert metadata["options"][0]["asset"]["image_url"] == f"/uploads/{option['id']}"
    assert created["correct_answer"] == "B"
    assert created["original_explanation"] == "用户确认的解析"
    assert metadata["recognized_answer"] == "C"
    assert metadata["recognized_parse"] == "OCR 从图片中识别出的解析"

    serialized = json.dumps(created, ensure_ascii=False)
    assert str(client.app.state.settings.upload_dir) not in serialized
    assert "storage_name" not in serialized
    assert "base64" not in serialized.casefold()


@pytest.mark.parametrize(
    "reference_kind", ["source", "crop", "figure", "table", "option"]
)
def test_question_rejects_every_foreign_ocr_asset_reference(client, reference_kind):
    owner = register(client, f"ocr-owner-{reference_kind}@example.com")
    owner_source = upload_question_image(client, owner)
    other = register(client, f"ocr-other-{reference_kind}@example.com")
    foreign = upload_question_image(client, other)
    metadata = ocr_metadata(owner_source["id"])
    if reference_kind == "source":
        metadata["source"] = {"asset_id": foreign["id"]}
    elif reference_kind == "crop":
        metadata["crop"] = {"asset_id": foreign["id"]}
    elif reference_kind == "figure":
        metadata["figures"] = [
            {
                "index": 0,
                "text": None,
                "coord": None,
                "asset": {"asset_id": foreign["id"]},
            }
        ]
    elif reference_kind == "table":
        metadata["tables"] = [
            {
                "index": 0,
                "text": None,
                "coord": None,
                "asset": {"asset_id": foreign["id"]},
            }
        ]
    else:
        metadata["options"] = [
            {"label": "A", "coord": None, "asset": {"asset_id": foreign["id"]}}
        ]

    response = client.post(
        "/api/v1/questions",
        cookies=owner,
        json=question_payload(ocr_metadata=metadata),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_ocr_asset_reference"
    assert foreign["id"] not in response.text


def test_question_rejects_missing_and_malformed_ocr_asset_references(client):
    cookies = register(client, "ocr-invalid-reference@example.com")
    source = upload_question_image(client, cookies)

    missing = client.post(
        "/api/v1/questions",
        cookies=cookies,
        json=question_payload(ocr_metadata=ocr_metadata(str(uuid4()))),
    )
    malformed_url = client.post(
        "/api/v1/questions",
        cookies=cookies,
        json=question_payload(
            ocr_metadata=ocr_metadata(
                source["id"],
                crop={
                    "asset_id": source["id"],
                    "image_url": "https://untrusted.example/image.png",
                },
            )
        ),
    )
    extra_field = client.post(
        "/api/v1/questions",
        cookies=cookies,
        json=question_payload(
            ocr_metadata={**ocr_metadata(source["id"]), "untrusted": "value"}
        ),
    )

    assert missing.status_code == 422
    assert missing.json()["code"] == "invalid_ocr_asset_reference"
    assert malformed_url.status_code == 422
    assert malformed_url.json()["code"] == "invalid_ocr_asset_reference"
    assert extra_field.status_code == 422
    assert extra_field.json()["code"] == "validation_error"


def test_question_rejects_oversized_persisted_ocr_text_element(client):
    cookies = register(client, "ocr-text-bound@example.com")
    source = upload_question_image(client, cookies)
    metadata = ocr_metadata(source["id"])
    metadata["question_elements"] = [{"index": 0, "text": "字" * 20001, "coord": None}]

    response = client.post(
        "/api/v1/questions",
        cookies=cookies,
        json=question_payload(ocr_metadata=metadata),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_updating_recognized_answer_and_parse_never_overwrites_confirmed_fields(client):
    cookies = register(client, "ocr-answer-boundary@example.com")
    source = upload_question_image(client, cookies)
    created = create_question(
        client,
        cookies,
        correct_answer="B",
        original_explanation="用户确认的原解析",
        ocr_metadata=ocr_metadata(source["id"]),
    )

    updated_metadata = {
        **created["ocr_metadata"],
        "recognized_answer": "D",
        "recognized_parse": "更新后的 OCR 解析",
    }
    response = client.patch(
        f"/api/v1/questions/{created['id']}",
        cookies=cookies,
        json={"ocr_metadata": updated_metadata},
    )

    assert response.status_code == 200, response.text
    assert response.json()["correct_answer"] == "B"
    assert response.json()["original_explanation"] == "用户确认的原解析"
    assert response.json()["ocr_metadata"]["recognized_answer"] == "D"
    assert response.json()["ocr_metadata"]["recognized_parse"] == "更新后的 OCR 解析"


def test_question_update_rejects_foreign_ocr_asset_reference(client):
    owner = register(client, "ocr-update-owner@example.com")
    owner_source = upload_question_image(client, owner)
    created = create_question(client, owner)
    other = register(client, "ocr-update-other@example.com")
    foreign = upload_question_image(client, other)

    response = client.patch(
        f"/api/v1/questions/{created['id']}",
        cookies=owner,
        json={
            "ocr_metadata": ocr_metadata(
                owner_source["id"], crop={"asset_id": foreign["id"]}
            )
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_ocr_asset_reference"


def test_question_rejects_ocr_asset_whose_backing_file_is_missing(client):
    cookies = register(client, "ocr-file-missing@example.com")
    source = upload_question_image(client, cookies)
    (client.app.state.settings.upload_dir / source["storage_name"]).unlink()

    response = client.post(
        "/api/v1/questions",
        cookies=cookies,
        json=question_payload(ocr_metadata=ocr_metadata(source["id"])),
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_ocr_asset_reference"


@pytest.mark.parametrize("field", ["stem", "module"])
def test_question_update_rejects_null_for_required_fields(client, field):
    cookies = register(client, f"null-{field}@example.com")
    created = create_question(client, cookies)

    response = client.patch(
        f"/api/v1/questions/{created['id']}",
        cookies=cookies,
        json={field: None},
    )

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    assert (
        client.get(f"/api/v1/questions/{created['id']}", cookies=cookies).json()[field]
        == created[field]
    )


def test_question_update_allows_null_for_nullable_fields(client):
    cookies = register(client, "nullable@example.com")
    created = create_question(client, cookies, notes="临时笔记")

    response = client.patch(
        f"/api/v1/questions/{created['id']}",
        cookies=cookies,
        json={"notes": None},
    )

    assert response.status_code == 200
    assert response.json()["notes"] is None


def test_question_is_isolated_by_user(client):
    first = register(client, "first@example.com")
    created = create_question(client, first)
    second = register(client, "second@example.com")

    response = client.get(f"/api/v1/questions/{created['id']}", cookies=second)
    assert response.status_code == 404
    listed = client.get("/api/v1/questions", cookies=second)
    assert listed.status_code == 200
    assert listed.json()["items"] == []
    assert (
        client.patch(
            f"/api/v1/questions/{created['id']}",
            cookies=second,
            json={"notes": "不应可见"},
        ).status_code
        == 404
    )


def test_filters_question_library_and_paginates(client):
    cookies = register(client, "filters@example.com")
    create_question(
        client,
        cookies,
        module="资料分析",
        error_reason="计算错",
        knowledge_points=["增长率"],
    )
    create_question(
        client,
        cookies,
        module="言语理解",
        error_reason="理解错",
        knowledge_points=["主旨题"],
    )
    create_question(client, cookies, module="资料分析", error_reason="粗心")

    response = client.get(
        "/api/v1/questions?module=资料分析&error_reason=计算错&knowledge_point=增长率",
        cookies=cookies,
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert [item["module"] for item in response.json()["items"]] == ["资料分析"]

    page = client.get("/api/v1/questions?page=2&page_size=2", cookies=cookies)
    assert page.status_code == 200
    assert page.json()["page"] == 2
    assert page.json()["page_size"] == 2
    assert page.json()["total"] == 3
    assert len(page.json()["items"]) == 1


def test_question_filters_status_and_created_window(client):
    cookies = register(client, "window@example.com")
    first = create_question(client, cookies, mastery_status="已掌握")
    create_question(client, cookies, analysis_status="已完成")

    first_created = datetime.fromisoformat(first["created_at"])
    start = (first_created - timedelta(seconds=1)).isoformat()
    end = (first_created + timedelta(seconds=1)).isoformat()
    response = client.get(
        "/api/v1/questions",
        cookies=cookies,
        params={
            "mastery_status": "已掌握",
            "created_from": start,
            "created_to": end,
        },
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == first["id"]


def test_bulk_status_and_delete_are_scoped_and_report_missing_ids(client):
    first = register(client, "bulk-first@example.com")
    question_one = create_question(client, first)
    question_two = create_question(client, first)
    second = register(client, "bulk-second@example.com")
    foreign = create_question(client, second)

    status_response = client.post(
        "/api/v1/questions/bulk-status",
        cookies=first,
        json={
            "ids": [question_one["id"], question_two["id"], foreign["id"], "missing"],
            "mastery_status": "已掌握",
        },
    )
    assert status_response.status_code == 200
    assert status_response.json() == {
        "updated": 2,
        "not_found": [foreign["id"], "missing"],
    }

    delete_response = client.post(
        "/api/v1/questions/bulk-delete",
        cookies=first,
        json={"ids": [question_one["id"], foreign["id"], "missing"]},
    )
    assert delete_response.status_code == 200
    assert delete_response.json() == {
        "deleted": 1,
        "not_found": [foreign["id"], "missing"],
    }
    assert (
        client.get(f"/api/v1/questions/{question_one['id']}", cookies=first).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/questions/{foreign['id']}", cookies=second).status_code
        == 200
    )


def test_question_requests_require_auth_and_validate_bulk_limit(client):
    payload = question_payload()
    assert client.post("/api/v1/questions", json=payload).status_code == 401
    cookies = register(client, "validation@example.com")
    response = client.post(
        "/api/v1/questions/bulk-status",
        cookies=cookies,
        json={"ids": [str(index) for index in range(101)], "mastery_status": "已掌握"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


def test_manual_analysis_persists_structured_result(client):
    cookies = register(client, "analysis@example.com")
    question = create_question(client, cookies)

    response = client.post(
        f"/api/v1/questions/{question['id']}/analyze", cookies=cookies
    )

    assert response.status_code == 200
    analysis = response.json()
    assert analysis["is_demo"] is True
    assert analysis["cause_analysis"]
    assert analysis["knowledge_points"]
    assert analysis["correct_approach"]
    detail = client.get(f"/api/v1/questions/{question['id']}", cookies=cookies)
    assert detail.json()["analysis_status"] == "已完成"
    assert detail.json()["analysis_error_code"] is None
    assert detail.json()["current_analysis"]["id"] == analysis["id"]


def test_analysis_loads_owned_visual_bytes_by_storage_name_and_deduplicates(
    client, monkeypatch
):
    cookies = register(client, "analysis-images@example.com")
    source = upload_question_image(client, cookies, color="purple")
    question = create_question(
        client,
        cookies,
        ocr_metadata=ocr_metadata(
            source["id"],
            crop={"asset_id": source["id"]},
            figures=[
                {
                    "index": 0,
                    "text": None,
                    "coord": None,
                    "asset": {"asset_id": source["id"]},
                }
            ],
        ),
    )
    expected = (
        client.app.state.settings.upload_dir / source["storage_name"]
    ).read_bytes()
    seen = {}

    class CapturingProvider:
        async def analyze(self, payload, images=(), request_id=None):
            seen["payload"] = payload
            seen["images"] = list(images)
            return await DemoProvider().analyze(
                payload, images=images, request_id=request_id
            )

    monkeypatch.setattr(
        "app.api.routes.questions.get_provider", lambda settings: CapturingProvider()
    )
    response = client.post(
        f"/api/v1/questions/{question['id']}/analyze", cookies=cookies
    )

    assert response.status_code == 200, response.text
    assert len(seen["images"]) == 1
    assert seen["images"][0].mime_type == "image/png"
    assert seen["images"][0].content == expected
    assert "ocr_metadata" not in seen["payload"].model_dump()
    assert "base64" not in seen["payload"].model_dump_json().casefold()


def test_analysis_applies_visual_count_and_total_byte_budgets(client, monkeypatch):
    cookies = register(client, "analysis-image-budget@example.com")
    source = upload_question_image(client, cookies, color="red")
    crop = upload_question_image(client, cookies, color="green")
    figure = upload_question_image(client, cookies, color="blue")
    question = create_question(
        client,
        cookies,
        ocr_metadata=ocr_metadata(
            source["id"],
            crop={"asset_id": crop["id"]},
            figures=[
                {
                    "index": 0,
                    "text": None,
                    "coord": None,
                    "asset": {"asset_id": figure["id"]},
                }
            ],
        ),
    )
    captured_images: list[list[bytes]] = []

    class CapturingProvider:
        async def analyze(self, payload, images=(), request_id=None):
            captured_images.append([image.content for image in images])
            return await DemoProvider().analyze(
                payload, images=images, request_id=request_id
            )

    monkeypatch.setattr(
        "app.api.routes.questions.get_provider", lambda settings: CapturingProvider()
    )
    monkeypatch.setattr(
        "app.api.routes.questions.MAX_ANALYSIS_IMAGES", 2, raising=False
    )
    monkeypatch.setattr(
        "app.api.routes.questions.MAX_ANALYSIS_IMAGE_TOTAL_BYTES",
        100 * 1024 * 1024,
        raising=False,
    )
    first = client.post(f"/api/v1/questions/{question['id']}/analyze", cookies=cookies)

    monkeypatch.setattr(
        "app.api.routes.questions.MAX_ANALYSIS_IMAGES", 8, raising=False
    )
    monkeypatch.setattr(
        "app.api.routes.questions.MAX_ANALYSIS_IMAGE_TOTAL_BYTES",
        crop["size_bytes"],
        raising=False,
    )
    second = client.post(f"/api/v1/questions/{question['id']}/analyze", cookies=cookies)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    source_bytes = (
        client.app.state.settings.upload_dir / source["storage_name"]
    ).read_bytes()
    crop_bytes = (
        client.app.state.settings.upload_dir / crop["storage_name"]
    ).read_bytes()
    figure_bytes = (
        client.app.state.settings.upload_dir / figure["storage_name"]
    ).read_bytes()
    assert captured_images[0] == [crop_bytes, figure_bytes]
    assert captured_images[1] == [crop_bytes]
    assert source_bytes not in captured_images[0]


def test_analysis_revalidates_visual_asset_ownership_in_persisted_metadata(
    client, monkeypatch
):
    owner = register(client, "analysis-visual-owner@example.com")
    owner_source = upload_question_image(client, owner)
    question = create_question(
        client, owner, ocr_metadata=ocr_metadata(owner_source["id"])
    )
    other = register(client, "analysis-visual-other@example.com")
    foreign = upload_question_image(client, other)

    async def corrupt_metadata() -> None:
        async with client.app.state.session_factory() as session:
            stored = await session.get(Question, question["id"])
            assert stored is not None
            stored.ocr_metadata = ocr_metadata(foreign["id"])
            await session.commit()

    asyncio.run(corrupt_metadata())

    class MustNotRunProvider:
        async def analyze(self, payload, images=(), request_id=None):
            raise AssertionError("provider must not receive a foreign visual asset")

    monkeypatch.setattr(
        "app.api.routes.questions.get_provider", lambda settings: MustNotRunProvider()
    )
    response = client.post(f"/api/v1/questions/{question['id']}/analyze", cookies=owner)

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_ocr_asset_reference"
    assert foreign["id"] not in response.text


def test_analysis_rejects_visual_asset_missing_from_controlled_storage(
    client, monkeypatch
):
    cookies = register(client, "analysis-visual-missing@example.com")
    source = upload_question_image(client, cookies)
    question = create_question(client, cookies, ocr_metadata=ocr_metadata(source["id"]))
    (client.app.state.settings.upload_dir / source["storage_name"]).unlink()

    class MustNotRunProvider:
        async def analyze(self, payload, images=(), request_id=None):
            raise AssertionError("provider must not run with a missing visual asset")

    monkeypatch.setattr(
        "app.api.routes.questions.get_provider", lambda settings: MustNotRunProvider()
    )
    response = client.post(
        f"/api/v1/questions/{question['id']}/analyze", cookies=cookies
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_ocr_asset_reference"


def test_analysis_redecodes_stored_image_and_rejects_corrupted_content(
    client, monkeypatch
):
    cookies = register(client, "analysis-visual-corrupt@example.com")
    source = upload_question_image(client, cookies)
    question = create_question(client, cookies, ocr_metadata=ocr_metadata(source["id"]))
    (client.app.state.settings.upload_dir / source["storage_name"]).write_bytes(
        b"not-an-image"
    )

    class MustNotRunProvider:
        async def analyze(self, payload, images=(), request_id=None):
            raise AssertionError("provider must not receive corrupted image bytes")

    monkeypatch.setattr(
        "app.api.routes.questions.get_provider", lambda settings: MustNotRunProvider()
    )
    response = client.post(
        f"/api/v1/questions/{question['id']}/analyze", cookies=cookies
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_ocr_asset_reference"


def test_analysis_converts_verified_bmp_to_bounded_png_input(client, monkeypatch):
    cookies = register(client, "analysis-visual-bmp@example.com")
    source = upload_question_image(client, cookies, color="orange", image_format="BMP")
    question = create_question(client, cookies, ocr_metadata=ocr_metadata(source["id"]))
    seen = {}

    class CapturingProvider:
        async def analyze(self, payload, images=(), request_id=None):
            seen["images"] = list(images)
            return await DemoProvider().analyze(
                payload, images=images, request_id=request_id
            )

    monkeypatch.setattr(
        "app.api.routes.questions.get_provider", lambda settings: CapturingProvider()
    )
    response = client.post(
        f"/api/v1/questions/{question['id']}/analyze", cookies=cookies
    )

    assert response.status_code == 200, response.text
    assert len(seen["images"]) == 1
    assert seen["images"][0].mime_type == "image/png"
    with Image.open(BytesIO(seen["images"][0].content)) as converted:
        assert converted.format == "PNG"


def test_reanalysis_keeps_history_and_updates_current_analysis(client):
    cookies = register(client, "reanalysis@example.com")
    question = create_question(client, cookies)

    first = client.post(f"/api/v1/questions/{question['id']}/analyze", cookies=cookies)
    second = client.post(f"/api/v1/questions/{question['id']}/analyze", cookies=cookies)
    detail = client.get(f"/api/v1/questions/{question['id']}", cookies=cookies)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] != second.json()["id"]
    assert detail.json()["current_analysis"]["id"] == second.json()["id"]
    assert detail.json()["analysis_error_code"] is None

    async def history_count() -> int:
        async with client.app.state.session_factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(Analysis)
                .where(Analysis.question_id == question["id"])
            )
        return count or 0

    assert asyncio.run(history_count()) == 2


def test_question_analysis_is_isolated_by_user(client):
    owner = register(client, "analysis-owner@example.com")
    question = create_question(client, owner)
    other = register(client, "analysis-other@example.com")

    response = client.post(f"/api/v1/questions/{question['id']}/analyze", cookies=other)

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_analysis_failure_marks_question_failed_without_provider_detail(
    client, monkeypatch
):
    cookies = register(client, "analysis-failure@example.com")
    question = create_question(client, cookies)

    class FailingProvider:
        async def analyze(self, payload, request_id=None):
            del payload, request_id
            raise APIError(502, "provider_api_error", "supplier detail: secret")

    monkeypatch.setattr(
        "app.api.routes.questions.get_provider", lambda settings: FailingProvider()
    )
    response = client.post(
        f"/api/v1/questions/{question['id']}/analyze", cookies=cookies
    )
    detail = client.get(f"/api/v1/questions/{question['id']}", cookies=cookies)

    assert response.status_code == 502
    assert response.json()["code"] == "provider_api_error"
    assert "supplier detail" not in response.json()["message"]
    assert detail.json()["analysis_status"] == "失败"
    assert detail.json()["analysis_error_code"] == "provider_api_error"
    assert detail.json()["current_analysis"] is None


def test_successful_reanalysis_clears_prior_failure_code(client, monkeypatch):
    cookies = register(client, "analysis-recovery@example.com")
    question = create_question(client, cookies)

    class FailingProvider:
        async def analyze(self, payload, request_id=None):
            del payload, request_id
            raise APIError(504, "provider_timeout", "supplier detail")

    monkeypatch.setattr(
        "app.api.routes.questions.get_provider", lambda settings: FailingProvider()
    )
    failed = client.post(f"/api/v1/questions/{question['id']}/analyze", cookies=cookies)
    assert failed.status_code == 504
    assert (
        client.get(f"/api/v1/questions/{question['id']}", cookies=cookies).json()[
            "analysis_error_code"
        ]
        == "provider_timeout"
    )

    monkeypatch.setattr(
        "app.api.routes.questions.get_provider", lambda settings: DemoProvider()
    )
    recovered = client.post(
        f"/api/v1/questions/{question['id']}/analyze", cookies=cookies
    )
    detail = client.get(f"/api/v1/questions/{question['id']}", cookies=cookies)

    assert recovered.status_code == 200
    assert detail.json()["analysis_status"] == "已完成"
    assert detail.json()["analysis_error_code"] is None


def test_invalid_analysis_result_marks_question_failed_and_returns_stable_code(
    client, monkeypatch
):
    cookies = register(client, "analysis-invalid-result@example.com")
    question = create_question(client, cookies)

    class InvalidResultProvider:
        async def analyze(self, payload, request_id=None):
            del payload, request_id
            return object()

    monkeypatch.setattr(
        "app.api.routes.questions.get_provider",
        lambda settings: InvalidResultProvider(),
    )
    response = client.post(
        f"/api/v1/questions/{question['id']}/analyze", cookies=cookies
    )
    detail = client.get(f"/api/v1/questions/{question['id']}", cookies=cookies)

    assert response.status_code == 502
    assert response.json()["code"] == "provider_invalid_response"
    assert detail.json()["analysis_status"] == "失败"
    assert detail.json()["analysis_error_code"] == "provider_invalid_response"


def test_mutated_analysis_result_is_revalidated_before_persistence(client, monkeypatch):
    cookies = register(client, "analysis-mutated-result@example.com")
    question = create_question(client, cookies)

    class MutatedResultProvider:
        async def analyze(self, payload, request_id=None):
            del payload, request_id
            result = AnalysisResult(
                cause_analysis="原因",
                knowledge_points=["知识点"],
                correct_approach="思路",
                study_advice="建议",
                suggested_error_reason="计算错",
                raw_response={},
                provider_name="test",
                model_name="test",
                is_demo=False,
            )
            result.suggested_error_reason = "bad"
            return result

    monkeypatch.setattr(
        "app.api.routes.questions.get_provider",
        lambda settings: MutatedResultProvider(),
    )
    response = client.post(
        f"/api/v1/questions/{question['id']}/analyze", cookies=cookies
    )
    detail = client.get(f"/api/v1/questions/{question['id']}", cookies=cookies)

    assert response.status_code == 502
    assert response.json()["code"] == "provider_invalid_response"
    assert detail.json()["analysis_status"] == "失败"
    assert detail.json()["analysis_error_code"] == "provider_invalid_response"


def test_analysis_uses_per_user_provider_rate_limit(client):
    cookies = register(client, "analysis-rate-limit@example.com")
    question = create_question(client, cookies)

    responses = [
        client.post(f"/api/v1/questions/{question['id']}/analyze", cookies=cookies)
        for _ in range(11)
    ]

    assert [response.status_code for response in responses[:10]] == [200] * 10
    assert responses[10].status_code == 429
    assert responses[10].json()["code"] == "provider_rate_limited"


def test_bulk_routes_are_registered_before_id_route(client):
    paths = [route.path for route in questions_router.routes if hasattr(route, "path")]

    assert paths.index("/questions/bulk-status") < paths.index(
        "/questions/{question_id}"
    )
    assert paths.index("/questions/bulk-delete") < paths.index(
        "/questions/{question_id}"
    )
