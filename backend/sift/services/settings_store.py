"""User-overridable settings persisted in the ``settings`` table.

Effective config = the base (env/toml) values overlaid with any DB overrides. Junk
thresholds edited in the UI live here so a scan/scoring uses them. (On a free host
with an ephemeral disk these reset on restart — same caveat as the snapshot.)
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..config import JunkThresholds, Settings
from ..db.models import Setting

_JUNK_KEY = "junk_thresholds"


def get_junk_thresholds(session: Session, base: JunkThresholds) -> JunkThresholds:
    row = session.get(Setting, _JUNK_KEY)
    if not row or not row.value:
        return base
    overrides = {k: v for k, v in row.value.items() if k in JunkThresholds.model_fields}
    return JunkThresholds(**{**base.model_dump(), **overrides})


def set_junk_thresholds(session: Session, values: dict[str, Any]) -> None:
    clean = {k: v for k, v in values.items() if k in JunkThresholds.model_fields}
    row = session.get(Setting, _JUNK_KEY)
    if row is None:
        session.add(Setting(key=_JUNK_KEY, value=clean))
    else:
        row.value = {**(row.value or {}), **clean}
    session.commit()


def effective_junk(session: Session, settings: Settings) -> JunkThresholds:
    return get_junk_thresholds(session, settings.junk)


# ------------------------------------------------------------- automatic rescans

_SCHEDULE_KEY = "scan_schedule"
ALLOWED_INTERVALS = (0, 6, 12, 24)  # hours; 0 = off


def get_scan_interval(session: Session) -> int:
    row = session.get(Setting, _SCHEDULE_KEY)
    hours = (row.value or {}).get("interval_hours", 0) if row else 0
    return int(hours) if hours in ALLOWED_INTERVALS else 0


def set_scan_interval(session: Session, hours: int) -> int:
    if hours not in ALLOWED_INTERVALS:
        raise ValueError(f"interval must be one of {ALLOWED_INTERVALS}")
    session.merge(Setting(key=_SCHEDULE_KEY, value={"interval_hours": hours}))
    session.commit()
    return hours
