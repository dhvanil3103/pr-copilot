import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from testcontainers.community.postgres import PostgresContainer

from shared.config import get_settings
from shared.db import make_engine, make_session_factory

pytestmark = pytest.mark.integration

# Docker Desktop on macOS exposes the socket via a symlink that the Ryuk cleanup
# container cannot mount; the in-VM path works there and on Linux CI alike.
os.environ.setdefault("TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE", "/var/run/docker.sock")


@pytest.fixture(scope="session")
def database_url(monkeypatch_session):
    with PostgresContainer("postgres:16.6-alpine", driver="asyncpg") as pg:
        url = pg.get_connection_url()
        # Migrations read DATABASE_URL through shared.config, same as production.
        monkeypatch_session.setenv("DATABASE_URL", url)
        get_settings.cache_clear()
        command.upgrade(Config("alembic.ini"), "head")
        yield url
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def monkeypatch_session():
    with pytest.MonkeyPatch.context() as mp:
        yield mp


@pytest.fixture
async def session_factory(database_url):
    engine = make_engine(database_url)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE reviews, comments RESTART IDENTITY CASCADE"))
    yield make_session_factory(engine)
    await engine.dispose()
