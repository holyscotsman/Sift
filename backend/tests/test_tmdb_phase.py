"""The TMDB phase — enrichment, curated-list resolution, and canon resolution.

The whole phase was uncovered: no test in the suite ever passed a TMDB client to
the pipeline, so every scan under test ran with `tmdb=None` and returned from the
first line. That is three network-shaped loops, each with its own budget and its
own failure policy, none of them exercised.
"""

from __future__ import annotations

from sqlalchemy import select

from sift.db.models import CanonEntry, Movie
from sift.ingest.pipeline import ScanPipeline
from sift.services import canon_entries
from sift.services.scanner import create_scan_run

from .test_pipeline import FakePlex, FakeRadarr, FakeService, FakeTautulli


class FakeTmdb(FakeService):
    """Records what it was asked for, so the budgets can be counted rather than
    inferred from side effects."""

    name = "tmdb"

    def __init__(self, *, movies=None, find=None, search=None, raises=()):
        super().__init__()
        self.movies = movies or {}
        self.find = find or {}
        self.search = search or {}
        self.raises = set(raises)
        self.get_calls: list[int] = []
        self.find_calls: list[str] = []
        self.search_calls: list[tuple[str, int | None]] = []

    async def get_movie(self, tmdb_id, *, append=""):
        self.get_calls.append(tmdb_id)
        if tmdb_id in self.raises:
            raise RuntimeError("tmdb said no")
        return self.movies.get(tmdb_id, {"id": tmdb_id, "title": f"Film {tmdb_id}"})

    async def find_by_imdb(self, imdb_id):
        self.find_calls.append(imdb_id)
        if imdb_id in self.raises:
            raise RuntimeError("tmdb said no")
        return self.find.get(imdb_id)

    async def search_movie(self, title, year=None):
        self.search_calls.append((title, year))
        if title in self.raises:
            raise RuntimeError("tmdb said no")
        return self.search.get(title)


def _pipeline(factory, settings, tmdb, *, enrich=0):
    return ScanPipeline(
        factory,
        settings,
        radarr=FakeRadarr(),
        plex=FakePlex(),
        tautulli=FakeTautulli(),
        tmdb=tmdb,
        tmdb_enrich_limit=enrich,
    )


async def _scan(factory, settings, tmdb, *, enrich=0):
    pipe = _pipeline(factory, settings, tmdb, enrich=enrich)
    await pipe.run(create_scan_run(factory))
    return pipe


# ------------------------------------------------------------------ enrichment


async def test_enrichment_is_capped_by_its_budget(factory, settings):
    """One request per title, and the count is the limit — not the library size.

    Enrichment is the only per-title network loop in the scan. Uncapped it would
    make a scan cost one TMDB request for every film the owner has, every time.
    """
    tmdb = FakeTmdb()
    await _scan(factory, settings, tmdb, enrich=2)

    assert len(tmdb.get_calls) == 2


async def test_a_zero_budget_asks_tmdb_nothing(factory, settings):
    """NEGATIVE CONTROL: the default is off, and off means no requests at all.

    A limit of zero that still fetched "just the first page" would make the
    feature impossible to actually disable.

    Mutation-checked: the `if self.tmdb_enrich_limit > 0` shortcut is *not* what
    delivers this — removing it leaves the test green, because `_tmdb_targets`
    passes the limit straight to a SQL `LIMIT` and `LIMIT 0` returns nothing. The
    enforcement is the `LIMIT` clause; removing that does turn this red. The
    shortcut saves a round trip, and the test claims only the outcome.
    """
    tmdb = FakeTmdb()
    await _scan(factory, settings, tmdb, enrich=0)

    assert tmdb.get_calls == []


async def test_one_title_tmdb_refuses_does_not_end_the_phase(factory, settings):
    """Enrichment is best-effort: a failure on one title is skipped and the rest
    of the budget is still spent. A phase that aborted on the first bad id would
    leave the whole library unenriched because of one deleted TMDB entry.
    """
    tmdb = FakeTmdb(raises={603})
    await _scan(factory, settings, tmdb, enrich=3)

    assert 603 in tmdb.get_calls
    assert len(tmdb.get_calls) == 3  # the failure did not stop the loop


# ----------------------------------------------------------- canon resolution


def _seed_canon_entry(session, *, title, year=None, imdb_id=None, tier=1):
    entry = CanonEntry(
        sources=["test"],
        title=title,
        year=year,
        imdb_id=imdb_id,
        tier=tier,
        review_status="pending",
    )
    session.add(entry)
    session.commit()
    return entry.id


