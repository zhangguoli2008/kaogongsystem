import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.dialects import postgresql

from app.core.errors import APIError
from app.core.rate_limit import RateLimiter
from app.models.question import Question
from app.schemas.analytics import AnalyticsAdviceResult
from app.services.analytics import trend_for_days


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


def test_trend_for_days_compiles_a_utc_date_bucket_for_postgresql():
    statements = []

    class PostgresSession:
        def get_bind(self):
            return type("Bind", (), {"dialect": postgresql.dialect()})()

        async def execute(self, statement):
            statements.append(statement)
            return []

    trends = asyncio.run(
        trend_for_days(
            PostgresSession(),
            "analytics-user",
            7,
            now=datetime(2026, 7, 10, 12, tzinfo=timezone.utc),
        )
    )

    sql = str(
        statements[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "date(timezone('UTC', questions.created_at))" in sql
    assert trends[0].date == "2026-07-04"
    assert trends[-1].date == "2026-07-10"


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


def test_analytics_gets_never_construct_a_provider(client, monkeypatch):
    cookies = register(client, "analytics-read-only@example.com")
    create_question(client, cookies)

    def provider_should_not_be_called(*args, **kwargs):
        raise AssertionError("read-only analytics must never construct a provider")

    monkeypatch.setattr(
        "app.api.routes.analytics.get_provider", provider_should_not_be_called
    )

    assert client.get("/api/v1/analytics/summary", cookies=cookies).status_code == 200
    assert client.get("/api/v1/dashboard", cookies=cookies).status_code == 200


def test_post_analytics_advice_uses_owner_aggregate_and_calls_provider_once(
    client, monkeypatch
):
    owner = register(client, "advice-owner@example.com")
    create_question(client, owner, module="资料分析", knowledge_points=["增长率"])
    other = register(client, "advice-other@example.com")
    create_question(client, other, module="判断推理", knowledge_points=["图形推理"])
    seen = {"calls": 0}

    class CapturingProvider:
        async def advise(self, payload, request_id=None):
            seen["calls"] += 1
            seen["payload"] = payload
            seen["request_id"] = request_id
            return AnalyticsAdviceResult(
                advice="先练增长率。",
                provider_name="test-provider",
                model_name="test-model",
                is_demo=False,
            )

    monkeypatch.setattr(
        "app.api.routes.analytics.get_provider", lambda settings: CapturingProvider()
    )
    response = client.post(
        "/api/v1/analytics/advice",
        cookies=owner,
        headers={"x-request-id": "advice-local-id"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "advice": "先练增长率。",
        "provider_name": "test-provider",
        "model_name": "test-model",
        "is_demo": False,
    }
    assert seen["calls"] == 1
    assert seen["request_id"] == "advice-local-id"
    assert seen["payload"].total_questions == 1
    assert {item.label for item in seen["payload"].module_distribution} == {"资料分析"}
    assert "图形推理" not in {
        item.label for item in seen["payload"].knowledge_point_ranking
    }


def test_post_analytics_advice_reuses_provider_rate_limit(client, monkeypatch):
    cookies = register(client, "advice-rate-limit@example.com")
    client.app.state.provider_rate_limiter = RateLimiter(limit=1, window_seconds=60)

    class Provider:
        async def advise(self, payload, request_id=None):
            del payload, request_id
            return AnalyticsAdviceResult(
                advice="建议",
                provider_name="demo",
                model_name=None,
                is_demo=True,
            )

    monkeypatch.setattr(
        "app.api.routes.analytics.get_provider", lambda settings: Provider()
    )
    first = client.post("/api/v1/analytics/advice", cookies=cookies)
    second = client.post("/api/v1/analytics/advice", cookies=cookies)

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["code"] == "provider_rate_limited"


def test_post_analytics_advice_revalidates_provider_result(client, monkeypatch):
    cookies = register(client, "advice-invalid@example.com")

    class InvalidProvider:
        async def advise(self, payload, request_id=None):
            del payload, request_id
            return {
                "advice": "looks valid",
                "provider_name": "malicious-provider",
                "model_name": None,
                "is_demo": False,
                "secret": "must not cross the route boundary",
            }

    monkeypatch.setattr(
        "app.api.routes.analytics.get_provider", lambda settings: InvalidProvider()
    )
    response = client.post("/api/v1/analytics/advice", cookies=cookies)

    assert response.status_code == 502
    assert response.json()["code"] == "provider_invalid_response"
    assert "secret" not in response.json()["message"]


def test_post_analytics_advice_preserves_stable_provider_api_error(client, monkeypatch):
    cookies = register(client, "advice-provider-error@example.com")

    class FailingProvider:
        async def advise(self, payload, request_id=None):
            del payload, request_id
            raise APIError(
                502,
                "provider_api_error",
                "AI 建议服务暂时不可用",
            )

    monkeypatch.setattr(
        "app.api.routes.analytics.get_provider", lambda settings: FailingProvider()
    )
    response = client.post("/api/v1/analytics/advice", cookies=cookies)

    assert response.status_code == 502
    assert response.json()["code"] == "provider_api_error"
    assert response.json()["message"] == "AI 建议服务暂时不可用"
