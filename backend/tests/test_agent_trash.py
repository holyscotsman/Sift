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
