"""create reviews and comments

Revision ID: 0001
Revises:
Create Date: 2026-11-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("repo_full_name", sa.String(255), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("head_sha", sa.String(64), nullable=False),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued", "running", "done", "failed", "skipped",
                name="review_status", native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text()),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Numeric(10, 6), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("repo_full_name", "pr_number", "head_sha"),
    )
    op.create_index("ix_reviews_repo_full_name", "reviews", ["repo_full_name"])
    op.create_index("ix_reviews_status", "reviews", ["status"])

    op.create_table(
        "comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "review_id",
            sa.Integer(),
            sa.ForeignKey("reviews.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "agent",
            sa.Enum("review", "test", name="comment_agent", native_enum=False),
            nullable=False,
        ),
        sa.Column("file_path", sa.String(1024), nullable=False),
        sa.Column("line", sa.Integer(), nullable=False),
        sa.Column(
            "severity",
            sa.Enum("info", "warning", "error", name="comment_severity", native_enum=False),
            nullable=False,
        ),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("posted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_comments_review_id", "comments", ["review_id"])


def downgrade() -> None:
    op.drop_table("comments")
    op.drop_table("reviews")
