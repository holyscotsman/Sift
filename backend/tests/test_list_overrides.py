"""The hand-corrections file, working against the list that already shipped.

``list_overrides.json`` is the only place in the two lists where a judgement call
belongs — everything else is derived from public data. The generator never writes
it, so a correction survives every rebuild.

The failure mode these pins exist for is a quiet one: a correction that only
applies to *incoming* candidates looks completely functional in a test and is
inert in practice, because almost every title on the list was stored before the
file was ever edited. Someone strikes a film out, nothing happens, and there is
nothing on screen to explain why.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from sift.db.models import CanonEntry
from sift.services import canon_entries, exclusions

_FILE = {
    "version": "test-1",
    "titles": [
        {
            "title": "Seven Samurai",
            "year": 1954,
            "imdb_id": "tt0047478",
            "tier": 1,
            "sources": ["criterion"],
        },
        {
            "title": "Loud Sequel",
            "year": 2011,
            "imdb_id": "tt0000009",
            "tier": 4,
            "sources": ["imdb_wr"],
        },
        {"title": "No Id Here", "year": 1930, "tier": 2, "sources": ["award"]},
    ],
}


@pytest.fixture
def overrides(tmp_path, monkeypatch):
    path = tmp_path / "overrides.json"
    path.write_text(
        json.dumps({"always_recommend": {"titles": []}, "never_recommend": {"titles": []}})
    )
    monkeypatch.setattr(exclusions, "_OVERRIDES", path)
    monkeypatch.setattr(canon_entries, "load_file", lambda: _FILE)
    exclusions.reload()
    yield path
    exclusions.reload()


def _write(path, always=(), never=()):
    path.write_text(
        json.dumps(
            {
                "always_recommend": {"titles": list(always)},
                "never_recommend": {"titles": list(never)},
            }
        )
    )
    exclusions.reload()


def _titles(session) -> set[str]:
    return {row.title for row in session.scalars(select(CanonEntry))}


def test_NEGATIVE_CONTROL_an_untouched_file_changes_nothing(overrides, factory):
    """NEGATIVE CONTROL: every pin below asserts that something disappeared or
    appeared. With no overrides written the canon must seed exactly as it always
    did — otherwise those pins prove only that seeding is broken."""
    with factory() as session:
        canon_entries.seed(session)
        assert _titles(session) == {"Seven Samurai", "Loud Sequel", "No Id Here"}


def test_a_struck_out_title_is_never_inserted_in_the_first_place(overrides, factory):
    """Asserted on what ``seed`` *inserted*, not on what survived it.

    The prune runs immediately afterwards and would delete the row anyway, so a
    test that only looked at the end state would pass with the seed-time filter
    deleted — and every scan would then insert the struck title and delete it
    again, for ever.
    """
    _write(overrides, never=[{"imdb_id": "tt0000009"}])
    with factory() as session:
        assert canon_entries.seed(session) == 2  # three in the file, one struck out
        assert _titles(session) == {"Seven Samurai", "No Id Here"}


def test_a_struck_out_title_stays_out_on_every_later_scan(overrides, factory):
    """Seeding runs every scan and re-reads the same file. A filter that only held
    on the first pass would re-insert the row each time — briefly resurrecting a
    film the owner struck out, on a schedule."""
    _write(overrides, never=[{"imdb_id": "tt0000009"}])
    with factory() as session:
        canon_entries.seed(session)
    with factory() as session:
        assert canon_entries.seed(session) == 0
        assert "Loud Sequel" not in _titles(session)


def test_a_bare_title_strike_is_applied_at_seed_time_too(overrides, factory):
    """The other half of the strike rule, pinned where the prune cannot cover for
    it."""
    _write(overrides, never=[{"title": "no id here", "year": 1930}])
    with factory() as session:
        assert canon_entries.seed(session) == 2
        assert _titles(session) == {"Seven Samurai", "Loud Sequel"}


def test_striking_out_a_title_removes_the_one_already_stored(overrides, factory):
    """The pin this file exists for. The correction is written *after* the canon
    has been seeded, which is the only order that ever happens in real life."""
    with factory() as session:
        canon_entries.seed(session)
        assert "Loud Sequel" in _titles(session)

    _write(overrides, never=[{"imdb_id": "tt0000009"}])
    with factory() as session:
        canon_entries.seed(session)  # the next scan
        assert _titles(session) == {"Seven Samurai", "No Id Here"}


def test_a_title_with_no_imdb_id_can_be_struck_out_by_title_and_year(overrides, factory):
    """Not every canon row carries an id, and the ones that do not are exactly the
    ones a person is most likely to want to correct by hand."""
    with factory() as session:
        canon_entries.seed(session)

    _write(overrides, never=[{"title": "no id here", "year": 1930}])
    with factory() as session:
        canon_entries.seed(session)
        assert _titles(session) == {"Seven Samurai", "Loud Sequel"}


def test_NEGATIVE_CONTROL_the_same_title_in_another_year_survives(overrides, factory):
    """NEGATIVE CONTROL: a strike is about one film, not one name. Matching on
    title alone would remove remakes and namesakes nobody mentioned."""
    with factory() as session:
        canon_entries.seed(session)

    _write(overrides, never=[{"title": "No Id Here", "year": 1998}])
    with factory() as session:
        canon_entries.seed(session)
        assert "No Id Here" in _titles(session)


def test_a_title_strike_reaches_a_row_that_happens_to_carry_an_id(overrides, factory):
    """Deliberately the opposite of how the exclusion list behaves, and the
    difference is the point.

    The exclusion list is generated, id-keyed and complete over its own domain, so
    an id decides alone there — a title match would let a different film answer
    for one the list has no opinion about. This file is neither generated nor
    complete: it is one person writing down a decision about a specific film,
    using whatever they had to hand, and most people have a title and a year
    rather than ``tt0000009``. A strike that silently did nothing because the
    stored row carried an id would be the exact failure this pass exists to
    prevent.
    """
    with factory() as session:
        canon_entries.seed(session)

    _write(overrides, never=[{"title": "Loud Sequel", "year": 2011}])
    with factory() as session:
        canon_entries.seed(session)
        assert "Loud Sequel" not in _titles(session)


def test_NEGATIVE_CONTROL_an_id_strike_does_not_take_a_namesake_with_it(overrides, factory):
    """NEGATIVE CONTROL: an id names exactly one film. Striking one out must not
    remove a different film that happens to share its title."""
    with factory() as session:
        canon_entries.seed(session)
        session.add(
            CanonEntry(
                imdb_id="tt9999999", title="Loud Sequel", year=1998, tier=2, sources=["award"]
            )
        )
        session.commit()

    _write(overrides, never=[{"imdb_id": "tt0000009"}])
    with factory() as session:
        canon_entries.seed(session)
        remaining = session.scalars(
            select(CanonEntry).where(CanonEntry.title == "Loud Sequel")
        ).all()
        assert [r.imdb_id for r in remaining] == ["tt9999999"]


def test_a_hand_added_title_joins_the_canon(overrides, factory):
    """The other direction. "Films that must be recommended even if the generated
    canon missed them" is what the file says it is for, and a file that could only
    remove things would be doing half the job it advertises."""
    _write(overrides, always=[{"title": "Overlooked Gem", "year": 1977, "imdb_id": "tt0000077"}])
    with factory() as session:
        canon_entries.seed(session)
        row = session.scalars(select(CanonEntry).where(CanonEntry.imdb_id == "tt0000077")).one()
        # Tier 1 by default: the reason to write a title in here is that the
        # generated list got it wrong, so the generated list does not outrank it.
        assert row.tier == 1 and row.title == "Overlooked Gem"


def test_hand_additions_are_idempotent_across_scans(overrides, factory):
    """Seeding runs every scan. An override that re-added itself each time would
    turn one correction into a slowly growing pile of duplicates."""
    _write(overrides, always=[{"title": "Overlooked Gem", "year": 1977, "imdb_id": "tt0000077"}])
    with factory() as session:
        canon_entries.seed(session)
    with factory() as session:
        canon_entries.seed(session)
        rows = session.scalars(select(CanonEntry).where(CanonEntry.imdb_id == "tt0000077")).all()
        assert len(rows) == 1


def test_a_title_in_both_sections_stays_out(overrides, factory):
    """Contradictory instructions resolve the safe way — the same rule the
    exclusion list uses. Of the two readings, only one can lose a film for ever,
    and it is not this one."""
    _write(
        overrides,
        always=[{"imdb_id": "tt0000009"}],
        never=[{"imdb_id": "tt0000009"}],
    )
    with factory() as session:
        # Two inserted, not three: the strike is applied while seeding rather than
        # left for the prune to clean up afterwards.
        assert canon_entries.seed(session) == 2
        assert "Loud Sequel" not in _titles(session)


def test_NEGATIVE_CONTROL_pruning_does_not_take_a_bystander_from_the_same_year(overrides, factory):
    """NEGATIVE CONTROL: the prune narrows to the struck years in SQL and then
    checks the title in Python. Drop that second check and every canon entry
    sharing a year with a struck film goes with it — silently, and only on the
    owner's own database."""
    with factory() as session:
        canon_entries.seed(session)
        session.add(
            CanonEntry(
                imdb_id="tt0001930",
                title="Innocent Bystander",
                year=1930,
                tier=2,
                sources=["award"],
            )
        )
        session.commit()

    _write(overrides, never=[{"title": "No Id Here", "year": 1930}])
    with factory() as session:
        canon_entries.prune_struck_out(session)
        assert "Innocent Bystander" in _titles(session)
        assert "No Id Here" not in _titles(session)


