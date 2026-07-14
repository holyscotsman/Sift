"""add classifier fact columns to movies

original_language, budget, is_adult, us_theatrical, is_independent — the facts the
smarter-junk classifier reads. Idempotent (guards each add) so it applies cleanly
over the create_all baseline.

Revision ID: 0003_movie_classifier_facts
Revises: 0002_movie_cutoff_unmet
Create Date: 2026-07-14
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "0003_movie_classifier_facts"
down_revision: str | None = "0002_movie_cutoff_unmet"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BOOL_COLS = ("is_adult", "us_theatrical", "is_independent")
_OTHER_COLS: dict[str, Any] = {
    "original_language": sa.String(length=8),
    "budget": sa.BigInteger(),
}


def _cols(bind: sa.engine.Connection) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns("movies")}


def upgrade() -> None:
    bind = op.get_bind()
    have = _cols(bind)
    for name, type_ in _OTHER_COLS.items():
        if name not in have:
            op.add_column("movies", sa.Column(name, type_, nullable=True))
    for name in _BOOL_COLS:
        if name not in have:
            op.add_column(
                "movies", sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false())
            )
            op.create_index(f"ix_movies_{name}", "movies", [name])


def downgrade() -> None:
    bind = op.get_bind()
    have = _cols(bind)
    for name in _BOOL_COLS:
        if name in have:
            op.drop_index(f"ix_movies_{name}", table_name="movies")
            op.drop_column("movies", name)
    for name in _OTHER_COLS:
        if name in have:
            op.drop_column("movies", name)
