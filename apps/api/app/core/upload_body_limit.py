from __future__ import annotations

import asyncio
from collections.abc import Sequence

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


UPLOAD_MULTIPART_OVERHEAD_BYTES = 64 * 1024
UPLOAD_PATH = "/api/v1/uploads/questions"


def upload_request_body_limit(max_base64_bytes: int) -> int:
    max_raw_bytes = 3 * (max_base64_bytes // 4)
    return max_raw_bytes + UPLOAD_MULTIPART_OVERHEAD_BYTES


def _content_length(headers: Sequence[tuple[bytes, bytes]]) -> int | None:
    values = [value for name, value in headers if name.lower() == b"content-length"]
    if not values:
        return None
    if len(values) != 1:
        return -1
    try:
        decoded = values[0].decode("ascii")
    except UnicodeDecodeError:
        return -1
    if not decoded.isdecimal():
        return -1
    return int(decoded)


class UploadBodyLimitMiddleware:
    """Bound upload bodies before FastAPI parses multipart or resolves auth."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_body_bytes: int,
        semaphore: asyncio.Semaphore,
        queue_timeout_seconds: float,
    ) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.semaphore = semaphore
        self.queue_timeout_seconds = queue_timeout_seconds

    async def _error(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        status_code: int,
        code: str,
        message: str,
    ) -> None:
        response = JSONResponse(
            status_code=status_code,
            content={"code": code, "message": message},
        )
        await response(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or scope.get("path") != UPLOAD_PATH
        ):
            await self.app(scope, receive, send)
            return

        declared_length = _content_length(scope.get("headers", ()))
        if declared_length == -1:
            await self._error(
                scope,
                receive,
                send,
                status_code=400,
                code="OCR_INVALID_REQUEST",
                message="请求体长度无效",
            )
            return
        if declared_length is not None and declared_length > self.max_body_bytes:
            await self._error(
                scope,
                receive,
                send,
                status_code=413,
                code="OCR_FILE_TOO_LARGE",
                message="文件大小超过限制",
            )
            return

        try:
            await asyncio.wait_for(
                self.semaphore.acquire(),
                timeout=self.queue_timeout_seconds,
            )
        except TimeoutError:
            await self._error(
                scope,
                receive,
                send,
                status_code=429,
                code="UPLOAD_RATE_LIMITED",
                message="上传服务繁忙，请稍后重试",
            )
            return

        messages: list[Message] = []
        received = 0
        try:
            while True:
                message = await receive()
                if message["type"] != "http.request":
                    messages.append(message)
                    break
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    await self._error(
                        scope,
                        receive,
                        send,
                        status_code=413,
                        code="OCR_FILE_TOO_LARGE",
                        message="文件大小超过限制",
                    )
                    return
                messages.append(message)
                if not message.get("more_body", False):
                    break

            message_index = 0

            async def replay_receive() -> Message:
                nonlocal message_index
                if message_index < len(messages):
                    message = messages[message_index]
                    message_index += 1
                    return message
                return {"type": "http.request", "body": b"", "more_body": False}

            await self.app(scope, replay_receive, send)
        finally:
            self.semaphore.release()
