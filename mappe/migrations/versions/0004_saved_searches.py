"""Saved searches, and which saved search a search ran for.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "saved_search",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cv_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("titles", sa.JSON(), nullable=True),
        sa.Column("requirements", sa.JSON(), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["cv_id"], ["cv.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_saved_search_cv_id", "saved_search", ["cv_id"])
    op.add_column("search", sa.Column("saved_id", sa.Integer(), nullable=True))
    op.create_index("ix_search_saved_id", "search", ["saved_id"])


def downgrade() -> None:
    op.drop_index("ix_search_saved_id", "search")
    with op.batch_alter_table("search") as batch:
        batch.drop_column("saved_id")
    op.drop_table("saved_search")
