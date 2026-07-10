from __future__ import annotations

from datetime import datetime, timedelta
import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from app.api.routes.questions import router as questions_router
from app.main import create_app
from app.models.base import Base
from app.models.review import UserSettings  # noqa: F401
from app.models.user import User  # noqa: F401


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
    assert client.get(f"/api/v1/questions/{question_id}", cookies=cookies).status_code == 404


def test_question_is_isolated_by_user(client):
    first = register(client, "first@example.com")
    created = create_question(client, first)
    second = register(client, "second@example.com")

    response = client.get(f"/api/v1/questions/{created['id']}", cookies=second)
    assert response.status_code == 404
    listed = client.get("/api/v1/questions", cookies=second)
    assert listed.status_code == 200
    assert listed.json()["items"] == []
    assert client.patch(
        f"/api/v1/questions/{created['id']}",
        cookies=second,
        json={"notes": "不应可见"},
    ).status_code == 404


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

    page = client.get(
        "/api/v1/questions?page=2&page_size=2", cookies=cookies
    )
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
    assert client.get(
        f"/api/v1/questions/{question_one['id']}", cookies=first
    ).status_code == 404
    assert client.get(
        f"/api/v1/questions/{foreign['id']}", cookies=second
    ).status_code == 200


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


def test_bulk_routes_are_registered_before_id_route(client):
    paths = [
        route.path
        for route in questions_router.routes
        if hasattr(route, "path")
    ]

    assert paths.index("/questions/bulk-status") < paths.index(
        "/questions/{question_id}"
    )
    assert paths.index("/questions/bulk-delete") < paths.index(
        "/questions/{question_id}"
    )
