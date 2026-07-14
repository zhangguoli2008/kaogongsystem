import re
import secrets
from ipaddress import ip_address
from typing import Annotated, cast

import jwt
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.errors import APIError
from app.core.security import ALGORITHM, SESSION_COOKIE
from app.models.user import User
from app.services.ocr.service import OCRService


RAILWAY_EDGE_PATTERN = re.compile(r"railway/[a-z0-9-]+")
PROXY_SECRET_PATTERN = re.compile(r"[0-9a-f]{64}")


async def enforce_auth_rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    railway_client_ip = request.headers.get("X-Real-IP")
    railway_edge = request.headers.get("X-Railway-Edge")
    proxy_secret = request.headers.get("X-Kaogong-Proxy-Secret")
    configured_proxy_secret = request.app.state.settings.internal_proxy_secret
    if (
        configured_proxy_secret is not None
        and PROXY_SECRET_PATTERN.fullmatch(configured_proxy_secret)
        and proxy_secret is not None
        and PROXY_SECRET_PATTERN.fullmatch(proxy_secret)
        and secrets.compare_digest(proxy_secret, configured_proxy_secret)
        and railway_client_ip
        and "%" not in railway_client_ip
        and railway_edge
        and RAILWAY_EDGE_PATTERN.fullmatch(railway_edge)
    ):
        try:
            client_ip = ip_address(railway_client_ip).compressed
        except ValueError:
            pass
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


def get_ocr_service(request: Request) -> OCRService:
    return cast(OCRService, request.app.state.ocr_service)


OCRServiceDep = Annotated[OCRService, Depends(get_ocr_service)]
