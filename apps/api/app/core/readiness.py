from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class ReadinessError(RuntimeError):
    def __init__(self, component: Literal["database", "uploads"]):
        super().__init__(component)
        self.component = component


async def probe_readiness(
    session_factory: async_sessionmaker[AsyncSession], upload_dir: Path
) -> None:
    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise ReadinessError("database") from exc

    try:
        upload_dir.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(
            mode="wb", prefix=".readiness-", dir=upload_dir, delete=True
        ) as probe:
            probe.write(b"ready")
            probe.flush()
    except OSError as exc:
        raise ReadinessError("uploads") from exc
