"""Alternative roles suggested for a confirmed CV.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cv", sa.Column("roles_status", sa.String(), nullable=True))
    op.add_column("cv", sa.Column("roles", sa.JSON(), nullable=True))
    op.add_column("cv", sa.Column("roles_error", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("cv") as batch:
        batch.drop_column("roles_error")
        batch.drop_column("roles")
        batch.drop_column("roles_status")
