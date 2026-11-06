"""add review summary

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reviews", sa.Column("summary", sa.Text()))


def downgrade() -> None:
    op.drop_column("reviews", "summary")