def test_NEGATIVE_CONTROL_two_strikes_do_not_cross_pollinate_their_years(overrides, factory):
    """NEGATIVE CONTROL: the prune narrows to the struck *years* in SQL and then
    matches the (title, year) *pair* in Python. Compare titles alone inside that
    window and a strike on "Remake" (2000) also deletes "Remake" (1990), because
    1990 is in the window on another film's account.
    """
    with factory() as session:
        canon_entries.seed(session)
        session.add_all(
            [
                CanonEntry(imdb_id="tt0001990", title="Remake", year=1990, tier=2, sources=[]),
                CanonEntry(imdb_id="tt0002000", title="Remake", year=2000, tier=2, sources=[]),
                CanonEntry(imdb_id="tt0001991", title="Other", year=1990, tier=2, sources=[]),
            ]
        )
        session.commit()

    _write(
        overrides,
        never=[{"title": "Other", "year": 1990}, {"title": "Remake", "year": 2000}],
    )
    with factory() as session:
        canon_entries.prune_struck_out(session)
        survivors = {
            (r.title, r.year)
            for r in session.scalars(select(CanonEntry).where(CanonEntry.title == "Remake"))
        }
        assert survivors == {("Remake", 1990)}


def test_NEGATIVE_CONTROL_an_empty_overrides_file_touches_the_database_at_all(overrides, factory):
    """NEGATIVE CONTROL: the common case is an empty file, and this runs on every
    scan. It has to cost nothing — not "nearly nothing", nothing."""
    from sqlalchemy import event

    with factory() as session:
        canon_entries.seed(session)

    engine = factory.kw["bind"]
    statements = {"n": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _count(*_a, **_kw):
        statements["n"] += 1

    try:
        with factory() as session:
            assert canon_entries.prune_struck_out(session) == 0
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert statements["n"] == 0, f"{statements['n']} statements for an empty overrides file"


def test_pruning_costs_a_bounded_number_of_statements(overrides, factory):
    """Bounded by the size of the overrides file, not by the canon. Pulling every
    canon row back to compare it in Python is free on SQLite and ruinous on a
    hosted database, which is the mistake this codebase keeps a changelog entry
    about."""
    from sqlalchemy import event

    with factory() as session:
        canon_entries.seed(session)

    _write(overrides, never=[{"imdb_id": "tt0000009"}])
    engine = factory.kw["bind"]
    statements = {"n": 0}

    @event.listens_for(engine, "before_cursor_execute")
    def _count(*_a, **_kw):
        statements["n"] += 1

    try:
        with factory() as session:
            canon_entries.prune_struck_out(session)
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    # One id lookup, one delete, one commit. No title pass runs at all when the
    # strike list names no bare titles.
    assert statements["n"] <= 4, f"{statements['n']} statements to prune one entry"
