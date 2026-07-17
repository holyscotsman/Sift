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
from ..db.models import Movie, Rating, Score, WatchHistory
from . import scoring
from .classify import MovieFacts, Verdict, classify


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


def _best_rating(session: Session, movie_id: int) -> tuple[float | None, int | None]:
    """Pick the rating with the most votes (most statistically reliable)."""
    rows = session.scalars(select(Rating).where(Rating.movie_id == movie_id)).all()
    if not rows:
        return None, None
    best = max(rows, key=lambda r: r.votes or 0)
    return best.value, best.votes


def _iter_scores(
    session: Session, thr: JunkThresholds, now: datetime | None
) -> Iterator[tuple[int, scoring.ScoreResult]]:
    engagement_available = (
        session.scalar(select(func.count()).select_from(WatchHistory)) or 0
    ) > 0
    for tmdb_id in list(session.scalars(select(Movie.tmdb_id).where(Movie.in_plex.is_(True)))):
        movie = session.get(Movie, tmdb_id)
        if movie is None:
            continue
        value, votes = _best_rating(session, tmdb_id)
        watch = [
            {
                "plays": w.plays,
                "last_played_at": w.last_played_at,
                "completion_pct": w.completion_pct,
            }
            for w in session.scalars(select(WatchHistory).where(WatchHistory.movie_id == tmdb_id))
        ]
        yield tmdb_id, scoring.score_movie(
            rating_value=value,
            rating_votes=votes,
            watch=watch,
            is_kids=movie.is_kids,
            thr=thr,
            engagement_available=engagement_available,
            now=now,
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
        for tmdb_id, result in _iter_scores(session, thr, now):
            movie = session.get(Movie, tmdb_id)
            if movie is None:
                continue
            # Classification overlay: the numeric band answers "low?"; the classifier
            # answers "keep or cut, given what kind of film it is".
            scored_low = result.band in ("junk", "borderline")
            verdict = classify(_facts(movie, cult_ids), scored_low=scored_low)
            row = movie.score
            if row is None:
                row = Score(movie_id=tmdb_id)
                session.add(row)
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
        for _tmdb_id, result in _iter_scores(session, thr, None):
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
