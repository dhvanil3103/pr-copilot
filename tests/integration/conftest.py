import os
import socket

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from testcontainers.community.postgres import PostgresContainer
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from shared.config import get_settings
from shared.db import make_engine, make_session_factory

pytestmark = pytest.mark.integration

# Docker Desktop on macOS exposes the socket via a symlink that the Ryuk cleanup
# container cannot mount; the in-VM path works there and on Linux CI alike.
os.environ.setdefault("TESTCONTAINERS_DOCKER_SOCKET_OVERRIDE", "/var/run/docker.sock")

# Same images as docker-compose.yml and the Helm chart.
POSTGRES_IMAGE = "postgres:16.6-alpine"
KAFKA_IMAGE = "apache/kafka:3.9.0"


@pytest.fixture(scope="session")
def database_url(monkeypatch_session):
    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as pg:
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


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def kafka_bootstrap():
    """Single-broker KRaft Kafka from the official apache/kafka image, like docker compose.

    The host port is fixed up front because Kafka must advertise the exact
    address clients connect to, which a random mapped port would not match.
    """
    port = _free_port()
    container = (
        DockerContainer(KAFKA_IMAGE)
        .with_bind_ports(9092, port)
        .with_envs(
            KAFKA_NODE_ID="1",
            KAFKA_PROCESS_ROLES="broker,controller",
            KAFKA_LISTENERS="PLAINTEXT://:9092,CONTROLLER://:9093",
            KAFKA_ADVERTISED_LISTENERS=f"PLAINTEXT://localhost:{port}",
            KAFKA_LISTENER_SECURITY_PROTOCOL_MAP="PLAINTEXT:PLAINTEXT,CONTROLLER:PLAINTEXT",
            KAFKA_CONTROLLER_LISTENER_NAMES="CONTROLLER",
            KAFKA_CONTROLLER_QUORUM_VOTERS="1@localhost:9093",
            KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR="1",
            KAFKA_TRANSACTION_STATE_LOG_REPLICATION_FACTOR="1",
            KAFKA_TRANSACTION_STATE_LOG_MIN_ISR="1",
            KAFKA_GROUP_INITIAL_REBALANCE_DELAY_MS="0",
        )
        .waiting_for(LogMessageWaitStrategy("Kafka Server started").with_startup_timeout(90))
    )
    with container:
        yield f"localhost:{port}"
