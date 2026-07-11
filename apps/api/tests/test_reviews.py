import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.models.question import Question
from app.models.review import ReviewRecord, UserSettings
from app.schemas.question import MasteryStatus
from app.services.review import score_review_candidate


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


def submit_review(client, cookies, question_id: str, result_status: str = "复习中"):
    response = client.post(
        f"/api/v1/reviews/{question_id}",
        cookies=cookies,
        json={"result_status": result_status, "review_note": "今天复盘"},
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


def set_review_limit(client, user_id: str, limit: int) -> None:
    async def set_limit():
        async with client.app.state.session_factory() as session:
            await session.execute(
                update(UserSettings)
                .where(UserSettings.user_id == user_id)
                .values(daily_review_limit=limit)
            )
            await session.commit()

    asyncio.run(set_limit())


def set_reviewed_at(client, review_id: str, reviewed_at: datetime) -> None:
    async def set_timestamp():
        async with client.app.state.session_factory() as session:
            await session.execute(
                update(ReviewRecord)
                .where(ReviewRecord.id == review_id)
                .values(reviewed_at=reviewed_at)
            )
            await session.commit()

    asyncio.run(set_timestamp())


def test_review_score_matches_spec():
    now = datetime(2026, 7, 10, tzinfo=timezone.utc)
    question = Question(
        mastery_status=MasteryStatus.UNMASTERED.value,
        created_at=now - timedelta(days=2),
        knowledge_points=["增长率计算"],
    )

    assert score_review_candidate(question, {"增长率计算"}, now) == 150


def test_review_candidates_are_scored_stably_and_limited(client):
    cookies = register(client, "review-sort@example.com")
    old_unmastered = create_question(client, cookies, knowledge_points=["旧知识点"])
    reviewing = create_question(
        client, cookies, mastery_status="复习中", knowledge_points=["复习知识点"]
    )
    recent_unmastered = create_question(
        client, cookies, knowledge_points=["增长率", "资料分析"]
    )
    oldest = datetime.now(timezone.utc) - timedelta(days=8)
    set_question_created_at(client, old_unmastered["id"], oldest)
    set_question_created_at(client, reviewing["id"], oldest)

    today = client.get("/api/v1/reviews/today", cookies=cookies)

    assert today.status_code == 200
    pending = today.json()["pending"]
    assert [item["id"] for item in pending[:3]] == [
        recent_unmastered["id"],
        old_unmastered["id"],
        reviewing["id"],
    ]


def test_today_review_honors_user_limit(client):
    cookies = register(client, "review-limit@example.com")
    questions = [create_question(client, cookies) for _ in range(12)]
    set_review_limit(client, questions[0]["user_id"], 10)

    response = client.get("/api/v1/reviews/today", cookies=cookies)

    assert response.status_code == 200
    assert response.json()["daily_review_limit"] == 10
    assert len(response.json()["pending"]) == 10


def test_today_review_uses_remaining_capacity_after_completed_reviews(client):
    cookies = register(client, "review-capacity@example.com")
    questions = [create_question(client, cookies) for _ in range(11)]
    set_review_limit(client, questions[0]["user_id"], 10)
    submit_review(client, cookies, questions[0]["id"])

    response = client.get("/api/v1/reviews/today", cookies=cookies)

    assert response.status_code == 200
    today = response.json()
    assert len(today["pending"]) == 9
    assert today["completed_count"] == 1
    assert today["total"] == 10


@pytest.mark.parametrize("limit", [10, 20, 30, 50])
def test_daily_review_limit_accepts_only_product_options(limit):
    from app.schemas.review import ReviewSettingsUpdate

    assert ReviewSettingsUpdate(daily_review_limit=limit).daily_review_limit == limit


def test_daily_review_limit_rejects_other_values():
    from pydantic import ValidationError

    from app.schemas.review import ReviewSettingsUpdate

    with pytest.raises(ValidationError):
        ReviewSettingsUpdate(daily_review_limit=15)


def test_review_settings_only_persist_allowed_daily_limits(client):
    cookies = register(client, "review-settings@example.com")

    changed = client.patch(
        "/api/v1/reviews/settings",
        cookies=cookies,
        json={"daily_review_limit": 30},
    )
    rejected = client.patch(
        "/api/v1/reviews/settings",
        cookies=cookies,
        json={"daily_review_limit": 15},
    )

    assert changed.status_code == 200
    assert changed.json() == {"daily_review_limit": 30}
    assert rejected.status_code == 422


def test_reviewed_today_is_completed_not_pending_and_updates_mastery(client):
    cookies = register(client, "review-complete@example.com")
    question = create_question(client, cookies)

    submitted = submit_review(client, cookies, question["id"], "复习中")
    today = client.get("/api/v1/reviews/today", cookies=cookies).json()
    detail = client.get(f"/api/v1/questions/{question['id']}", cookies=cookies).json()

    assert submitted["question_id"] == question["id"]
    assert question["id"] not in [item["id"] for item in today["pending"]]
    assert question["id"] in [item["question_id"] for item in today["completed"]]
    assert detail["mastery_status"] == "复习中"


def test_review_submission_is_scoped_to_the_current_user(client):
    owner = register(client, "review-owner@example.com")
    question = create_question(client, owner)
    other = register(client, "review-other@example.com")

    response = client.post(
        f"/api/v1/reviews/{question['id']}",
        cookies=other,
        json={"result_status": "已掌握"},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_question_review_history_is_empty_for_an_owned_question(client):
    cookies = register(client, "review-history-empty@example.com")
    question = create_question(client, cookies)

    response = client.get(
        f"/api/v1/reviews/questions/{question['id']}", cookies=cookies
    )

    assert response.status_code == 200
    assert response.json() == []


def test_question_review_history_is_newest_first_and_question_scoped(client):
    cookies = register(client, "review-history-order@example.com")
    question = create_question(client, cookies)
    other_question = create_question(client, cookies)
    older = submit_review(client, cookies, question["id"], "复习中")
    newer = submit_review(client, cookies, question["id"], "已掌握")
    submit_review(client, cookies, other_question["id"], "未掌握")
    now = datetime.now(timezone.utc)
    set_reviewed_at(client, older["id"], now - timedelta(days=1))
    set_reviewed_at(client, newer["id"], now)

    response = client.get(
        f"/api/v1/reviews/questions/{question['id']}", cookies=cookies
    )

    assert response.status_code == 200
    assert [record["id"] for record in response.json()] == [newer["id"], older["id"]]


def test_question_review_history_hides_another_users_question(client):
    owner = register(client, "review-history-owner@example.com")
    question = create_question(client, owner)
    submit_review(client, owner, question["id"])
    other = register(client, "review-history-other@example.com")

    response = client.get(
        f"/api/v1/reviews/questions/{question['id']}", cookies=other
    )

    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
