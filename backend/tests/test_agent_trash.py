"""The host agent's trash must never overwrite what is already in it.

The agent is the only part of Sift with filesystem access, and it never unlinks:
approved deletes are *moved* to a `.sift-trash` folder, so a wrong approval costs
a restore rather than a re-download. That guarantee is only as good as the move.

`shutil.move` onto an existing path replaces it without a word, and two files
sharing one basename is not an exotic case here — a transcode moves the original
into the trash and writes the new encode out under the source's own name, so any
later delete of that encode targets the identical trash path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_AGENT = Path(__file__).resolve().parents[2] / "tools" / "sift-agent.py"


def _load():
    spec = importlib.util.spec_from_file_location("sift_agent", _AGENT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def agent_mod():
    return _load()


def test_a_second_file_of_the_same_name_does_not_replace_the_first(agent_mod, tmp_path):
    """The sequence that loses data: delete, restore-by-redownload, delete again."""
    agent = agent_mod.Agent("http://sift", "token")

    first = tmp_path / "S01E01.mkv"
    first.write_bytes(b"the original, which must survive")
    assert agent._delete(first)["ok"]

    second = tmp_path / "S01E01.mkv"
    second.write_bytes(b"a different file entirely")
    assert agent._delete(second)["ok"]

    trash = tmp_path / agent_mod.TRASH_DIRNAME
    kept = sorted(p.read_bytes() for p in trash.iterdir())
    assert len(kept) == 2, f"one file overwrote the other: {list(trash.iterdir())}"
    assert b"the original, which must survive" in kept


def test_the_ordinary_delete_keeps_its_own_name(agent_mod, tmp_path):
    """NEGATIVE CONTROL. Uniquifying unconditionally would rename every file that
    ever reaches the trash, making a restore a guessing game. With no collision the
    name must be untouched."""
    agent = agent_mod.Agent("http://sift", "token")
    path = tmp_path / "Film.mkv"
    path.write_bytes(b"x")
    result = agent._delete(path)
    assert result["output_path"].endswith(f"{agent_mod.TRASH_DIRNAME}/Film.mkv")


def test_a_dry_run_moves_nothing(agent_mod, tmp_path):
    """The default posture everywhere else in Sift, and it must hold here too —
    this is the process that can actually touch files."""
    agent = agent_mod.Agent("http://sift", "token", dry_run=True)
    path = tmp_path / "Film.mkv"
    path.write_bytes(b"x")
    assert agent._delete(path)["ok"]
    assert path.exists(), "dry run moved the file"
    assert not (tmp_path / agent_mod.TRASH_DIRNAME).exists()


def _encoder(agent_mod, monkeypatch, *, output_bytes: bytes = b"encoded"):
    """Stand in for HandBrake: write a plausible output and report success."""
    def fake_run(command, **kwargs):
        out = Path(command[command.index("-o") + 1])
        out.write_bytes(output_bytes)
        return None
    monkeypatch.setattr(agent_mod.subprocess, "run", fake_run)
    # The verifier compares durations; give both files the same one.
    monkeypatch.setattr(agent_mod.Agent, "duration_seconds", lambda self, p: 100.0)


def test_a_transcode_will_not_overwrite_a_different_file(agent_mod, tmp_path, monkeypatch):
    """The swap has a destination, and the destination may already be taken.

    Re-encoding `film.avi` produces `film.mkv`. A second copy of one film in one
    folder is exactly what the duplicate report surfaces, so `film.mkv` existing
    already is the normal case rather than a corner one — and moving onto it
    destroys a file nobody approved for deletion.
    """
    _encoder(agent_mod, monkeypatch)
    agent = agent_mod.Agent("http://sift", "token")

    source = tmp_path / "film.avi"
    source.write_bytes(b"the source, being re-encoded")
    bystander = tmp_path / "film.mkv"
    bystander.write_bytes(b"a different copy, never approved for anything")

    result = agent._transcode({"source_size": 100, "source_duration_ms": 100_000}, source)

    assert result["ok"] is False
    assert "already exists" in result["error"]
    assert bystander.read_bytes() == b"a different copy, never approved for anything"
    assert source.exists(), "the source must be left alone when the swap is refused"
    assert not (tmp_path / agent_mod.TRASH_DIRNAME).exists()


def test_an_ordinary_transcode_still_replaces_its_own_source(agent_mod, tmp_path, monkeypatch):
    """NEGATIVE CONTROL. Refusing whenever the destination exists would block every
    same-extension re-encode — `film.mkv` to `film.mkv` is the common case, and
    there the destination is the source itself."""
    _encoder(agent_mod, monkeypatch)
    agent = agent_mod.Agent("http://sift", "token")

    source = tmp_path / "film.mkv"
    source.write_bytes(b"the original")

    result = agent._transcode({"source_size": 100, "source_duration_ms": 100_000}, source)

    assert result["ok"] is True, result
    assert source.read_bytes() == b"encoded"
    trashed = list((tmp_path / agent_mod.TRASH_DIRNAME).iterdir())
    assert [p.read_bytes() for p in trashed] == [b"the original"]


def _verify(agent_mod, tmp_path, *, source_seconds, output_seconds, output_bytes=b"x" * 500):
    agent = agent_mod.Agent("http://sift", "token")
    source = tmp_path / "in.mkv"
    source.write_bytes(b"y" * 1000)
    output = tmp_path / "out.mkv"
    output.write_bytes(output_bytes)
    durations = {source: source_seconds, output: output_seconds}
    agent.duration_seconds = lambda p: durations[Path(p)]  # type: ignore[method-assign]
    return agent._verify({}, source, output)


def test_an_unprobeable_source_is_not_a_pass(agent_mod, tmp_path):
    """The hole in the load-bearing check.

    The duration comparison ran only when *both* files probed. If the source did
    not — an odd container, a missing probe, a transient failure — the comparison
    was skipped and the function fell through to "passed". The size floor is 5%, so
    an encode containing half the episode cleared it easily, and a truncated file
    that plays is indistinguishable from a good one to everything downstream.
    """
    verdict = _verify(agent_mod, tmp_path, source_seconds=None, output_seconds=100.0)
    assert verdict is not None, "an unverifiable encode was accepted"
    assert "probe" in verdict


def test_a_truncated_encode_is_still_caught(agent_mod, tmp_path):
    """The case the check exists for, when both files do probe."""
    verdict = _verify(agent_mod, tmp_path, source_seconds=2700.0, output_seconds=1200.0)
    assert verdict is not None and "truncated" in verdict


def test_a_good_encode_still_passes(agent_mod, tmp_path):
    """NEGATIVE CONTROL. Refusing whenever a duration is missing must not become
    refusing everything — a matching pair has to pass, or nothing ever swaps."""
    assert _verify(agent_mod, tmp_path, source_seconds=2700.0, output_seconds=2701.5) is None


def test_a_wildly_small_output_is_refused_on_size_alone(agent_mod, tmp_path):
    """Belt and braces: the size floor must still bite even when the durations
    agree, because a container can report a full duration it cannot deliver."""
    verdict = _verify(
        agent_mod, tmp_path, source_seconds=2700.0, output_seconds=2700.0, output_bytes=b"x" * 5
    )
    assert verdict is not None and "not an encode" in verdict


class _Posts:
    """Records every attempt and fails the first `fail_times` of them."""

    def __init__(self, exc, fail_times: int):
        self.exc = exc
        self.fail_times = fail_times
        self.attempts = 0

    def __call__(self, path, payload=None):
        self.attempts += 1
        if self.attempts <= self.fail_times:
            raise self.exc
        return {}


def _agent_with(agent_mod, posts):
    agent = agent_mod.Agent("http://sift", "token", sleep=lambda _s: None)
    agent._post = posts  # type: ignore[method-assign]
    return agent


def test_a_dropped_report_is_retried(agent_mod):
    """The report is the only record that the work happened.

    By the time it runs the file has already moved. Nothing on the server
    reconciles a job that is never reported — it stays `claimed` for ever, and the
    audit log shows an approved action that never executed, for work that did. So
    a single dropped connection must not be the end of it.
    """
    import urllib.error

    posts = _Posts(urllib.error.URLError("connection reset"), fail_times=2)
    _agent_with(agent_mod, posts).report(7, {"ok": True})
    assert posts.attempts == 3, "gave up before the connection recovered"


def test_a_refusal_is_not_retried(agent_mod):
    """NEGATIVE CONTROL. A bad token or an unknown job does not become true by
    asking again — retrying a 4xx just delays the log line that explains it."""
    import urllib.error

    refusal = urllib.error.HTTPError("http://sift", 401, "unauthorized", {}, None)
    posts = _Posts(refusal, fail_times=99)
    _agent_with(agent_mod, posts).report(7, {"ok": True})
    assert posts.attempts == 1


def test_a_server_error_is_retried_then_given_up_on(agent_mod):
    """A 5xx is worth retrying — and worth stopping, so a wedged server does not
    trap the agent in a loop while the rest of the queue waits."""
    import urllib.error

    boom = urllib.error.HTTPError("http://sift", 503, "unavailable", {}, None)
    posts = _Posts(boom, fail_times=99)
    _agent_with(agent_mod, posts).report(7, {"ok": True})
    assert posts.attempts == agent_mod.REPORT_ATTEMPTS


def test_a_first_time_success_does_not_retry(agent_mod):
    """NEGATIVE CONTROL: the ordinary path must still be one request."""
    posts = _Posts(RuntimeError("never raised"), fail_times=0)
    _agent_with(agent_mod, posts).report(7, {"ok": True})
    assert posts.attempts == 1
