import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from app.models.question import Question


def question_payload(**overrides):
    payload = {
        "exam_type": "国考",
        "module": "资料分析",
        "stem": "某公司今年收入较去年增长多少？",
        "options": [{"label": "A", "content": "10%"}],
        "user_answer": "A",
        "correct_answer": "B",
        "knowledge_points": ["增长率"],
        "error_reason": "计算错",
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


def set_question_created_at(client, question_id: str, created_at: datetime) -> None:
    async def set_created_at():
        async with client.app.state.session_factory() as session:
            await session.execute(
                update(Question)
                .where(Question.id == question_id)
                .values(created_at=created_at)
            )
            await session.commit()

    asyncio.run(set_created_at())


def values_by_label(items):
    return {item["label"]: item["count"] for item in items}


def test_analytics_aggregates_only_current_user_and_fills_trends(client):
    owner = register(client, "analytics-owner@example.com")
    now = datetime.now(timezone.utc)
    today = create_question(
        client,
        owner,
        module="资料分析",
        knowledge_points=["增长率", "比重"],
        error_reason="计算错",
    )
    older = create_question(
        client,
        owner,
        module="言语理解",
        knowledge_points=["增长率"],
        error_reason="理解错",
        mastery_status="复习中",
    )
    set_question_created_at(client, older["id"], now - timedelta(days=2))

    other = register(client, "analytics-other@example.com")
    create_question(client, other, module="判断推理", knowledge_points=["图形推理"])

    response = client.get("/api/v1/analytics/summary", cookies=owner)

    assert response.status_code == 200, response.text
    summary = response.json()
    assert summary["total_questions"] == 2
    assert values_by_label(summary["module_distribution"]) == {
        "资料分析": 1,
        "言语理解": 1,
    }
    assert values_by_label(summary["knowledge_point_ranking"])["增长率"] == 2
    assert values_by_label(summary["error_reason_distribution"]) == {
        "计算错": 1,
        "理解错": 1,
    }
    assert values_by_label(summary["mastery_distribution"]) == {
        "未掌握": 1,
        "复习中": 1,
    }
    trend_7d = {point["date"]: point["count"] for point in summary["trend_7d"]}
    assert len(summary["trend_7d"]) == 7
    assert len(summary["trend_30d"]) == 30
    assert trend_7d[now.date().isoformat()] == 1
    assert trend_7d[(now - timedelta(days=2)).date().isoformat()] == 1
    assert 0 in trend_7d.values()
    assert summary["is_demo"] is True
    assert any(
        item["label"] in summary["ai_summary"]
        for item in summary["module_distribution"]
    )
    assert "增长率" in summary["ai_summary"]


def test_dashboard_uses_current_user_data_and_never_calls_a_provider(client, monkeypatch):
    owner = register(client, "dashboard-owner@example.com")
    first = create_question(client, owner, module="数量关系")
    second = create_question(client, owner, module="资料分析")
    other = register(client, "dashboard-other@example.com")
    foreign = create_question(client, other, module="判断推理")

    def provider_should_not_be_called(*args, **kwargs):
        raise AssertionError("dashboard must not make a paid provider request")

    monkeypatch.setattr(
        "app.services.providers.factory.get_provider", provider_should_not_be_called
    )
    response = client.get("/api/v1/dashboard", cookies=owner)

    assert response.status_code == 200, response.text
    dashboard = response.json()
    assert dashboard["provider_mode"] == "demo"
    assert dashboard["current_question"]["id"] in {first["id"], second["id"]}
    assert foreign["id"] not in [item["id"] for item in dashboard["recent_questions"]]
    assert len(dashboard["trend_7d"]) == 7
    assert dashboard["ai_advice"]
