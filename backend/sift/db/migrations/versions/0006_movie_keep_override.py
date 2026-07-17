"""add movies.keep_override

The owner's standing "never flag this again" verdict, set from the Junk screen.
Idempotent add so it applies over the create_all baseline.

Revision ID: 0006_movie_keep_override
Revises: 0005_musthave_suggestions
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_movie_keep_override"
down_revision: str | None = "0005_musthave_suggestions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_column(bind: sa.engine.Connection) -> bool:
    return any(c["name"] == "keep_override" for c in sa.inspect(bind).get_columns("movies"))


def upgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind):
        return
    op.add_column(
        "movies",
        sa.Column("keep_override", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_movies_keep_override", "movies", ["keep_override"])


def downgrade() -> None:
    bind = op.get_bind()
    if _has_column(bind):
        op.drop_index("ix_movies_keep_override", table_name="movies")
        op.drop_column("movies", "keep_override")
