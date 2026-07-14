from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url.removeprefix("postgres://")
    url = make_url(database_url)
    if url.get_backend_name() == "postgresql" and url.get_driver_name() != "psycopg":
        url = url.set(drivername="postgresql+psycopg")
    return url.render_as_string(hide_password=False)


def create_session_factory(database_url: str) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(
        normalize_database_url(database_url), pool_pre_ping=True
    )
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as session:
        yield session
