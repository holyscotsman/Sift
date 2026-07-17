"""AI review orchestration — Ollama (cheap draft) ↔ Anthropic (refine).

In tandem mode the local model drafts a quick advisory note, then Anthropic refines
it into the final one or two sentences; the engine mode (Settings › Connections) can
pin the work to either provider alone. With nothing configured, a deterministic note
is returned so the flow never hard-fails.

**Advisory only.** The deterministic classifier + score already decided keep/remove;
this never changes that. It writes supplementary context for the owner — the §4/§7
rule that AI advises but never grades holds here too.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from ..analysis import junk
from ..config import Settings
from ..db.models import Movie
from ..services.settings_store import effective_junk
from .provider import LLMProvider
from .registry import build_providers

log = logging.getLogger("sift.ai.review")

SYSTEM = (
    "You are a film-library curation assistant. You ADVISE ONLY — a deterministic "
    "system has already decided whether each title is kept or removed, and you must not "
    "override it. Given the facts, write ONE or TWO plain, specific sentences of "
    "advisory context for the library owner. Never invent facts you weren't given."
)


@dataclass(frozen=True)
class ReviewNote:
    note: str
    provider: str


def _prompt(target: dict[str, Any]) -> str:
    genres = ", ".join(target.get("genres") or []) or "unknown"
    decision = target.get("decision") or "flagged for review"
    return (
        f"Title: {target['title']} ({target.get('year') or 'n/a'})\n"
        f"Genres: {genres}\n"
        f"Junk score: {target.get('score')}/100 (band: {target.get('band')})\n"
        f"System decision: {decision}\n"
        f"Reason on record: {target.get('reason') or '—'}\n\n"
        "Advisory note for the owner:"
    )


async def review_one(
    target: dict[str, Any],
    *,
    local: LLMProvider | None,
    anthropic: LLMProvider | None,
) -> ReviewNote:
    prompt = _prompt(target)
    draft: str | None = None
    if local is not None:
        try:
            draft = (await local.complete(system=SYSTEM, prompt=prompt)).text or None
        except Exception as exc:  # noqa: BLE001 - local is best-effort
            log.info("ollama draft failed: %s", exc)

    if anthropic is not None:
        refine = prompt
        if draft:
            refine += f'\n\nA local model drafted: "{draft}". Tighten it to 1–2 sentences.'
        try:
            out = await anthropic.complete(system=SYSTEM, prompt=refine)
            if out.text:
                return ReviewNote(out.text, "anthropic+ollama" if draft else "anthropic")
        except Exception as exc:  # noqa: BLE001 - fall through to draft/deterministic
            log.info("anthropic refine failed: %s", exc)

    if draft:
        return ReviewNote(draft, "ollama")
    # Deterministic fallback — no AI configured or both failed. Prefer the classifier
    # reason; otherwise describe the band so the note never contradicts the verdict.
    reason = target.get("reason")
    if reason:
        return ReviewNote(reason, "deterministic")
    band_note = {
        "junk": "Low on rating/engagement — a solid removal candidate.",
        "borderline": "Borderline on rating/engagement — worth a look before removing.",
    }.get(str(target.get("band")), "No strong removal signals — likely worth keeping.")
    return ReviewNote(band_note, "deterministic")


def _targets(session: Session, settings: Settings, limit: int) -> list[dict[str, Any]]:
    thr = effective_junk(session, settings)
    out: list[dict[str, Any]] = []
    for movie, score in junk.candidates(session, thr, limit=limit):
        payload = score.signals or {}
        out.append(
            {
                "tmdb_id": movie.tmdb_id,
                "title": movie.title,
                "year": movie.year,
                "genres": list(movie.genres or []),
                "score": score.junk_score,
                "band": payload.get("band"),
                "decision": payload.get("verdict"),
                "reason": payload.get("verdict_reason") or "",
            }
        )
    return out


async def run_review(
    session_factory: sessionmaker[Session], settings: Settings, *, limit: int = 50
) -> dict[str, Any]:
    """Review the current removal candidates and store an advisory note on each."""
    local, anthropic = build_providers(settings)
    try:
        targets = await _in_thread(session_factory, lambda s: _targets(s, settings, limit))
        notes: dict[int, ReviewNote] = {}
        for target in targets:
            notes[target["tmdb_id"]] = await review_one(target, local=local, anthropic=anthropic)

        def _persist(session: Session) -> None:
            for tmdb_id, note in notes.items():
                movie = session.get(Movie, tmdb_id)
                if movie is None or movie.score is None:
                    continue
                signals = dict(movie.score.signals or {})
                signals["ai_note"] = note.note
                signals["ai_provider"] = note.provider
                movie.score.signals = signals
                movie.score.model_used = note.provider
            session.commit()

        await _in_thread(session_factory, _persist)
        provider = "anthropic+ollama" if (local and anthropic) else (
            "anthropic" if anthropic else "ollama" if local else "deterministic"
        )
        return {"reviewed": len(notes), "provider": provider}
    finally:
        for prov in (local, anthropic):
            if prov is not None:
                await prov.aclose()


async def _in_thread(session_factory: sessionmaker[Session], fn: Any) -> Any:
    import asyncio

    def _run() -> Any:
        with session_factory() as session:
            return fn(session)

    return await asyncio.to_thread(_run)
