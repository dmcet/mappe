"""Semantic ranking: stored listing vectors, and how each search was ranked.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_hit", sa.Column("embedding", sa.LargeBinary(), nullable=True))
    op.add_column("job_hit", sa.Column("embedding_key", sa.String(), nullable=True))
    op.add_column("search", sa.Column("ranking", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("search") as batch:
        batch.drop_column("ranking")
    with op.batch_alter_table("job_hit") as batch:
        batch.drop_column("embedding_key")
        batch.drop_column("embedding")
