import asyncio
import importlib
import inspect
from collections import Counter
from importlib.util import find_spec
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.security import hash_password, verify_password
from app.models.analysis import Analysis
from app.models.base import Base
from app.models.question import Question
from app.models.review import ReviewRecord, UserSettings
from app.models.user import User
from app.seed import seed_demo_data


def test_seed_module_exposes_async_seed_entrypoint() -> None:
    spec = find_spec("app.seed")

    assert spec is not None, "app.seed must provide the reproducible demo dataset"
    seed_module = importlib.import_module("app.seed")
    assert inspect.iscoroutinefunction(seed_module.seed_demo_data)


def test_seed_is_idempotent_and_covers_the_demo_diagnosis_flow(
    tmp_path: Path,
) -> None:
    async def exercise_seed() -> None:
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'seed.db'}")
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)

            async with session_factory() as session:
                await seed_demo_data(session)

            async with session_factory() as session:
                user = await session.scalar(
                    select(User).where(User.email == "demo@example.com")
                )
                assert user is not None
                assert verify_password("demo-pass-123", user.password_hash)

                settings = await session.get(UserSettings, user.id)
                assert settings is not None
                assert settings.daily_review_limit == 20

                questions = list(
                    await session.scalars(
                        select(Question)
                        .where(Question.user_id == user.id)
                        .order_by(Question.id)
                    )
                )
                assert len(questions) == 10
                assert Counter(question.module for question in questions) == {
                    "言语理解": 2,
                    "数量关系": 2,
                    "判断推理": 2,
                    "资料分析": 2,
                    "常识判断": 2,
                }
                assert {question.mastery_status for question in questions} == {
                    "未掌握",
                    "复习中",
                    "已掌握",
                }
                assert {question.error_reason for question in questions} == {
                    "粗心",
                    "不会",
                    "理解错",
                    "计算错",
                    "时间不够",
                }
                assert all(question.analysis_status == "已完成" for question in questions)
                assert all(question.current_analysis_id for question in questions)

                analyses = list(
                    await session.scalars(
                        select(Analysis).where(Analysis.user_id == user.id)
                    )
                )
                reviews = list(
                    await session.scalars(
                        select(ReviewRecord).where(ReviewRecord.user_id == user.id)
                    )
                )
                assert len(analyses) == 10
                assert all(analysis.is_demo for analysis in analyses)
                assert len(reviews) >= 5

                counts_before = {
                    "users": await session.scalar(select(func.count(User.id))),
                    "questions": await session.scalar(select(func.count(Question.id))),
                    "analyses": await session.scalar(select(func.count(Analysis.id))),
                    "reviews": await session.scalar(select(func.count(ReviewRecord.id))),
                }

            async with session_factory() as session:
                user = await session.scalar(
                    select(User).where(User.email == "demo@example.com")
                )
                assert user is not None
                user.password_hash = hash_password("temporarily-changed-password")
                await session.commit()

            async with session_factory() as session:
                await seed_demo_data(session)

            async with session_factory() as session:
                user = await session.scalar(
                    select(User).where(User.email == "demo@example.com")
                )
                assert user is not None
                assert verify_password("demo-pass-123", user.password_hash)
                counts_after = {
                    "users": await session.scalar(select(func.count(User.id))),
                    "questions": await session.scalar(select(func.count(Question.id))),
                    "analyses": await session.scalar(select(func.count(Analysis.id))),
                    "reviews": await session.scalar(select(func.count(ReviewRecord.id))),
                }
                assert counts_after == counts_before
        finally:
            await engine.dispose()

    asyncio.run(exercise_seed())
