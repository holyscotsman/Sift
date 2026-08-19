"""What a whole scan costs the database, as the library grows.

The per-phase pins elsewhere guard the phases that were once wrong. This guards
the shape of the whole thing: reads and updates must not grow with the library.
The failure it exists to catch already happened once — a `session.merge()` per
film, four statements each, which looked instant on the file-backed SQLite these
tests use and made a scan against the hosted database look hung.

Counted, never timed, for exactly that reason.

**A trap worth knowing before you read a statement count here.** On SQLite,
SQLAlchemy batches ORM inserts into one statement only when the primary key is
supplied by us; a table with an autoincrement id gets one INSERT per row, because
the ids have to come back. So `movies` and `plex_copies` (keyed on tmdb id and
rating key) insert in one statement while `ratings` and `seasons` (autoincrement)
insert one at a time — and on Postgres, where this actually runs, both batch.

A raw total therefore reads as "one statement per film" against a scan that is
doing nothing of the kind, and the obvious "fix" would be a rewrite that buys
nothing on the database it ships to. This is the third time the artifact has come
up; it is written down here so it does not have to be rediscovered a fourth.

What is counted below is what a per-row round trip would actually show up as, in
either dialect: a SELECT or an UPDATE per film.
"""

from __future__ import annotations

from sqlalchemy import event

from sift.db.session import init_db, make_engine, make_session_factory
from sift.ingest.pipeline import ScanPipeline
from sift.services.scanner import create_scan_run

from .test_pipeline import FakeService

SECTIONS = [{"key": "1", "type": "movie", "title": "Movies"}]


def _films(count: int) -> tuple[list[dict], list[dict]]:
    """`count` films, known to both Radarr and Plex — the ordinary case."""
    radarr = [
        {
            "id": n + 1,
            "tmdbId": 10_000 + n,
            "title": f"Film {n}",
            "year": 1990 + (n % 30),
            "monitored": True,
            "hasFile": True,
            "genres": ["Drama"],
            "ratings": {"tmdb": {"value": 7.0, "votes": 5_000 + n}},
        }
        for n in range(count)
    ]
    plex = [
        {
            "ratingKey": 20_000 + n,
            "title": f"Film {n}",
            "year": 1990 + (n % 30),
            "Guid": [{"id": f"tmdb://{10_000 + n}"}],
        }
        for n in range(count)
    ]
    return radarr, plex


class ScaledRadarr(FakeService):
    name = "radarr"

    def __init__(self, movies: list[dict]) -> None:
        super().__init__()
        self.movies = movies

    async def get_movies(self) -> list[dict]:
        return self.movies

    async def get_collections(self) -> list[dict]:
        return []


class ScaledPlex(FakeService):
    name = "plex"

    # Small pages on purpose: a scan that only ever sees one batch would not
    # exercise the streamed write path, and it is the per-batch work that grows.
    page_size = 25
    last_section_total = 0

    def __init__(self, items: list[dict]) -> None:
        super().__init__()
        self.items = items

    async def get_sections(self) -> list[dict]:
        return SECTIONS

    def _for(self, item_type: int) -> list[dict]:
        return self.items if item_type == 1 else []

    async def iter_section_items(self, key, *, item_type=1):  # noqa: ANN001, ANN201
        items = self._for(item_type)
        self.last_section_total = len(items)
        for start in range(0, len(items), self.page_size):
            yield items[start : start + self.page_size]

    async def get_section_items(self, key, *, item_type=1):  # noqa: ANN001, ANN201
        return self._for(item_type)


async def _scan_statements(factory, settings, count: int) -> list[str]:
    radarr_movies, plex_items = _films(count)
    pipe = ScanPipeline(
        factory,
        settings,
        radarr=ScaledRadarr(radarr_movies),
        plex=ScaledPlex(plex_items),
        tautulli=None,
        tmdb=None,
    )
    scan_id = create_scan_run(factory)

    engine = factory.kw["bind"]
    seen: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _record(_c, _cur, statement, *_a, **_k):
        seen.append(statement)

    try:
        run = await pipe.run(scan_id)
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    assert str(run.status) in ("ScanStatus.COMPLETED", "completed"), run.status
    return [" ".join(statement.split()) for statement in seen]


def _fresh(tmp_path, name: str):
    engine = make_engine(tmp_path / f"{name}.db")
    init_db(engine)
    return make_session_factory(engine)


async def test_reads_and_updates_do_not_grow_with_the_library(factory, settings, tmp_path):
    """The regression that already happened once, in a shape that would catch it.

    A `session.merge()` per film cost four statements each; removing it is
    recorded as 4.0 statements per film down to 0.01. Both halves of that shape —
    the read that checks whether the row exists, and the update that follows — are
    counted here, and both mean the same thing on either dialect.

    Measured as a *slope* rather than a budget: reads legitimately grow a little
    with the number of Plex batches, so a flat threshold either has to be so loose
    it proves nothing or so tight it breaks when the page size changes. Scanning
    two libraries of different sizes and comparing is the honest form of the
    question.
    """
    for name in ("tautulli", "tmdb"):
        getattr(settings, name).enabled = False

    small, large = 40, 160
    small_statements = await _scan_statements(_fresh(tmp_path, "small"), settings, small)
    large_statements = await _scan_statements(_fresh(tmp_path, "large"), settings, large)

    def kind(statements: list[str], word: str) -> int:
        return len([s for s in statements if s.upper().lstrip().startswith(word)])

    extra_films = large - small
    extra_reads = kind(large_statements, "SELECT") - kind(small_statements, "SELECT")
    extra_updates = kind(large_statements, "UPDATE") - kind(small_statements, "UPDATE")

    assert extra_reads < extra_films / 2, (
        f"{extra_reads} more reads for {extra_films} more films — that is the "
        "slope of a per-row round trip"
    )
    assert extra_updates < extra_films / 2, (
        f"{extra_updates} more updates for {extra_films} more films"
    )


async def test_the_films_are_written_in_batches_not_one_at_a_time(factory, settings):
    """`movies` is keyed on the tmdb id we already hold, which is what lets the
    whole library land in one insert — on either dialect. Losing that (a merge, a
    per-row add-and-flush) is the regression this file exists for, and unlike a
    raw statement count it means the same thing on SQLite and Postgres.
    """
    for name in ("tautulli", "tmdb"):
        getattr(settings, name).enabled = False

    statements = await _scan_statements(factory, settings, 120)
    movie_inserts = [s for s in statements if s.upper().lstrip().startswith("INSERT INTO MOVIES")]

    assert movie_inserts, "no films were inserted at all"
    assert len(movie_inserts) <= 2, f"{len(movie_inserts)} inserts for 120 films"


async def test_the_scan_really_wrote_the_library(factory, settings):
    """NEGATIVE CONTROL: a scan that did nothing is extremely cheap.

    Every assertion about cost is satisfied perfectly by a pipeline that skips its
    work, so the cheap scan has to be shown to have produced the library.
    """
    from sqlalchemy import func, select

    from sift.db.models import Movie

    for name in ("tautulli", "tmdb"):
        getattr(settings, name).enabled = False

    await _scan_statements(factory, settings, 120)

    with factory() as session:
        total = session.scalar(select(func.count()).select_from(Movie)) or 0
        in_plex = (
            session.scalar(
                select(func.count()).select_from(Movie).where(Movie.in_plex.is_(True))
            )
            or 0
        )
    assert total == 120 and in_plex == 120
