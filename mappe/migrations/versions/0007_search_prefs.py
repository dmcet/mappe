"""The job search form per CV.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cv", sa.Column("search_prefs", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("cv") as batch:
        batch.drop_column("search_prefs")
