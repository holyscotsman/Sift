"""No `async` route handler may talk to the database on the event loop.

FastAPI runs a plain `def` handler in a threadpool, so a session call inside one
costs that request and nothing else. Inside an `async def` handler the same call
runs *on the loop*, and while it is in flight nothing else in the process moves —
every other request, every poll, the scan socket.

On the file-backed SQLite these tests use, a session call is microseconds and the
difference is invisible. Against a hosted database it is a network round trip.
That is not theory: thirty concurrent poster fetches took 1.57 s of the server
being unavailable before `PosterCache` was moved off the loop.

This is a structural pin rather than a timing one — it catches the whole class,
including the next handler somebody writes, and it does not depend on the machine.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROUTES = Path(__file__).resolve().parents[1] / "sift" / "api"

# Handlers that still do it, each one request at a time rather than thirty at
# once — so none is urgent, and none is forgotten either. Removing a name from
# this list without fixing the handler fails, and so does fixing one without
# removing its name: the list has to describe reality to be worth having.
KNOWN_BLOCKING = {
    ("routes_analysis.py", "canon_refresh"),
    ("routes_ask.py", "ask"),
    ("routes_config.py", "save_config"),
    ("routes_config.py", "save_actions"),
    ("routes_config.py", "set_sections"),
    ("routes_musthave.py", "request_canon_batch"),
    ("routes_scan.py", "start_scan"),
    ("routes_system.py", "version_status"),
    ("routes_system.py", "update"),
}

_SESSION_CALLS = ("factory()", "session_factory()")


def _opens_a_session(node: ast.AsyncFunctionDef) -> bool:
    """A `with <something>_factory() as session:` anywhere inside the handler."""
    for item in ast.walk(node):
        if isinstance(item, ast.With | ast.AsyncWith):
            source = ast.unparse(item.items[0].context_expr)
            if any(call in source for call in _SESSION_CALLS):
                return True
    return False


def blocking_handlers(source: str, filename: str) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.AsyncFunctionDef) and _opens_a_session(node):
            found.add((filename, node.name))
    return found


def test_no_new_async_handler_blocks_the_loop() -> None:
    found: set[tuple[str, str]] = set()
    for path in sorted(ROUTES.glob("routes_*.py")):
        found |= blocking_handlers(path.read_text(), path.name)

    new = found - KNOWN_BLOCKING
    assert not new, (
        "these async handlers open a database session on the event loop, which "
        f"stalls every other request while it runs: {sorted(new)}. Use "
        "`db.session.in_thread`, or make the handler a plain `def`."
    )

    fixed = KNOWN_BLOCKING - found
    assert not fixed, (
        f"these are no longer blocking — take them off KNOWN_BLOCKING: {sorted(fixed)}"
    )


def test_the_detector_actually_detects() -> None:
    """NEGATIVE CONTROL: a scanner that finds nothing passes the pin above perfectly.

    Feed it exactly the shape it exists to catch, and one it must leave alone.
    """
    offender = '''
async def handler(factory):
    with factory() as session:
        return session.get(1)
'''
    assert blocking_handlers(offender, "x.py") == {("x.py", "handler")}

    # A plain `def` is fine: FastAPI runs it in a threadpool.
    fine = '''
def handler(factory):
    with factory() as session:
        return session.get(1)
'''
    assert blocking_handlers(fine, "x.py") == set()

    # And an async handler that stays off the loop is the point of the exercise.
    fixed = '''
async def handler(factory):
    return await in_thread(factory, lambda session: session.get(1))
'''
    assert blocking_handlers(fixed, "x.py") == set()