async def test_an_imdb_id_resolves_exactly_and_a_bare_title_is_searched(factory, settings):
    """Two different calls for two different qualities of evidence.

    An IMDb id is an identity and resolves exactly. A title and year is a guess,
    and is made through the search endpoint precisely so it reads as one.
    """
    with factory() as session:
        # A made-up title: the curated-list seed resolves real films by name in
        # the same phase, so a genuine title would appear in `search_calls` for a
        # reason that has nothing to do with the canon path being tested.
        exact = _seed_canon_entry(
            session, title="A Film With An Id", year=1953, imdb_id="tt0046438"
        )
        guess = _seed_canon_entry(session, title="Some Obscure Film", year=1962)

    tmdb = FakeTmdb(find={"tt0046438": 18148}, search={"Some Obscure Film": 555})
    await _scan(factory, settings, tmdb)

    assert "tt0046438" in tmdb.find_calls
    assert ("Some Obscure Film", 1962) in tmdb.search_calls
    # The one with an id was never sent to search.
    assert not any(t == "A Film With An Id" for t, _ in tmdb.search_calls)

    with factory() as session:
        assert session.get(CanonEntry, exact).tmdb_id == 18148
        assert session.get(CanonEntry, guess).tmdb_id == 555


async def test_a_miss_is_a_counted_attempt_not_a_verdict(factory, settings):
    """TMDB not finding a title today does not make it un-canonical.

    A miss increments the attempt counter and leaves the entry pending, so the
    next scan tries again. Marking it unresolvable on the first miss would let one
    bad night at TMDB permanently drop films out of the canon.
    """
    with factory() as session:
        entry_id = _seed_canon_entry(session, title="Nowhere Film", year=1970)

    await _scan(factory, settings, FakeTmdb())  # search returns nothing

    with factory() as session:
        entry = session.get(CanonEntry, entry_id)
        assert entry.resolve_attempts == 1
        assert entry.review_status == "pending"
        assert entry.tmdb_id is None


async def test_repeated_misses_eventually_give_up(factory, settings):
    """NEGATIVE CONTROL for the above: forgiveness is not infinite.

    Without a ceiling, an entry TMDB will never have retries on every scan
    forever — a permanent per-scan cost for a title that does not exist.
    """
    with factory() as session:
        entry_id = _seed_canon_entry(session, title="Nowhere Film", year=1970)

    for _ in range(canon_entries.MAX_RESOLVE_ATTEMPTS):
        await _scan(factory, settings, FakeTmdb())

    with factory() as session:
        entry = session.get(CanonEntry, entry_id)
        assert entry.resolve_attempts == canon_entries.MAX_RESOLVE_ATTEMPTS
        assert entry.review_status == "unresolvable"

    # And having given up, it is not asked about again.
    tmdb = FakeTmdb()
    await _scan(factory, settings, tmdb)
    assert not any(t == "Nowhere Film" for t, _ in tmdb.search_calls)


async def test_a_failed_lookup_is_not_recorded_as_a_miss(factory, settings):
    """An exception is TMDB being unreachable; a `None` is TMDB answering "no such
    film". Only the second is evidence about the title.

    Counting a network error as a miss would burn the attempt ceiling during an
    outage and mark real canon unresolvable for reasons that have nothing to do
    with the film.
    """
    with factory() as session:
        entry_id = _seed_canon_entry(session, title="Unreachable Film", year=1970)

    await _scan(factory, settings, FakeTmdb(raises={"Unreachable Film"}))

    with factory() as session:
        entry = session.get(CanonEntry, entry_id)
        assert entry.resolve_attempts == 0
        assert entry.review_status == "pending"


async def test_the_phase_does_nothing_at_all_without_a_tmdb_client(factory, settings):
    """NEGATIVE CONTROL: TMDB is optional. A scan on a setup with no TMDB key
    completes, and resolves nothing.

    Mutation-checked, and the result is worth writing down: removing *all three*
    `if self.tmdb is None: return {}` guards leaves this green. Every TMDB call in
    the phase sits inside a best-effort `except Exception`, which swallows the
    `AttributeError` on `None` just as readily as a network failure. The guards
    are what stop the phase doing pointless database work and logging an error per
    pending entry — they are not what keeps the scan alive. This pins the
    behaviour that matters and does not pretend to protect a line that is not
    load-bearing.
    """
    with factory() as session:
        entry_id = _seed_canon_entry(
            session, title="A Film With An Id", year=1953, imdb_id="tt0046438"
        )

    pipe = ScanPipeline(
        factory,
        settings,
        radarr=FakeRadarr(),
        plex=FakePlex(),
        tautulli=FakeTautulli(),
        tmdb=None,
        tmdb_enrich_limit=50,
    )
    run = await pipe.run(create_scan_run(factory))

    assert run.status.value == "completed"
    with factory() as session:
        assert session.get(CanonEntry, entry_id).tmdb_id is None
        assert session.scalar(select(Movie.tmdb_id).where(Movie.tmdb_id == 603)) == 603
