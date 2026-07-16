"""Audit trail for catalog actions.

For Phase 0 the audit surface is the ``actions`` table (immutable status history)
plus a structured log line per event. A dedicated tamper-evident, append-only log
(hash-chained) is Role 8.3 in the game plan and layers on top of this without
changing the call sites.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..db.models import Action

log = logging.getLogger("sift.audit")


class AuditTrail:
    def record(self, action: Action, event: str) -> None:
        log.info(
            "action.%s id=%s type=%s status=%s movie=%s dry_run=%s actor=%s",
            event,
            action.id,
            action.type,
            action.status,
            action.movie_tmdb_id,
            action.dry_run,
            action.actor,
        )
