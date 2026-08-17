"""Compute and persist deterministic junk scores, and fetch removal candidates.

Only library items (``in_plex``) are scored — Radarr-only "wanted" entries aren't
things you have, so they can't be junk. Kids-section items are scored but carry a
guard and are excluded from removal candidates (never auto-flagged on rating).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import func, insert, select, update
from sqlalchemy.orm import Session, sessionmaker

from ..config import JunkThresholds
from ..db.models import (
    Action,
    ActionActor,
    ActionType,
    CanonMovie,
    CuratedListEntry,
    Movie,
    Rating,
    Score,
    ScoreV2,
    WatchHistory,
)
from ..services import canon_entries
from . import recognition, scoring, scoring_v2
from .classify import MovieFacts, Verdict, classify

# Films per database round trip. 500 matches the chunk size used by the ingest
# writers, and is comfortably inside the parameter limit of every dialect in play.
_CHUNK = 500


class ScoredMovie(NamedTuple):
    """The columns scoring actually reads — and deliberately nothing else.

    ``select(Movie)`` ships all twenty-seven columns, including ``overview``,
    ``poster_url``, ``genres`` and ``keywords``. None of them affects a score, and
    together they are the bulk of the row: roughly 1.4 KB against the 90 bytes
    below. Scoring walks the whole library on every scan, so on a hosted database
    that difference is megabytes of egress per scan for data nothing reads — which
    is how a free tier's monthly transfer allowance disappears in a week.
    """

    tmdb_id: int
    year: int | None
    budget: int | None
    added_at: datetime | None
    original_language: str | None
    is_kids: bool
    is_adult: bool
    is_independent: bool
    us_theatrical: bool
    keep_override: bool
    monitored: bool


_SCORED_COLUMNS = (
    Movie.tmdb_id,
    Movie.year,
    Movie.budget,
    Movie.added_at,
    Movie.original_language,
    Movie.is_kids,
    Movie.is_adult,
    Movie.is_independent,
    Movie.us_theatrical,
    Movie.keep_override,
    Movie.monitored,
)


def _facts(movie: ScoredMovie, cult_ids: frozenset[int]) -> MovieFacts:
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


def _requested_at(session: Session) -> dict[int, datetime]:
    """When the owner first asked for each title, from the audit trail.

    One grouped statement, read once per scoring pass. This is the only place the
    ``actions`` history feeds scoring, and it is what lets v2 tell "nobody wanted
    this" apart from "somebody asked for this and never got round to it" — which
    from watch history alone look identical.
    """
    rows = session.execute(
        select(Action.movie_tmdb_id, func.min(Action.created_at))
        .where(
            Action.movie_tmdb_id.is_not(None),
            Action.type == ActionType.ADD,
            Action.actor == ActionActor.USER,
        )
        .group_by(Action.movie_tmdb_id)
    )
    return {int(tmdb_id): created for tmdb_id, created in rows if created is not None}


def _v2_facts(
    movie: ScoredMovie, cult_ids: frozenset[int], canon_ids: frozenset[int]
) -> scoring_v2.FactsV2:
    lang = movie.original_language
    return scoring_v2.FactsV2(
        keep_override=bool(movie.keep_override),
        is_kids=bool(movie.is_kids),
        is_adult=bool(movie.is_adult),
        is_cult=movie.tmdb_id in cult_ids,
        on_canon_list=movie.tmdb_id in canon_ids,
        us_theatrical=bool(movie.us_theatrical),
        is_independent=bool(movie.is_independent),
        is_international=bool(lang) and lang != "en",
    )


def previous_v2_bands(session: Session) -> dict[int, tuple[str, str | None]]:
    """What v2 said last time, three columns wide.

    Hysteresis needs the previous band and the previous rule, and nothing else.
    ``select(ScoreV2)`` would ship the whole ``signals`` blob for every film —
    about a kilobyte each, for two values.
    """
    return {
        movie_id: (band, rule)
        for movie_id, band, rule in session.execute(
            select(ScoreV2.movie_id, ScoreV2.band, ScoreV2.rule)
        )
    }


def _iter_scores(
    session: Session,
    thr: JunkThresholds,
    now: datetime | None,
    *,
    cult_ids: frozenset[int] = frozenset(),
    shadow: bool = False,
    previous: dict[int, tuple[str, str | None]] | None = None,
) -> Iterator[tuple[ScoredMovie, scoring.ScoreResult, scoring_v2.ScoreV2Result | None]]:
    """Score every library title, reading the database in batches rather than per
    film.

    The per-film shape this replaces cost four round trips each — the film, its
    ratings, its watch history, and a lazily loaded score row. That is free on the
    SQLite the tests run against and is the dominant cost against hosted Postgres,
    which is the exact gap that produced 2607.15.1. Scoring a library is the
    largest loop in the scan, so it is the worst place to pay it.

    With ``shadow`` set it computes v2 from the same batch as v1 — deliberately
    sharing the reads, because a second opinion that doubled the scan's round
    trips would not survive contact with a real library.
    """
    engagement_available = (
        session.scalar(select(func.count()).select_from(WatchHistory)) or 0
    ) > 0
    canon_ids = _canon_ids(session)
    ids = list(session.scalars(select(Movie.tmdb_id).where(Movie.in_plex.is_(True))))

    requested: dict[int, datetime] = {}
    if shadow:
        requested = _requested_at(session)
        if previous is None:
            previous = previous_v2_bands(session)
    previous = previous or {}

    for start in range(0, len(ids), _CHUNK):
        batch = ids[start : start + _CHUNK]
        movies = {
            row.tmdb_id: row
            for row in (
                ScoredMovie(*values)
                for values in session.execute(
                    select(*_SCORED_COLUMNS).where(Movie.tmdb_id.in_(batch))
                )
            )
        }
        ratings = _best_ratings(session, batch)
        watches = _watch_by_movie(session, batch)

        for tmdb_id in batch:
            movie = movies.get(tmdb_id)
            if movie is None:
                continue
            value, votes = ratings.get(tmdb_id, (None, None))
            watch = watches.get(tmdb_id, [])
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
            v1 = scoring.score_movie(
                rating_value=value,
                rating_votes=votes,
                watch=watch,
                is_kids=movie.is_kids,
                thr=thr,
                engagement_available=engagement_available,
                now=now,
                recognition=rec,
            )
            v2 = None
            if shadow:
                prev_band, prev_rule = previous.get(tmdb_id, (None, None))
                v2 = scoring_v2.score_movie_v2(
                    rating_value=value,
                    rating_votes=votes,
                    watch=list(watch),
                    facts=_v2_facts(movie, cult_ids, canon_ids),
                    thr=thr,
                    engagement_available=engagement_available,
                    recognition=rec,
                    requested_at=requested.get(tmdb_id),
                    monitored=bool(movie.monitored),
                    added_at=movie.added_at,
                    previous_band=prev_band,
                    previous_rule=prev_rule,
                    now=now,
                )
            yield movie, v1, v2


def compute_and_store(
    factory: sessionmaker[Session],
    thr: JunkThresholds,
    *,
    now: datetime | None = None,
    cult_ids: frozenset[int] = frozenset(),
) -> int:
    with factory() as session:
        # Keys only, never whole rows. Deciding insert-versus-update needs an id;
        # `select(Score)` shipped the entire `signals` JSON blob for every film to
        # answer that — about a kilobyte each, twice over once v2 joined in. On a
        # hosted database that is the single largest read the scan performs, and
        # every byte of it was discarded.
        v1_ids = {
            movie_id: row_id
            for row_id, movie_id in session.execute(select(Score.id, Score.movie_id))
        }
        v2_ids = {
            movie_id: row_id
            for row_id, movie_id in session.execute(select(ScoreV2.id, ScoreV2.movie_id))
        }
        previous = previous_v2_bands(session)

        v1_new: list[dict[str, object]] = []
        v1_edit: list[dict[str, object]] = []
        v2_new: list[dict[str, object]] = []
        v2_edit: list[dict[str, object]] = []
        written = 0

        for movie, result, shadow in _iter_scores(
            session, thr, now, cult_ids=cult_ids, shadow=True, previous=previous
        ):
            tmdb_id = movie.tmdb_id
            # Classification overlay: the numeric band answers "low?"; the classifier
            # answers "keep or cut, given what kind of film it is".
            scored_low = result.band in ("junk", "borderline")
            verdict = classify(_facts(movie, cult_ids), scored_low=scored_low)
            payload: dict[str, object] = {
                "junk_score": result.junk_score,
                "signals": {
                    "signals": [s.as_dict() for s in result.signals],
                    "kids_guard": result.kids_guard,
                    "band": result.band,
                    "verdict": str(verdict.verdict),
                    "verdict_reason": verdict.reason,
                },
                "model_used": None,  # deterministic — no model involved
            }
            row_id = v1_ids.get(tmdb_id)
            if row_id is None:
                v1_new.append({"movie_id": tmdb_id, **payload})
            else:
                v1_edit.append({"id": row_id, **payload})

            # The shadow opinion, written beside the real one and read by nobody but
            # the diff endpoint. `previous_band` is what v2 said last scan, which is
            # what hysteresis needs to have an opinion about.
            if shadow is not None:
                v2_payload: dict[str, object] = {
                    "score": shadow.score,
                    "band": shadow.band,
                    "rule": shadow.rule,
                    "confidence": shadow.confidence,
                    "signals": shadow.as_dict(),
                    "previous_band": previous.get(tmdb_id, (None, None))[0],
                }
                v2_row_id = v2_ids.get(tmdb_id)
                if v2_row_id is None:
                    v2_new.append({"movie_id": tmdb_id, **v2_payload})
                else:
                    v2_edit.append({"id": v2_row_id, **v2_payload})
            written += 1

        # Bulk, chunked, by primary key — one statement per five hundred films
        # rather than a flush per film.
        for model, fresh, edits in ((Score, v1_new, v1_edit), (ScoreV2, v2_new, v2_edit)):
            for start in range(0, len(fresh), _CHUNK):
                session.execute(insert(model), fresh[start : start + _CHUNK])
            for start in range(0, len(edits), _CHUNK):
                session.execute(update(model), edits[start : start + _CHUNK])
        session.commit()
        return written


def preview(factory: sessionmaker[Session], thr: JunkThresholds) -> dict[str, int]:
    """Count how many titles each band *would* have under the given thresholds,
    without persisting — powers the Settings live preview. Kids items are excluded
    from the junk/borderline counts (never auto-flagged)."""
    counts = {"junk": 0, "borderline": 0, "keep": 0, "total": 0}
    with factory() as session:
        for _movie, result, _shadow in _iter_scores(session, thr, None):
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


def _diff_sort_key(row: dict[str, object]) -> tuple[float, int]:
    """Biggest disagreement first, with tmdb_id as a total tie-break so the same
    library produces the same list every time (the iter-8 rule)."""
    gap = abs(float(str(row["v2_score"])) - float(str(row["v1_score"])))
    return (-gap, int(str(row["tmdb_id"])))


def shadow_diff(
    session: Session, thr: JunkThresholds, *, limit: int = 200
) -> tuple[list[dict[str, object]], dict[str, int]]:
    """Every title where v1 and v2 disagree about the band, plus the totals.

    The golden set checks the rules; this checks the *judgement*. It is the only
    honest eval that exists for taste, because it runs on the owner's own library
    rather than on cases chosen to prove a point — and it is why v2 computes in
    shadow at all instead of simply replacing v1 on a version bump.

    Two statements regardless of library size: both score tables are read whole
    and joined in memory against the titles, which is the same shape the scoring
    loop uses and for the same reason.
    """
    v1_rows = {row.movie_id: row for row in session.scalars(select(Score))}
    v2_rows = {row.movie_id: row for row in session.scalars(select(ScoreV2))}
    shared = sorted(set(v1_rows) & set(v2_rows))

    summary = {
        "compared": len(shared),
        "disagreements": 0,
        "v2_stricter": 0,
        "v2_gentler": 0,
        "v2_abstained": 0,
    }
    order = {"keep": 0, "borderline": 1, "junk": 2}
    diffs: list[dict[str, object]] = []
    for tmdb_id in shared:
        v1_row, v2_row = v1_rows[tmdb_id], v2_rows[tmdb_id]
        v1_band = str((v1_row.signals or {}).get("band") or scoring.band(v1_row.junk_score, thr))
        if v1_band == v2_row.band:
            continue
        summary["disagreements"] += 1
        if v2_row.band == scoring_v2.INSUFFICIENT:
            summary["v2_abstained"] += 1
        elif order.get(v2_row.band, 0) > order.get(v1_band, 0):
            summary["v2_stricter"] += 1
        else:
            summary["v2_gentler"] += 1
        diffs.append(
            {
                "tmdb_id": tmdb_id,
                "v1_band": v1_band,
                "v1_score": v1_row.junk_score,
                "v2_band": v2_row.band,
                "v2_score": v2_row.score,
                "v2_rule": v2_row.rule,
                "v2_confidence": v2_row.confidence,
            }
        )

    diffs.sort(key=_diff_sort_key)
    diffs = diffs[:limit]

    # Titles for the page-worth actually returned, scoped and chunked — never one
    # lookup per row.
    wanted = [int(str(d["tmdb_id"])) for d in diffs]
    titles: dict[int, Movie] = {}
    for start in range(0, len(wanted), _CHUNK):
        for found in session.scalars(
            select(Movie).where(Movie.tmdb_id.in_(wanted[start : start + _CHUNK]))
        ):
            titles[found.tmdb_id] = found
    for row in diffs:
        movie = titles.get(int(str(row["tmdb_id"])))
        row["title"] = movie.title if movie is not None else ""
        row["year"] = movie.year if movie is not None else None
    return diffs, summary
