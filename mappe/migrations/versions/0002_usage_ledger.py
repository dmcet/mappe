"""Usage ledger: one row per Claude call (model, step, tokens, cost).

Existing per-run and per-CV totals are carried over as one "legacy" row each, so the
overall spend stays correct.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        # Plain IDs, no foreign keys: cost history survives deleting a run or CV.
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("cv_id", sa.Integer(), nullable=True),
        sa.Column("step", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_run_id", "usage", ["run_id"])
    op.create_index("ix_usage_created_at", "usage", ["created_at"])
    op.execute(
        """
        INSERT INTO usage (created_at, run_id, cv_id, step, model, input_tokens,
                           output_tokens, cache_read_tokens, cache_write_tokens, cost_usd)
        SELECT updated_at, id, NULL, 'legacy', 'unknown', 0, 0, 0, 0, cost_usd
        FROM run WHERE cost_usd > 0
        """
    )
    op.execute(
        """
        INSERT INTO usage (created_at, run_id, cv_id, step, model, input_tokens,
                           output_tokens, cache_read_tokens, cache_write_tokens, cost_usd)
        SELECT updated_at, NULL, id, 'legacy', 'unknown', 0, 0, 0, 0, cost_usd
        FROM cv WHERE cost_usd > 0
        """
    )


def downgrade() -> None:
    op.drop_table("usage")
