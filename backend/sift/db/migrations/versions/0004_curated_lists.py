"""add curated_list_entries

Cult-classics / IMDb-top titles for the smarter-junk 'keep if cult' rule and the
Missing screen. Idempotent create so it applies over the create_all baseline.

Revision ID: 0004_curated_lists
Revises: 0003_movie_classifier_facts
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_curated_lists"
down_revision: str | None = "0003_movie_classifier_facts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "curated_list_entries"


def upgrade() -> None:
    bind = op.get_bind()
    if _TABLE in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("list_name", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("tmdb_id", sa.Integer(), nullable=True),
        sa.Column("review_status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.UniqueConstraint("list_name", "title", "year", name="uq_curated_entry"),
    )
    op.create_index("ix_curated_list_entries_list_name", _TABLE, ["list_name"])
    op.create_index("ix_curated_list_entries_tmdb_id", _TABLE, ["tmdb_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if _TABLE in sa.inspect(bind).get_table_names():
        op.drop_table(_TABLE)
