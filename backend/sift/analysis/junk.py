"""Compute and persist deterministic junk scores, and fetch removal candidates.

Only library items (``in_plex``) are scored — Radarr-only "wanted" entries aren't
things you have, so they can't be junk. Kids-section items are scored but carry a
guard and are excluded from removal candidates (never auto-flagged on rating).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from ..config import JunkThresholds
from ..db.models import CanonMovie, CuratedListEntry, Movie, Rating, Score, WatchHistory
from ..services import canon_entries
from . import recognition, scoring
from .classify import MovieFacts, Verdict, classify

# Films per database round trip. 500 matches the chunk size used by the ingest
# writers, and is comfortably inside the parameter limit of every dialect in play.
_CHUNK = 500


def _facts(movie: Movie, cult_ids: frozenset[int]) -> MovieFacts:
    lang = movie.original_language
    return MovieFacts(
        us_theatrical=bool(movie.us_theatrical),
        is_adult=bool(movie.is_adult),
        is_independent=bool(movie.is_independent),
        # International = a known non-English original language.
        is_international=bool(lang) and lang != "en",
        is_cult=movie.tmdb_id in cult_ids,
    )


def _best_ratings(
    session: Session, movie_ids: list[int]
) -> dict[int, tuple[float | None, int | None]]:
    """The most-voted rating per film — most statistically reliable — for a whole
    batch of films in one query.

    Ordered by id and resolved with a strict ``>`` so the first of several equally
    voted ratings wins, which is the one the per-film ``max()`` returned. Without
    the explicit order the winner of a tie would depend on whatever order the
    database happened to hand rows back in, and this function decides what gets
    proposed for deletion.
    """
    best: dict[int, tuple[float | None, int | None]] = {}
    votes_seen: dict[int, int] = {}
    for start in range(0, len(movie_ids), _CHUNK):
        batch = movie_ids[start : start + _CHUNK]
        for row in session.scalars(
            select(Rating).where(Rating.movie_id.in_(batch)).order_by(Rating.id)
        ):
            votes = row.votes or 0
            if row.movie_id not in best or votes > votes_seen[row.movie_id]:
                best[row.movie_id] = (row.value, row.votes)
                votes_seen[row.movie_id] = votes
    return best


def _canon_ids(session: Session) -> frozenset[int]:
    """Titles the backend canon or a curated list vouches for. Recognition floors
    these — it's what stops culling-the-obscure from deleting exactly the Criterion
    and cult titles the Missing page tells you to acquire.

    The validated canon joins them at tiers 1-3, which are curated, award and
    consensus entries: proposing that one be deleted would contradict the
    acquisition half of the same app, which is busy telling you to go and get it.
    Tier 4 is deliberately excluded — it is fame-fill, and a famous film nobody in
    the house watches is exactly what the junk queue exists to surface.

    Note what this is not: absence from the canon is never evidence of junk. Ten
    thousand films is not every good film, so a title the list omits has had
    nothing said about it at all.
    """
    ids = set(session.scalars(select(CanonMovie.tmdb_id)))
    ids.update(
        session.scalars(
            select(CuratedListEntry.tmdb_id).where(CuratedListEntry.tmdb_id.is_not(None))
        )
    )
    ids.update(canon_entries.protected_tmdb_ids(session))
    return frozenset(ids)


def _watch_by_movie(
    session: Session, movie_ids: list[int]
) -> dict[int, list[dict[str, object]]]:
    """Watch rows grouped per film, for a batch of films in one query."""
    watch: dict[int, list[dict[str, object]]] = {}
    for start in range(0, len(movie_ids), _CHUNK):
        batch = movie_ids[start : start + _CHUNK]
        for row in session.scalars(
            select(WatchHistory).where(WatchHistory.movie_id.in_(batch))
        ):
            watch.setdefault(row.movie_id, []).append(
                {
                    "plays": row.plays,
                    "last_played_at": row.last_played_at,
                    "completion_pct": row.completion_pct,
                }
            )
    return watch


def _iter_scores(
    session: Session, thr: JunkThresholds, now: datetime | None
) -> Iterator[tuple[Movie, scoring.ScoreResult]]:
    """Score every library title, reading the database in batches rather than per
    film.

    The per-film shape this replaces cost four round trips each — the film, its
    ratings, its watch history, and a lazily loaded score row. That is free on the
    SQLite the tests run against and is the dominant cost against hosted Postgres,
    which is the exact gap that produced 2607.15.1. Scoring a library is the
    largest loop in the scan, so it is the worst place to pay it.
    """
    engagement_available = (
        session.scalar(select(func.count()).select_from(WatchHistory)) or 0
    ) > 0
    canon_ids = _canon_ids(session)
    ids = list(session.scalars(select(Movie.tmdb_id).where(Movie.in_plex.is_(True))))

    for start in range(0, len(ids), _CHUNK):
        batch = ids[start : start + _CHUNK]
        movies = {
            m.tmdb_id: m for m in session.scalars(select(Movie).where(Movie.tmdb_id.in_(batch)))
        }
        ratings = _best_ratings(session, batch)
        watches = _watch_by_movie(session, batch)

        for tmdb_id in batch:
            movie = movies.get(tmdb_id)
            if movie is None:
                continue
            value, votes = ratings.get(tmdb_id, (None, None))
            # Recognition needs enrichment facts. A title TMDB hasn't reached yet has
            # a vote count of None, and must not be read as "nobody has heard of it" —
            # that would propose deleting the whole library after a partial scan.
            rec = (
                recognition.recognise(
                    votes=votes,
                    year=movie.year,
                    us_theatrical=bool(movie.us_theatrical),
                    budget=movie.budget,
                    on_canon_list=tmdb_id in canon_ids,
                )
                if votes is not None
                else None
            )
            yield movie, scoring.score_movie(
                rating_value=value,
                rating_votes=votes,
                watch=watches.get(tmdb_id, []),
                is_kids=movie.is_kids,
                thr=thr,
                engagement_available=engagement_available,
                now=now,
                recognition=rec,
            )


def compute_and_store(
    factory: sessionmaker[Session],
    thr: JunkThresholds,
    *,
    now: datetime | None = None,
    cult_ids: frozenset[int] = frozenset(),
) -> int:
    with factory() as session:
        written = 0
        # Preloaded, because ``movie.score`` is a lazy relationship: reading it in
        # the loop is one more round trip per film on top of the three the scoring
        # read used to cost.
        rows = {row.movie_id: row for row in session.scalars(select(Score))}
        for movie, result in _iter_scores(session, thr, now):
            tmdb_id = movie.tmdb_id
            # Classification overlay: the numeric band answers "low?"; the classifier
            # answers "keep or cut, given what kind of film it is".
            scored_low = result.band in ("junk", "borderline")
            verdict = classify(_facts(movie, cult_ids), scored_low=scored_low)
            row = rows.get(tmdb_id)
            if row is None:
                row = Score(movie_id=tmdb_id)
                session.add(row)
                rows[tmdb_id] = row
            row.junk_score = result.junk_score
            row.signals = {
                "signals": [s.as_dict() for s in result.signals],
                "kids_guard": result.kids_guard,
                "band": result.band,
                "verdict": str(verdict.verdict),
                "verdict_reason": verdict.reason,
            }
            row.model_used = None  # deterministic — no model involved
            written += 1
        session.commit()
        return written


def preview(factory: sessionmaker[Session], thr: JunkThresholds) -> dict[str, int]:
    """Count how many titles each band *would* have under the given thresholds,
    without persisting — powers the Settings live preview. Kids items are excluded
    from the junk/borderline counts (never auto-flagged)."""
    counts = {"junk": 0, "borderline": 0, "keep": 0, "total": 0}
    with factory() as session:
        for _movie, result in _iter_scores(session, thr, None):
            counts["total"] += 1
            if result.kids_guard and result.band != "keep":
                counts["keep"] += 1  # guarded → treated as keep for candidate counts
            else:
                counts[result.band] += 1
    return counts


def _is_candidate(score: Score, thr: JunkThresholds) -> bool:
    """Classification-aware selection:

    * ``remove`` verdict → always a candidate (e.g. an adult film, even if well-rated);
    * ``protect`` verdict → never (US theatrical / cult classic, even if it scored low);
    * otherwise → the numeric band decides (at/above the borderline cutoff).
    """
    verdict = (score.signals or {}).get("verdict", Verdict.NEUTRAL)
    if verdict == Verdict.REMOVE:
        return True
    if verdict == Verdict.PROTECT:
        return False
    return score.junk_score >= thr.borderline_cutoff


def candidates(
    session: Session, thr: JunkThresholds, *, limit: int = 200
) -> list[tuple[Movie, Score]]:
    """Removal candidates: library items the classifier + score flag for removal,
    excluding kids-section items (never auto-flagged) and titles the owner has
    marked Keep (a standing verdict, not a per-session one)."""
    stmt = (
        select(Movie, Score)
        .join(Score, Score.movie_id == Movie.tmdb_id)
        .where(
            Movie.in_plex.is_(True),
            Movie.is_kids.is_(False),
            Movie.keep_override.is_(False),
        )
        .order_by(Score.junk_score.desc())
    )
    rows = [(m, s) for m, s in session.execute(stmt) if _is_candidate(s, thr)]
    return rows[:limit]
