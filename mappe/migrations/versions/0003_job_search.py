"""Job search: searches, the listings they found, and per-search scores.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cv_id", sa.Integer(), nullable=False),
        sa.Column("titles", sa.JSON(), nullable=True),
        sa.Column("places", sa.JSON(), nullable=True),
        sa.Column("remote_only", sa.Boolean(), nullable=False),
        sa.Column("requirements", sa.JSON(), nullable=True),
        sa.Column("sources", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["cv_id"], ["cv.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_search_cv_id", "search", ["cv_id"])
    op.create_index("ix_search_created_at", "search", ["created_at"])
    op.create_table(
        "job_hit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("external_id", sa.String(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_id"),
    )
    op.create_table(
        "search_result",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("search_id", sa.Integer(), nullable=False),
        sa.Column("hit_id", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=True),
        sa.Column("hidden", sa.String(), nullable=True),
        sa.Column("is_new", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["search_id"], ["search.id"]),
        sa.ForeignKeyConstraint(["hit_id"], ["job_hit.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_search_result_search_id", "search_result", ["search_id"])
    op.create_index("ix_search_result_hit_id", "search_result", ["hit_id"])


def downgrade() -> None:
    op.drop_table("search_result")
    op.drop_table("job_hit")
    op.drop_table("search")
