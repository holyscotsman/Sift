"""Factory reset — wipe the snapshot + config back to first-run.

Clears every row (library snapshot, actions, scan history, and the settings table:
connections, thresholds, and the login account) so the app returns to the setup
wizard. The on-disk thumbnail cache is preserved when ``keep_thumbnails`` is set, so
the next scan re-renders instantly instead of re-fetching every poster.
"""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from ..db.models import Base


def wipe_data(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        # Reverse topological order = children before parents, so FK constraints hold.
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
