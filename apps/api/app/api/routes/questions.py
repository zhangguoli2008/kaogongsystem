from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_session
from app.core.errors import APIError
from app.models.question import Question
from app.schemas.common import BulkIds
from app.schemas.question import (
    AnalysisStatus,
    BulkStatusRequest,
    ErrorReason,
    ExamModule,
    MasteryStatus,
    QuestionCreate,
    QuestionPage,
    QuestionRead,
    QuestionUpdate,
)

router = APIRouter(prefix="/questions", tags=["questions"])
Session = Annotated[AsyncSession, Depends(get_session)]


def _not_found() -> APIError:
    return APIError(404, "not_found", "错题不存在")


async def _get_owned_question(
    question_id: str, user_id: str, session: AsyncSession
) -> Question:
    question = await session.scalar(
        select(Question).where(Question.id == question_id, Question.user_id == user_id)
    )
    if question is None:
        raise _not_found()
    return question


def _knowledge_point_filter(knowledge_point: str, session: AsyncSession):
    """Return an EXISTS predicate that works with SQLite and PostgreSQL JSON arrays."""
    if session.get_bind().dialect.name == "postgresql":
        points = func.json_array_elements_text(
            Question.knowledge_points
        ).table_valued("value")
    else:
        points = func.json_each(Question.knowledge_points).table_valued("value")
    return (
        select(1)
        .select_from(points)
        .where(points.c.value == knowledge_point)
        .correlate(Question)
        .exists()
    )


@router.post("", response_model=QuestionRead, status_code=status.HTTP_201_CREATED)
async def create_question(
    payload: QuestionCreate, current_user: CurrentUser, session: Session
) -> Question:
    values = payload.model_dump(mode="json")
    values["user_id"] = current_user.id
    question = Question(**values)
    session.add(question)
    await session.commit()
    await session.refresh(question)
    return question


@router.get("", response_model=QuestionPage)
async def list_questions(
    current_user: CurrentUser,
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    module: ExamModule | None = None,
    knowledge_point: str | None = Query(default=None, min_length=1),
    error_reason: ErrorReason | None = None,
    mastery_status: MasteryStatus | None = None,
    analysis_status: AnalysisStatus | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> QuestionPage:
    filters = [Question.user_id == current_user.id]
    if module is not None:
        filters.append(Question.module == module.value)
    if knowledge_point is not None:
        filters.append(_knowledge_point_filter(knowledge_point, session))
    if error_reason is not None:
        filters.append(Question.error_reason == error_reason.value)
    if mastery_status is not None:
        filters.append(Question.mastery_status == mastery_status.value)
    if analysis_status is not None:
        filters.append(Question.analysis_status == analysis_status.value)
    if created_from is not None:
        filters.append(Question.created_at >= created_from)
    if created_to is not None:
        filters.append(Question.created_at <= created_to)

    count = await session.scalar(
        select(func.count()).select_from(Question).where(*filters)
    )
    result = await session.scalars(
        select(Question)
        .where(*filters)
        .order_by(Question.created_at.desc(), Question.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return QuestionPage(
        items=list(result), page=page, page_size=page_size, total=count or 0
    )


@router.post("/bulk-status")
async def bulk_update_status(
    payload: BulkStatusRequest, current_user: CurrentUser, session: Session
) -> dict[str, int | list[str]]:
    questions = list(
        await session.scalars(
            select(Question).where(
                Question.user_id == current_user.id, Question.id.in_(payload.ids)
            )
        )
    )
    found_ids = {question.id for question in questions}
    not_found = [
        question_id for question_id in payload.ids if question_id not in found_ids
    ]
    for question in questions:
        question.mastery_status = payload.mastery_status.value
    await session.commit()
    return {"updated": len(questions), "not_found": not_found}


@router.post("/bulk-delete")
async def bulk_delete(
    payload: BulkIds, current_user: CurrentUser, session: Session
) -> dict[str, int | list[str]]:
    questions = list(
        await session.scalars(
            select(Question).where(
                Question.user_id == current_user.id, Question.id.in_(payload.ids)
            )
        )
    )
    found_ids = {question.id for question in questions}
    not_found = [
        question_id for question_id in payload.ids if question_id not in found_ids
    ]
    for question in questions:
        await session.delete(question)
    await session.commit()
    return {"deleted": len(questions), "not_found": not_found}


@router.get("/{question_id}", response_model=QuestionRead)
async def read_question(
    question_id: str, current_user: CurrentUser, session: Session
) -> Question:
    return await _get_owned_question(question_id, current_user.id, session)


@router.patch("/{question_id}", response_model=QuestionRead)
async def update_question(
    question_id: str,
    payload: QuestionUpdate,
    current_user: CurrentUser,
    session: Session,
) -> Question:
    question = await _get_owned_question(question_id, current_user.id, session)
    for key, value in payload.model_dump(exclude_unset=True, mode="json").items():
        setattr(question, key, value)
    await session.commit()
    await session.refresh(question)
    return question


@router.delete("/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_question(
    question_id: str, current_user: CurrentUser, session: Session
) -> Response:
    question = await _get_owned_question(question_id, current_user.id, session)
    await session.delete(question)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
