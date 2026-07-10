from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, enforce_auth_rate_limit
from app.core.database import get_session
from app.core.errors import APIError
from app.core.security import (
    SESSION_COOKIE,
    create_session_token,
    hash_password,
    verify_password,
)
from app.models.review import UserSettings
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest, UserResponse

router = APIRouter(prefix="/auth", tags=["auth"])
Session = Annotated[AsyncSession, Depends(get_session)]


def _set_session_cookie(response: Response, request: Request, user_id: str) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        key=SESSION_COOKIE,
        value=create_session_token(user_id, settings.jwt_secret),
        max_age=7 * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def register(
    payload: RegisterRequest,
    response: Response,
    request: Request,
    session: Session,
) -> User:
    existing = await session.scalar(select(User.id).where(User.email == payload.email))
    if existing is not None:
        raise APIError(409, "email_already_registered", "该邮箱已注册")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        settings=UserSettings(),
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise APIError(409, "email_already_registered", "该邮箱已注册") from exc
    await session.refresh(user)
    _set_session_cookie(response, request, user.id)
    return user


@router.post(
    "/login",
    response_model=UserResponse,
    dependencies=[Depends(enforce_auth_rate_limit)],
)
async def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    session: Session,
) -> User:
    user = await session.scalar(select(User).where(User.email == payload.email))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise APIError(401, "invalid_credentials", "邮箱或密码错误")
    _set_session_cookie(response, request, user.id)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request) -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=request.app.state.settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/me", response_model=UserResponse)
async def me(current_user: CurrentUser) -> User:
    return current_user
