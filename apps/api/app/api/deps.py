from typing import Annotated

import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.errors import APIError
from app.core.security import ALGORITHM, SESSION_COOKIE
from app.models.user import User


async def enforce_auth_rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    if not request.app.state.auth_rate_limiter.allow(client_ip):
        raise APIError(
            status_code=429,
            code="auth_rate_limit_exceeded",
            message="认证请求过于频繁，请稍后再试",
        )


async def get_current_user(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise APIError(401, "invalid_session", "请先登录")
    try:
        payload = jwt.decode(
            token,
            request.app.state.settings.jwt_secret,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "exp"]},
        )
        user_id = payload["sub"]
        if not isinstance(user_id, str) or not user_id:
            raise jwt.InvalidTokenError("invalid subject")
    except jwt.InvalidTokenError as exc:
        raise APIError(401, "invalid_session", "登录状态无效或已过期") from exc

    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise APIError(401, "invalid_session", "登录状态无效或已过期")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
