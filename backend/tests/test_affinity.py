"""Ranking the Missing list by reasons counted from the library.

The original ask was for suggestions "sorted by what is suggested the most". The
obvious reading — count the sources vouching for a title — does not survive the
data: 24,417 of the 25,000 shipped entries carry exactly one source. So the
reasons are counted from the shelf instead, and these pin that the arithmetic
does what the words on the card claim.

Nothing here consults a model. That is the standing rule and also why every
assertion below can be an equality rather than a range.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, update

from sift.analysis import affinity, canon_missing
from sift.db.models import CanonEntry, CanonMetadata, Movie
from sift.db.session import init_db, make_engine, make_session_factory
from sift.services import canon_affinity, canon_entries


def profile(genres: list[list[str]], directors: list[list[str]]) -> affinity.Profile:
    return affinity.build_profile(genres, directors)


class TestDirectorAffinity:
    def test_two_films_by_one_director_is_a_reason(self):
        p = profile([[], []], [["Akira Kurosawa"], ["Akira Kurosawa"]])
        reasons = affinity.reasons_for(p, tier=3, genres=[], directors=["Akira Kurosawa"])
        assert "You own 2 films by Akira Kurosawa" in reasons

    def test_NEGATIVE_CONTROL_one_film_is_a_coincidence(self):
        """Plenty of people own exactly one Kubrick. That is not a taste, it is a
        film, and treating it as evidence would make the list noise."""
        p = profile([[]], [["Stanley Kubrick"]])
        reasons = affinity.reasons_for(p, tier=3, genres=[], directors=["Stanley Kubrick"])
        assert not any("Kubrick" in r for r in reasons)
        assert affinity.score(p, tier=3, genres=[], directors=["Stanley Kubrick"]) == (
            affinity.TIER_POINTS[3]
        )

    def test_the_same_film_counted_twice_does_not_manufacture_a_pattern(self):
        """A duplicated row in the source must not look like two films."""
        p = profile([[]], [["Akira Kurosawa", "Akira Kurosawa"]])
        assert p.directors["Akira Kurosawa"] == 1

    def test_owning_more_raises_the_score_but_not_without_limit(self):
        two = profile([[]] * 2, [["A"]] * 2)
        thirty = profile([[]] * 30, [["A"]] * 30)
        s2 = affinity.score(two, tier=4, genres=[], directors=["A"])
        s30 = affinity.score(thirty, tier=4, genres=[], directors=["A"])
        assert s30 > s2
        # Someone who owns thirty does not need every remaining one ahead of
        # everything else on the list.
        assert s30 == affinity.DIRECTOR_POINTS * 4


class TestGenreAffinity:
    def test_a_genre_the_shelf_is_full_of_is_a_reason(self):
        p = profile([["Horror"]] * 8 + [["Drama"]] * 2, [[]] * 10)
        reasons = affinity.reasons_for(p, tier=4, genres=["Horror"], directors=[])
        assert reasons == ["Horror is 80% of your library"]

    def test_NEGATIVE_CONTROL_a_genre_everybody_owns_is_not_a_reason(self):
        """Two dramas in a library of twenty is what a library looks like, not a
        preference. Without a floor every card would carry 'Drama'."""
        p = profile([["Drama"]] * 2 + [["Horror"]] * 18, [[]] * 20)
        assert affinity.reasons_for(p, tier=4, genres=["Drama"], directors=[]) == []

    def test_imdb_and_tmdb_names_for_one_genre_are_the_same_genre(self):
        """The library's genres come from TMDB and the canon's from IMDb. They
        disagree on the name, and a comparison that misses that would silently
        never match the single most common genre in science fiction."""
        p = profile([["Science Fiction"]] * 10, [[]] * 10)
        assert affinity.reasons_for(p, tier=4, genres=["Sci-Fi"], directors=[])


class TestRankingShape:
    def test_a_beloved_director_outranks_a_canon_title_with_no_connection(self):
        """The reason tier is folded into the score rather than left as the sort
        key: otherwise this is impossible, and the list stays the same list with
        reasons written on it."""
        p = profile([[]] * 3, [["A"]] * 3)
        personal = affinity.score(p, tier=4, genres=[], directors=["A"])
        canon = affinity.score(p, tier=1, genres=[], directors=["Nobody"])
        assert personal > canon

    def test_NEGATIVE_CONTROL_an_empty_library_gets_the_ranking_it_always_had(self):
        """A new install must not be handed a worse list than before. With nothing
        on the shelf every library term is zero and the order collapses to tier."""
        p = affinity.Profile()
        assert p.is_empty
        scores = [
            affinity.score(p, tier=t, genres=["Horror"], directors=["A"])
            for t in (1, 2, 3, 4)
        ]
        assert scores == [4, 2, 1, 0]
        assert scores == sorted(scores, reverse=True)


class TestSpread:
    def _run(self, n: int) -> list[str]:
        rows = [(f"tt{i:04d}", 16, ["Akira Kurosawa"], 1000 - i) for i in range(n)]
        rows += [(f"other{i}", 4, [f"Director {i}"], 500) for i in range(n)]
        adjusted = affinity.spread(rows)
        return [k for k, _ in sorted(adjusted.items(), key=lambda kv: (-kv[1], kv[0]))]

    def test_one_director_does_not_own_the_top_of_the_list(self):
        """Measured before this existed: a shelf with five Kurosawa films on it
        put twenty-five consecutive Kurosawa films at the head of page one. Not
        wrong — every one is a film the owner plausibly wants — but a filmography
        rather than a recommendation list."""
        order = self._run(25)
        lead = 0
        for key in order:
            if key.startswith("tt"):
                lead += 1
            else:
                break
        assert lead <= 7

    def test_NEGATIVE_CONTROL_the_best_of_them_still_leads(self):
        """The toll must not flatten the signal it is moderating. Noticing that
        somebody loves a director and then burying every film they made would be
        a worse answer than never noticing."""
        order = self._run(25)
        assert order[0].startswith("tt")

    def test_the_same_library_produces_the_same_list(self):
        rows = [("a", 10, ["X"], 5), ("b", 10, ["X"], 9), ("c", 10, ["Y"], 1)]
        assert affinity.spread(rows) == affinity.spread(list(reversed(rows)))

    def test_NEGATIVE_CONTROL_a_film_with_no_director_pays_no_toll(self):
        rows = [(f"n{i}", 10, [], 1) for i in range(10)]
        assert set(affinity.spread(rows).values()) == {10}


# The arithmetic above is pure and the tests are instant. These next ones go
# through the database, because the join is where this can silently do nothing:
# an outer join that never matches produces a perfectly ordered list of NULLs.

@pytest.fixture
def seeded(tmp_path):
    """The real canon, resolved so it can be compared with a library."""
    engine = make_engine(tmp_path / "affinity.db")
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        canon_entries.seed(session)
        # Resolution normally costs API budget spread over many scans; the
        # ranking under test does not care which ids these are, only that they
        # exist, so they are filled in directly.
        session.execute(
            update(CanonEntry).values(tmdb_id=CanonEntry.id, review_status="resolved")
        )
        session.commit()
    return factory


def own(session, director: str, count: int, genres: list[str]) -> list[str]:
    """Put `count` films by `director` on the shelf. Returns their titles."""
    rows = session.execute(
        select(CanonEntry.imdb_id, CanonEntry.title, CanonEntry.id)
        .join(CanonMetadata, CanonMetadata.imdb_id == CanonEntry.imdb_id)
        .where(CanonMetadata.directors.like(f"%{director}%"))
        .limit(count)
    ).all()
    for imdb_id, title, cid in rows:
        session.add(Movie(tmdb_id=cid, imdb_id=imdb_id, title=title, in_plex=True,
                          genres=genres, library_section="Films"))
    session.commit()
    return [t for _, t, _ in rows]


def test_the_shelf_changes_the_list(seeded):
    """End to end, against the shipped canon: own five films by one director and
    the top of the list becomes films by that director, each carrying the reason."""
    with seeded() as session:
        canon_affinity.recompute(session)
        before, _ = canon_missing.missing(session, limit=10, with_total=False)

        own(session, "Akira Kurosawa", 5, ["Drama"])
        canon_affinity.recompute(session)
        after, _ = canon_missing.missing(session, limit=10, with_total=False)

    assert not any("Akira Kurosawa" in (r.directors or []) for r in before[:3])
    assert "Akira Kurosawa" in (after[0].directors or [])
    assert "You own 5 films by Akira Kurosawa" in after[0].reasons


def test_NEGATIVE_CONTROL_an_empty_library_leaves_the_order_alone(seeded):
    """Nothing on the shelf, nothing to say: the list must be the tier-and-fame
    ordering it was before any of this existed."""
    with seeded() as session:
        canon_affinity.recompute(session)
        rows, _ = canon_missing.missing(session, limit=20, with_total=False)

    assert [r.tier for r in rows] == sorted(r.tier for r in rows)
    assert all(r.reasons in ([], ["Widely regarded as essential"],
                             ["Widely held to be worth owning"], ["Well regarded"])
               for r in rows)


def test_the_card_carries_what_the_film_is(seeded):
    """Genres, runtime and a director reach the page. The join is an outer join,
    so a broken one degrades to silence rather than an error."""
    with seeded() as session:
        canon_affinity.recompute(session)
        rows, _ = canon_missing.missing(session, limit=40, with_total=False)

    assert sum(1 for r in rows if r.genres) / len(rows) > 0.9
    assert sum(1 for r in rows if r.directors) / len(rows) > 0.9
    assert sum(1 for r in rows if r.runtime) / len(rows) > 0.9


def test_NEGATIVE_CONTROL_one_director_does_not_fill_the_first_page(seeded):
    """The measured failure this spread exists for: twenty-five in a row."""
    with seeded() as session:
        own(session, "Akira Kurosawa", 5, ["Drama"])
        canon_affinity.recompute(session)
        rows, _ = canon_missing.missing(session, limit=60, with_total=False)

    lead = 0
    for row in rows:
        if "Akira Kurosawa" in (row.directors or []):
            lead += 1
        else:
            break
    assert lead <= 7
    assert len({d for r in rows for d in (r.directors or [])}) > 30
