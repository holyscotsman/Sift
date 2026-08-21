"""The scan-progress fan-out, and the one property that matters most about it.

`ScanHub` sits between the ingest pipeline and every open browser tab. The
pipeline awaits `publish_progress` on the event loop it is scanning on, so
anything that can block there blocks the scan itself — and a browser tab is not a
reliable reader. A backgrounded tab is throttled, a suspended laptop reads
nothing at all, and a closed one never says so until a write fails.

The auth gate on the socket is covered in `test_auth.py` and
`test_security_hardening.py`. This is about what happens once it is open.
"""

from __future__ import annotations

import asyncio

from sift.api.ws import ScanHub
from sift.ingest.pipeline import ScanProgress


async def test_a_tab_that_stops_reading_never_stalls_the_scan():
    """The load-bearing property. Messages are dropped, not queued forever, and
    `publish` returns whatever the subscriber is doing.

    A queue that grew without bound is a memory leak that a single backgrounded
    tab creates; one that blocked when full would stop the scan dead — the
    pipeline awaits this call on the loop it is scanning on. Dropping progress
    frames is the right trade: they are a picture of a moving thing, and the next
    one supersedes the last.
    """
    hub = ScanHub()
    hub.subscribe(1)  # a subscriber that never calls `get`

    # An order of magnitude past the queue bound, so this fails loudly rather than
    # passing because the test happened to stay inside it.
    for i in range(1_000):
        await asyncio.wait_for(hub.publish(1, {"event": "progress", "n": i}), timeout=1.0)


async def test_the_bound_is_real_and_the_oldest_frames_are_the_ones_kept():
    """NEGATIVE CONTROL for the above: unbounded would also never block.

    The queue caps at 100. Anything past that is discarded on arrival rather than
    displacing what is already waiting — which is worth knowing, because it means
    a subscriber that resumes reading sees the *start* of what it missed and then
    a jump, not a smooth tail.
    """
    hub = ScanHub()
    queue = hub.subscribe(1)

    for i in range(500):
        await hub.publish(1, {"event": "progress", "n": i})

    assert queue.qsize() == 100
    assert queue.get_nowait()["n"] == 0  # the first frame, not the 400th
    assert queue.qsize() == 99


async def test_publishing_to_a_scan_nobody_is_watching_is_a_no_op():
    """The ordinary case: a scan started from the CLI, or a browser that has gone.

    The pipeline publishes unconditionally, so this path runs on every progress
    frame of every unwatched scan. A `KeyError` here would take the scan down.
    """
    hub = ScanHub()
    await hub.publish(999, {"event": "progress"})  # no subscribers at all

    hub.subscribe(1)
    await hub.publish(2, {"event": "progress"})  # a different scan


async def test_each_scan_only_hears_its_own_progress():
    """NEGATIVE CONTROL: two scans, two audiences.

    A fan-out that ignored the id would show a resumed scan's progress on a tab
    watching a different one — and the counts would be wrong, not merely noisy.
    """
    hub = ScanHub()
    one, two = hub.subscribe(1), hub.subscribe(2)

    await hub.publish(1, {"event": "progress", "which": "one"})

    assert one.get_nowait()["which"] == "one"
    assert two.qsize() == 0


async def test_every_subscriber_to_one_scan_gets_the_frame():
    """Two tabs open on the same scan is the ordinary case, not an edge one."""
    hub = ScanHub()
    a, b = hub.subscribe(1), hub.subscribe(1)

    await hub.publish(1, {"event": "progress", "n": 1})

    assert a.get_nowait()["n"] == 1
    assert b.get_nowait()["n"] == 1


async def test_unsubscribing_the_last_reader_forgets_the_scan():
    """Otherwise the hub accumulates an entry per scan for the life of the process.

    Long-lived by nature — this is a server that runs for weeks — and every scan
    that has ever been watched would leave one behind.
    """
    hub = ScanHub()
    queue = hub.subscribe(7)
    assert hub._subs.get(7)

    hub.unsubscribe(7, queue)

    assert 7 not in hub._subs


async def test_one_of_two_readers_leaving_keeps_the_other_subscribed():
    """NEGATIVE CONTROL for the cleanup: closing one tab must not silence the
    other. Dropping the whole scan on the first unsubscribe would do exactly that.
    """
    hub = ScanHub()
    a, b = hub.subscribe(1), hub.subscribe(1)

    hub.unsubscribe(1, a)
    await hub.publish(1, {"event": "progress", "n": 1})

    assert b.get_nowait()["n"] == 1


async def test_unsubscribing_something_that_was_never_subscribed_is_harmless():
    """The socket handler unsubscribes in a `finally`, which runs even when the
    connection failed before it ever subscribed.
    """
    hub = ScanHub()
    hub.unsubscribe(1, asyncio.Queue())  # never registered
    hub.unsubscribe(404, asyncio.Queue())  # no such scan


async def test_progress_is_published_as_a_progress_event_with_its_fields_flattened():
    """The browser reads `event` to tell frames apart and the rest as the payload.

    `asdict` rather than a hand-written mapping, so a field added to
    `ScanProgress` reaches the UI without a second edit — the kind of drift that
    otherwise shows up as a dial that stopped moving.
    """
    hub = ScanHub()
    queue = hub.subscribe(5)

    await hub.publish_progress(
        ScanProgress(
            scan_run_id=5,
            phase="plex",
            phase_index=2,
            total_phases=11,
            status="running",
            message="1,200 films",
            counts={"movies": 1200},
        )
    )

    frame = queue.get_nowait()
    assert frame["event"] == "progress"
    assert frame["scan_run_id"] == 5
    assert frame["phase"] == "plex"
    assert frame["message"] == "1,200 films"
    # Every field, not a chosen subset — this is what "how far through is it"
    # is drawn from, and a dropped one is a dial that stops moving.
    assert frame["phase_index"] == 2
    assert frame["total_phases"] == 11
    assert frame["status"] == "running"
    assert frame["counts"] == {"movies": 1200}
