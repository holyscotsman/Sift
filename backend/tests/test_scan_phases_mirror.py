"""The frontend checklist must mirror the backend pipeline.

It silently did not: `sonarr` was missing from `SCAN_PHASES`, so that phase never
appeared in the panel while it ran, and the polling fallback divided by 8 where
the server counts 9 — its percentage disagreed with the websocket's throughout and
could never reach 100.

Checked from here rather than from a frontend test because the frontend has no
test runner, and adding one to pin a nine-line list would be a dependency bought
for a single assertion. This file is plain text; reading it is enough.
"""

from __future__ import annotations

import re
from pathlib import Path

from sift.ingest.pipeline import PHASES

_SCAN_TSX = Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib" / "scan.tsx"


def _frontend_phase_keys() -> list[str]:
    source = _SCAN_TSX.read_text()
    block = re.search(r"SCAN_PHASES[^=]*=\s*\[(.*?)\];", source, re.S)
    assert block, "could not find SCAN_PHASES in scan.tsx — has it been renamed?"
    return re.findall(r'key:\s*"([^"]+)"', block.group(1))


def test_the_scan_checklist_mirrors_the_pipeline():
    assert _frontend_phase_keys() == list(PHASES)


def test_the_mirror_check_can_actually_fail():
    """NEGATIVE CONTROL. A regex that matched nothing would make the test above
    pass by comparing two empty lists, or fail for the wrong reason. Prove the
    parser really reads the file."""
    keys = _frontend_phase_keys()
    assert len(keys) >= 8
    assert "plex" in keys
