import enum
from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class ReviewStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    skipped = "skipped"


class AgentName(enum.StrEnum):
    review = "review"
    test = "test"


class Severity(enum.StrEnum):
    info = "info"
    warning = "warning"
    error = "error"


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    # Store the string values (not member names) and keep them as plain VARCHAR
    # so migrations do not have to manage Postgres enum types.
    return Enum(cls, name=name, native_enum=False, values_callable=lambda e: [m.value for m in e])


class Base(DeclarativeBase):
    pass


class Review(Base):
    __tablename__ = "reviews"
    # This constraint is what makes duplicate webhooks and Kafka redeliveries harmless.
    __table_args__ = (UniqueConstraint("repo_full_name", "pr_number", "head_sha"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_full_name: Mapped[str] = mapped_column(String(255), index=True)
    pr_number: Mapped[int] = mapped_column(Integer)
    head_sha: Mapped[str] = mapped_column(String(64))
    installation_id: Mapped[int] = mapped_column(Integer)
    status: Mapped[ReviewStatus] = mapped_column(
        _enum(ReviewStatus, "review_status"), default=ReviewStatus.queued, index=True
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    comments: Mapped[list["Comment"]] = relationship(
        back_populates="review", cascade="all, delete-orphan", order_by="Comment.id"
    )


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True)
    agent: Mapped[AgentName] = mapped_column(_enum(AgentName, "comment_agent"))
    file_path: Mapped[str] = mapped_column(String(1024))
    line: Mapped[int] = mapped_column(Integer)
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "comment_severity"))
    category: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    posted: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    review: Mapped[Review] = relationship(back_populates="comments")


def make_engine(url: str):
    return create_async_engine(url, pool_pre_ping=True)


def make_session_factory(engine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False so objects stay readable after commit in async code.
    return async_sessionmaker(engine, expire_on_commit=False)
