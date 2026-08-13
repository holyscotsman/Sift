"""Ties in "what resolution is this season" must not depend on the hash seed.

`max(set(values), key=values.count)` reads as "the most common one" and is that,
except on a tie: it then returns whichever tied value `set` iteration reaches
first, and for strings that order is derived from Python's per-process hash seed.
A season split evenly between 1080p and 480p therefore resolved to either one,
differing between runs of identical code over an identical library.

It decides whether an irreversible quality downgrade is proposed and how large its
saving looks, so "usually right" is not a standard it can be held to.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

from sift.analysis import tv_size

_TIE = ["1080p", "480p", "1080p", "480p"]


def test_a_tie_resolves_to_the_lower_rung():
    """Conservative on purpose. Reading an evenly split season as 1080p proposes a
    downgrade from a height half of it is not at, and overstates the saving."""
    assert tv_size.dominant(_TIE, rank=tv_size.resolution_rank) == "480p"


def test_a_clear_majority_still_wins():
    """NEGATIVE CONTROL: the tie-break must not become the rule. A tie-break
    applied unconditionally would return 480p here too, and the function would
    have stopped answering the question it is named after."""
    assert tv_size.dominant(["1080p", "1080p", "480p"], rank=tv_size.resolution_rank) == "1080p"
    assert tv_size.dominant(["480p", "1080p", "480p"], rank=tv_size.resolution_rank) == "480p"


def test_no_values_at_all_is_not_an_answer():
    assert tv_size.dominant([]) is None
    assert tv_size.dominant([None, None]) is None


def test_the_answer_does_not_move_with_the_hash_seed():
    """The reproduction. Python randomises string hashing per process, so this has
    to cross a process boundary to be seen at all — inside one interpreter the
    wrong implementation looks perfectly stable.
    """
    script = textwrap.dedent(
        """
        import sys
        sys.path.insert(0, "backend")
        from sift.analysis import tv_size
        print(tv_size.dominant(["1080p", "480p", "1080p", "480p"],
                               rank=tv_size.resolution_rank))
        """
    )
    answers = set()
    for seed in range(8):
        out = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, check=True,
            env={"PYTHONHASHSEED": str(seed), "PATH": "/usr/bin:/bin"},
        )
        answers.add(out.stdout.strip())
    assert answers == {"480p"}, f"answer varied with the hash seed: {answers}"


def test_the_old_formulation_really_was_unstable():
    """NEGATIVE CONTROL for the test above — proof the harness can see the bug.

    Without this, a determinism test that passes proves nothing: it might pass
    because the implementation is fixed, or because eight seeds happened to agree,
    or because the subprocess never varied the seed at all. Running the *original*
    expression the same way must produce more than one answer.
    """
    script = textwrap.dedent(
        """
        values = ["1080p", "480p", "1080p", "480p"]
        print(max(set(values), key=values.count))
        """
    )
    answers = set()
    for seed in range(8):
        out = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, check=True,
            env={"PYTHONHASHSEED": str(seed), "PATH": "/usr/bin:/bin"},
        )
        answers.add(out.stdout.strip())
    assert len(answers) > 1, "the harness cannot observe hash-order variation at all"
