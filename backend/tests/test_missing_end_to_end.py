"""The whole Missing feature, walked once as a person would use it.

Every part of this is tested somewhere: the lists have their own pins, the
affinity arithmetic has its own file, the ignore endpoint has its own suite.
What none of them prove is that the parts fit together — and the two bugs this
feature shipped with were both integration bugs, invisible from inside any one
piece. The API sent raw pillar tags as reasons because the route and the analysis
disagreed about what `reasons` meant; the top-up ranked last because the ranking
and the top-up disagreed about what a missing score meant.

So this walks the flow end to end, through the HTTP API rather than the services,
and asserts the things a person would actually notice.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from sift.db.models import CanonEntry, CanonMetadata, Movie
from sift.db.session import init_db, make_engine, make_session_factory
from sift.main import create_app
from sift.services import auth, canon_affinity, canon_entries


@pytest.fixture
def client(tmp_path, settings):
    engine = make_engine(tmp_path / "e2e.db")
    init_db(engine)
    factory = make_session_factory(engine)

    with factory() as session:
        canon_entries.seed(session)
        session.execute(
            update(CanonEntry).values(tmdb_id=CanonEntry.id, review_status="resolved")
        )
        # A shelf with a clear preference on it: five Kurosawa films.
        rows = session.execute(
            select(CanonEntry.imdb_id, CanonEntry.title, CanonEntry.id)
            .join(CanonMetadata, CanonMetadata.imdb_id == CanonEntry.imdb_id)
            .where(CanonMetadata.directors.like("%Akira Kurosawa%"))
            .limit(5)
        ).all()
        for imdb_id, title, cid in rows:
            session.add(
                Movie(
                    tmdb_id=cid,
                    imdb_id=imdb_id,
                    title=title,
                    in_plex=True,
                    genres=["Drama"],
                    library_section="Films",
                )
            )
        session.commit()
        canon_affinity.recompute(session)
        auth.create_account(session, "owner", "hunter2hunter2")
        token = auth.issue_token(
            auth._signing_secret(auth.get_auth(session)) or "", "owner"
        )

    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        c.headers.update({"Authorization": f"Bearer {token}"})
        yield c


def suggestions(client: TestClient, **params) -> dict:
    resp = client.get("/api/missing/suggestions", params={"limit": 60, **params})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_list_arrives_ranked_explained_and_described(client):
    """One request, and everything a card needs is on it."""
    body = suggestions(client)
    items = body["items"]
    assert len(items) == 60
    assert body["total"] > 20_000

    top = items[0]
    # Ranked by the shelf: five Kurosawa films owned, so a Kurosawa film leads.
    assert "Akira Kurosawa" in top["directors"]
    assert "You own 5 films by Akira Kurosawa" in top["reasons"]
    # And described well enough to decide on.
    assert top["genres"]
    assert top["runtime"]
    assert top["title"] and top["year"]

    # Most of the page carries its metadata, not just the first row.
    assert sum(1 for i in items if i["genres"]) / len(items) > 0.9
    assert sum(1 for i in items if i["directors"]) / len(items) > 0.9


def test_NEGATIVE_CONTROL_the_reasons_never_name_the_built_in_list(client):
    """The list is meant to be invisible. This is the assertion that would have
    caught the API handing back `cult` and `imdb_wr` as a film's reasons."""
    items = suggestions(client)["items"]
    said = {reason for item in items for reason in item["reasons"]}
    assert said, "no reasons at all would make this pass vacuously"
    for reason in said:
        for leak in ("criterion", "cult", "imdb_wr", "canon", "canon_patch", "floor_override"):
            assert leak not in reason.lower(), reason


def test_one_director_does_not_fill_the_page(client):
    items = suggestions(client)["items"]
    lead = 0
    for item in items:
        if "Akira Kurosawa" in item["directors"]:
            lead += 1
        else:
            break
    assert lead <= 7
    assert len({d for i in items for d in i["directors"]}) > 30


def test_setting_a_title_aside_removes_it_for_good(client):
    """The refusal has to outlive the request that made it, and outlive a
    re-read of the list — which is the whole difference between a queue you can
    work and a list that keeps handing back the same titles."""
    first = suggestions(client)["items"][0]

    resp = client.post(
        "/api/missing/ignore",
        json={"tmdb_id": first["tmdb_id"], "title": first["title"], "source": "missing"},
    )
    assert resp.status_code in (200, 201), resp.text

    after = suggestions(client)
    assert first["tmdb_id"] not in {i["tmdb_id"] for i in after["items"]}
    # And it is accounted for rather than merely gone.
    assert after["ignored_total"] >= 1
    assert after["total"] < 1e9


def test_NEGATIVE_CONTROL_taking_the_refusal_back_returns_the_title(client):
    """A permanent decision the owner cannot undo is a trap, not a feature."""
    first = suggestions(client)["items"][0]
    client.post(
        "/api/missing/ignore",
        json={"tmdb_id": first["tmdb_id"], "title": first["title"], "source": "missing"},
    )
    assert first["tmdb_id"] not in {i["tmdb_id"] for i in suggestions(client)["items"]}

    resp = client.delete(f"/api/missing/ignore/{first['tmdb_id']}")
    assert resp.status_code == 200, resp.text
    assert first["tmdb_id"] in {i["tmdb_id"] for i in suggestions(client)["items"]}


def test_paging_never_skips_or_repeats_a_title(client):
    """Four pages, no title twice.

    Worth having, and worth being clear about what it does *not* prove: removing
    the id from the ORDER BY leaves this green. SQLite happens to return rows in a
    stable scan order, so equal-ranked films do not actually swap places here even
    when nothing guarantees they cannot. The property itself is pinned below.
    """
    seen: list[int] = []
    for offset in range(0, 240, 60):
        page = suggestions(client, offset=offset, with_total="false")["items"]
        assert len(page) == 60
        seen.extend(i["tmdb_id"] for i in page)
    assert len(seen) == len(set(seen))


def test_the_ordering_is_total_by_construction(client):
    """The ordering must end in a unique column, and that is a claim about the
    query rather than about one database's scan order.

    Two films with equal scores and equal vote counts swapping places between
    requests would silently skip a title on the page boundary. It is invisible
    until somebody notices a film they never saw, and by then it is
    unreproducible — which is exactly the kind of bug that has to be pinned
    structurally, because no behavioural test on SQLite can see it.
    """
    from sqlalchemy.dialects import postgresql

    from sift.analysis import canon_missing

    compiled = str(
        canon_missing._page_query().compile(dialect=postgresql.dialect())
    )
    order_by = compiled.split("ORDER BY")[1]
    last_term = order_by.split(",")[-1].strip().split()[0]
    assert last_term.endswith(".tmdb_id"), order_by


def test_the_tier_filter_narrows_without_losing_the_ranking(client):
    items = suggestions(client, tier=1)["items"]
    assert items
    assert {i["tier"] for i in items} == {1}
    assert "Akira Kurosawa" in items[0]["directors"]
