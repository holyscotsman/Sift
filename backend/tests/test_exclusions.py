"""The exclusion list, and the hand corrections that outrank it.

The rule the owner set is narrow and worth restating, because every test here is
a consequence of it: **anything with a theatrical release must be considered,
however bad it was.** Direct-to-video and made-for-TV releases must not be.

That makes the exclusion list a claim about *distribution*, not about quality,
and the way to get it wrong is to let a judgement leak in — either by excluding a
film for being bad, or by matching so loosely that a good film is caught by a bad
one's name.
"""

from __future__ import annotations

import json

import pytest

from sift.services import exclusions


@pytest.fixture
def lists(tmp_path, monkeypatch):
    """Small stand-in files, so the pins describe rules rather than 24,000 rows."""
    exclude = tmp_path / "exclude.json"
    exclude.write_text(
        json.dumps(
            {
                "titles": [
                    {
                        "imdb_id": "tt0120131",
                        "title": "The Lion King II: Simba's Pride",
                        "year": 1998,
                        "kind": "video",
                    },
                    {
                        "imdb_id": "tt0475293",
                        "title": "High School Musical",
                        "year": 2006,
                        "kind": "tvMovie",
                    },
                ]
            }
        )
    )
    overrides = tmp_path / "overrides.json"
    overrides.write_text(
        json.dumps({"always_recommend": {"titles": []}, "never_recommend": {"titles": []}})
    )
    monkeypatch.setattr(exclusions, "_EXCLUDE", exclude)
    monkeypatch.setattr(exclusions, "_OVERRIDES", overrides)
    exclusions.reload()
    yield exclude, overrides
    exclusions.reload()


def _write(path, payload):
    path.write_text(json.dumps(payload))
    exclusions.reload()


def test_a_direct_to_video_sequel_is_excluded_by_id(lists):
    assert exclusions.excluded(imdb_id="tt0120131") is True


def test_the_same_film_is_excluded_by_title_and_year_when_no_id_arrives(lists):
    """TMDB discovery and every AI provider hand back a title and a year, never an
    IMDb id. Without this fallback the list only ever filters the one source that
    does not need filtering."""
    assert exclusions.excluded(title="the lion king ii: simba's pride", year=1998) is True
    # Punctuation and case are not the film.
    assert exclusions.excluded(title="The Lion King II  Simbas Pride", year=1998) is True


def test_NEGATIVE_CONTROL_a_theatrical_flop_is_not_excluded(lists):
    """The rule is about distribution, not quality. A film that opened in cinemas
    and was hated stays a candidate — that is the owner's rule stated verbatim,
    and an exclusion list that quietly filtered bad films would be a different
    feature wearing this one's name."""
    assert exclusions.excluded(imdb_id="tt0499549", title="Battlefield Earth", year=2000) is False


def test_NEGATIVE_CONTROL_an_id_that_resolved_and_said_nothing_ends_the_matter(lists):
    """A film carrying an IMDb id absent from the list is not excluded, even if
    some *other* film shares its title and year. Falling through to a title match
    here lets one film answer for another, and being wrong removes a title from
    every surface at once with nothing on screen to say why."""
    assert (
        exclusions.excluded(imdb_id="tt9999999", title="The Lion King II: Simba's Pride", year=1998)
        is False
    )


def test_NEGATIVE_CONTROL_the_same_title_in_a_different_year_is_a_different_film(lists):
    assert exclusions.excluded(title="High School Musical", year=1998) is False


def test_an_always_recommend_override_beats_the_generated_list(lists):
    """The escape hatch. The generated list is evidence, and evidence is sometimes
    wrong about a specific film — that is what this file is for, and the generator
    never writes it, so the correction survives every rebuild."""
    exclude, overrides = lists
    _write(
        overrides,
        {
            "always_recommend": {"titles": [{"imdb_id": "tt0120131"}]},
            "never_recommend": {"titles": []},
        },
    )
    assert exclusions.excluded(imdb_id="tt0120131") is False


def test_a_never_recommend_override_beats_everything(lists):
    exclude, overrides = lists
    _write(
        overrides,
        {
            "always_recommend": {"titles": [{"title": "Battlefield Earth", "year": 2000}]},
            "never_recommend": {"titles": [{"title": "Battlefield Earth", "year": 2000}]},
        },
    )
    # Named in both: the "never" wins. A hand-written refusal is deliberate, and
    # of the two readings it is the one that cannot lose a film for ever.
    assert exclusions.excluded(title="Battlefield Earth", year=2000) is True


def test_the_shipped_lists_load_and_are_the_size_they_were_measured_at():
    """The real files, not the fixtures. These numbers are facts about the data
    rather than details to update quietly: if they move, either the generator was
    re-run or something was hand-edited, and both deserve to be noticed."""
    exclusions.reload()
    counts = exclusions.counts()
    assert counts["excluded"] == 23_937
    # The real list is loaded and answering, not an empty dict standing in for it.
    assert exclusions.excluded(imdb_id="tt0120131") is True
