"""The storage endpoints, including that they are read-only and behind auth."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sift.db.models import MediaFile, Movie
from sift.main import create_app

GB = 1_000_000_000
HOUR_MS = 3_600_000
MIN_MS = 60_000


@pytest.fixture
def client(settings, factory):
    for name in ("plex", "radarr", "tautulli", "tmdb"):
        getattr(settings, name).enabled = False
    app = create_app(settings, session_factory=factory)
    with TestClient(app) as c:
        yield c, factory


def _seed(factory) -> None:
    with factory() as session:
        for i in range(10):
            session.add(Movie(tmdb_id=1000 + i, title=f"Ordinary {i}", year=2015, runtime=120))
            session.add(
                MediaFile(
                    movie_tmdb_id=1000 + i,
                    path=f"/movies/ordinary{i}.mkv",
                    size=6 * GB,
                    duration_ms=2 * HOUR_MS,
                    resolution="1080p",
                    video_codec="h264",
                    source="plex",
                )
            )
        session.add(Movie(tmdb_id=9001, title="Bloated", year=2015, runtime=90))
        session.add(
            MediaFile(
                movie_tmdb_id=9001,
                path="/movies/bloated.mkv",
                size=30 * GB,
                duration_ms=90 * MIN_MS,
                resolution="1080p",
                video_codec="h264",
                source="plex",
            )
        )
        session.commit()


def test_movie_sizes_reports_the_bloated_film(client):
    c, factory = client
    _seed(factory)
    body = c.get("/api/storage/movies").json()
    assert [i["tmdb_id"] for i in body["items"]] == [9001]
    assert body["items"][0]["kind"] == "oversized"
    assert body["items"][0]["bytes_reclaimable"] > 20 * GB
    assert body["total_reclaimable"] >= body["items"][0]["bytes_reclaimable"]


def test_baselines_are_inspectable(client):
    c, factory = client
    _seed(factory)
    body = c.get("/api/storage/baselines").json()
    bucket = next(b for b in body["buckets"] if b["resolution"] == "1080p")
    assert bucket["observed"] is True
    assert bucket["samples"] >= 10


def test_an_empty_library_answers_cleanly(client):
    """NEGATIVE CONTROL: a fresh instance must return an empty report, not a 500
    from measuring baselines over nothing."""
    c, _ = client
    body = c.get("/api/storage/movies").json()
    assert body["items"] == []
    assert body["total_reclaimable"] == 0
    assert c.get("/api/storage/baselines").json()["buckets"] == []


def test_storage_is_read_only(client):
    """NEGATIVE CONTROL: nothing here may mutate. A POST must not be routed."""
    c, _ = client
    assert c.post("/api/storage/movies").status_code == 405


def test_ledger_orders_by_risk_then_size(client):
    c, factory = client
    _seed(factory)
    body = c.get("/api/storage/ledger").json()
    tiers = [i["risk_tier"] for i in body["items"]]
    assert tiers == sorted(tiers)
    assert body["total_reclaimable"] >= 0
    assert [t["tier"] for t in body["tiers"]] == [0, 1, 2]


def test_the_planner_reports_falling_short_rather_than_overpromising(client):
    """NEGATIVE CONTROL: a plan that quietly misses its target sends someone
    deleting things for nothing."""
    c, factory = client
    _seed(factory)
    body = c.post("/api/storage/plan", json={"target_bytes": 500_000 * GB}).json()
    assert body["reached"] is False
    assert body["total"] < 500_000 * GB


def _seed_tv(factory) -> None:
    from sift.db.models import Episode, MediaFile, Season, Show

    with factory() as session:
        session.add(Show(tvdb_id=76156, title="Scrubs", library_section="TV", in_plex=True))
        season = Season(show_id=76156, season_number=1, air_year=2001)
        session.add(season)
        session.flush()
        for n in range(1, 11):
            episode = Episode(season_id=season.id, episode_number=n, has_file=True)
            session.add(episode)
            session.flush()
            # One episode in SD among nine in HD — an accident, not a decision.
            hd = n != 10
            session.add(
                MediaFile(
                    episode_id=episode.id,
                    path=f"/tv/s01e{n:02d}.mkv",
                    part_group=f"g{n}",
                    size=3 * GB if hd else 400_000_000,
                    duration_ms=22 * MIN_MS,
                    resolution="1080p" if hd else "480p",
                    video_codec="h264",
                    source="plex",
                )
            )
        session.commit()


def test_inconsistent_seasons_are_reachable(client):
    """The odd-episode-out report was asked for by name. Built, tested, and for
    a while reachable from nowhere — this pins that it is served."""
    c, factory = client
    _seed_tv(factory)
    body = c.get("/api/storage/tv").json()
    odd = body["inconsistencies"]
    assert len(odd) == 1
    assert odd[0]["common_resolution"] == "1080p"
    assert odd[0]["odd_resolutions"] == {"480p": 1}
    assert odd[0]["episodes_affected"] >= 1


def test_inconsistency_is_not_counted_as_reclaimable(client):
    """NEGATIVE CONTROL: fixing a season with one SD episode among nineteen HD
    ones usually costs space. Folding it into a reclaim total would overstate
    what the library can give back."""
    c, factory = client
    _seed_tv(factory)
    tv = c.get("/api/storage/tv").json()
    assert tv["inconsistencies"]

    ledger = c.get("/api/storage/ledger").json()
    kinds = {i["kind"] for i in ledger["items"]}
    assert "inconsistency" not in kinds
    assert "inconsistent_season" not in kinds


def test_tv_storage_is_empty_on_a_movies_only_library(client):
    """NEGATIVE CONTROL."""
    c, _ = client
    body = c.get("/api/storage/tv").json()
    assert body["duplicates"] == []
    assert body["inconsistencies"] == []
    assert body["duplicate_bytes"] == 0


def _seed_actionable(factory) -> list[str]:
    """One episode held twice, so there is a real surplus to act on."""
    from sift.db.models import Episode, MediaFile, Season, Show

    paths = ["/tv/scrubs/s01e01.1080p.mkv", "/tv/scrubs/s01e01.sd.mkv"]
    with factory() as session:
        session.add(Show(tvdb_id=76156, title="Scrubs", library_section="TV", in_plex=True))
        season = Season(show_id=76156, season_number=1, air_year=2001)
        session.add(season)
        session.flush()
        episode = Episode(season_id=season.id, episode_number=1, has_file=True)
        session.add(episode)
        session.flush()
        for path, size, res in ((paths[0], 3 * GB, "1080p"), (paths[1], 1 * GB, "480p")):
            session.add(
                MediaFile(
                    episode_id=episode.id,
                    path=path,
                    part_group=path,
                    size=size,
                    duration_ms=22 * MIN_MS,
                    resolution=res,
                    video_codec="h264",
                    source="plex",
                )
            )
        session.commit()
    return paths


def test_acting_on_a_finding_records_an_action_and_its_jobs(client):
    c, factory = client
    paths = _seed_actionable(factory)
    body = c.post(
        "/api/storage/act",
        json={
            "target_kind": "show",
            "target_id": "76156",
            "paths": [paths[1]],
            "label": "Scrubs S1E1 surplus copy",
        },
    ).json()
    assert len(body["job_ids"]) == 1

    from sift.db.models import Action, ActionStatus, FileJob

    with factory() as session:
        action = session.get(Action, body["action_id"])
        assert action is not None
        # Proposed, not approved — asking is not agreeing.
        assert action.status == ActionStatus.PROPOSED
        assert action.payload["via"] == "agent"
        job = session.get(FileJob, body["job_ids"][0])
        assert job is not None and job.kind == "delete"
        assert job.source_path == paths[1]


def test_a_path_sift_has_never_seen_is_refused(client):
    """NEGATIVE CONTROL, and the one that matters most. Without it this endpoint
    is a way to have an agent with filesystem access delete anything on the box."""
    c, factory = client
    _seed_actionable(factory)
    response = c.post(
        "/api/storage/act",
        json={"target_kind": "show", "target_id": "76156", "paths": ["/etc/passwd"]},
    )
    assert response.status_code == 400

    from sift.db.models import FileJob

    with factory() as session:
        assert session.query(FileJob).count() == 0


def test_an_empty_selection_is_refused(client):
    """NEGATIVE CONTROL."""
    c, factory = client
    _seed_actionable(factory)
    assert (
        c.post(
            "/api/storage/act",
            json={"target_kind": "show", "target_id": "76156", "paths": []},
        ).status_code
        == 400
    )


def test_a_proposed_job_is_not_claimable_until_approved(client, factory):
    """The whole point of proposing rather than doing, pinned from both sides:
    unapproved hands out nothing, approved-and-live hands out exactly the file
    that was selected."""
    from sift.services import config_store

    c, factory = client
    paths = _seed_actionable(factory)
    with factory() as session:
        config_store.set_config(session, {"transcode": {"agent_token": "tok"}})
    # Let the instance issue real writes; dry-run is the server's floor and would
    # otherwise (correctly) hand out nothing at all.
    c.put("/api/config/actions", json={"dry_run": False})

    body = c.post(
        "/api/storage/act",
        json={"target_kind": "show", "target_id": "76156", "paths": [paths[1]]},
    ).json()
    assert body["dry_run"] is False

    before = c.post("/api/agent/claim", headers={"X-Sift-Agent-Token": "tok"})
    assert before.json()["job"] is None

    c.post(f"/api/actions/{body['action_id']}/approve")
    after = c.post("/api/agent/claim", headers={"X-Sift-Agent-Token": "tok"}).json()
    assert after["job"]["source_path"] == paths[1]
    assert after["job"]["kind"] == "delete"


def test_a_staged_instance_records_the_approval_but_frees_nothing(client, factory):
    """NEGATIVE CONTROL: dry-run means your decision is audited and the disk is
    untouched. The agent must be handed nothing even after you approve."""
    from sift.services import config_store

    c, factory = client
    paths = _seed_actionable(factory)
    with factory() as session:
        config_store.set_config(session, {"transcode": {"agent_token": "tok"}})
    c.put("/api/config/actions", json={"dry_run": True})

    body = c.post(
        "/api/storage/act",
        json={"target_kind": "show", "target_id": "76156", "paths": [paths[1]]},
    ).json()
    assert body["dry_run"] is True

    c.post(f"/api/actions/{body['action_id']}/approve")
    claimed = c.post("/api/agent/claim", headers={"X-Sift-Agent-Token": "tok"})
    assert claimed.json()["job"] is None


def test_the_surplus_paths_never_include_the_copy_being_kept(client):
    """NEGATIVE CONTROL, and the one that decides whether this is safe. These
    paths are what a click sends to be deleted; the best copy of each episode
    must not be among them."""
    c, factory = client
    paths = _seed_actionable(factory)
    body = c.get("/api/storage/tv").json()
    show = body["duplicates"][0]
    assert show["surplus_paths"] == [paths[1]]  # the 480p one
    assert paths[0] not in show["surplus_paths"]  # the 1080p one is kept


def test_removing_every_copy_of_an_episode_is_refused(client):
    """The promise every finding here rests on, enforced where it can be relied on.

    "Only the surplus copies go" was a property of how findings were *computed*,
    not of what this endpoint would *accept*. A request that did not come from a
    finding — a stale page, a repeated call, a client bug — was checked only for
    whether the paths existed. Both of these paths exist, and together they are the
    entire episode.
    """
    c, factory = client
    paths = _seed_actionable(factory)
    response = c.post(
        "/api/storage/act",
        json={"target_kind": "show", "target_id": "76156", "paths": paths, "label": "both"},
    )
    assert response.status_code == 400
    assert "last copy" in response.json()["detail"]

    from sift.db.models import Action

    with factory() as session:
        assert session.query(Action).count() == 0, "nothing may be recorded on a refusal"


def test_removing_the_surplus_copy_is_still_allowed(client):
    """NEGATIVE CONTROL. A guard that refused any episode deletion would pass the
    test above and make the whole duplicate report unusable — its entire purpose is
    removing one of these two files."""
    c, factory = client
    paths = _seed_actionable(factory)
    response = c.post(
        "/api/storage/act",
        json={"target_kind": "show", "target_id": "76156", "paths": [paths[1]], "label": "one"},
    )
    assert response.status_code == 200
    assert len(response.json()["job_ids"]) == 1


def test_removing_a_films_only_copy_is_refused(client):
    """Films get the same floor as episodes. A single-copy film is the common case,
    so an oversized-film finding must never arrive here as a delete."""
    from sift.db.models import MediaFile, Movie

    c, factory = client
    with factory() as session:
        session.add(Movie(tmdb_id=4242, title="Only Copy", year=2001, in_plex=True))
        session.add(
            MediaFile(
                movie_tmdb_id=4242, path="/films/only.mkv", size=40 * GB,
                duration_ms=120 * MIN_MS, resolution="1080p", video_codec="h264", source="plex",
            )
        )
        session.commit()

    response = c.post(
        "/api/storage/act",
        json={"target_kind": "movie", "target_id": "4242", "paths": ["/films/only.mkv"],
              "label": "the only copy"},
    )
    assert response.status_code == 400
    assert "last copy" in response.json()["detail"]


def test_the_strand_check_reads_only_what_the_request_touches(client):
    """The guard must not cost the whole library to answer a question about two
    files.

    It was written as one unfiltered read of `media_files`, filtered in Python.
    That is one statement — so a statement count would have called it fine — but
    it ships every row in the table over the wire on every reclaim action, and a
    thirty-thousand-episode library pays that to check two paths. The cost grows
    forever while the request stays the same size, which is the shape worth
    pinning rather than the count.
    """
    from sqlalchemy import event

    c, factory = client
    paths = _seed_actionable(factory)

    seen: list[str] = []
    engine = factory.kw["bind"]

    @event.listens_for(engine, "before_cursor_execute")
    def _capture(_conn, _cur, statement, *_a, **_kw):
        seen.append(" ".join(statement.split()))

    try:
        response = c.post(
            "/api/storage/act",
            json={"target_kind": "show", "target_id": "76156", "paths": [paths[1]], "label": "one"},
        )
    finally:
        event.remove(engine, "before_cursor_execute", _capture)

    assert response.status_code == 200  # the work really happened
    reads = [s for s in seen if "FROM media_files" in s and s.upper().startswith("SELECT")]
    assert reads, "the guard did not read media_files at all — is it still running?"
    unscoped = [s for s in reads if "WHERE" not in s.upper()]
    assert not unscoped, f"whole-table read of media_files: {unscoped[0][:120]}"


def _statements(factory, run) -> list[str]:
    """Every SQL statement issued while `run()` executes."""
    from sqlalchemy import event

    seen: list[str] = []
    engine = factory.kw["bind"]

    @event.listens_for(engine, "before_cursor_execute")
    def _record(_conn, _cur, statement, *_a, **_kw):
        seen.append(" ".join(statement.split()))

    try:
        run()
    finally:
        event.remove(engine, "before_cursor_execute", _record)
    return seen


def test_the_tv_page_reads_the_season_join_once(client):
    """The widest read in the app, and the page was doing it twice.

    Season sizes and season inconsistencies are two questions about one set of
    rows — every episode file joined to its season and show. Each was loading
    that join for itself, so opening the page shipped the whole of a TV library's
    file metadata across the wire twice over. On a hosted database that is billed
    by bytes moved, not by statements, the duplicate is the entire cost of the
    page.

    Counting the join rather than timing it is deliberate: tests run on local
    SQLite, where the second read is free and invisible.
    """
    c, factory = client
    _seed_tv(factory)

    seen = _statements(factory, lambda: c.get("/api/storage/tv"))

    season_joins = [
        s for s in seen if "FROM media_files" in s and "JOIN seasons" in s and "JOIN shows" in s
    ]
    assert season_joins, "the page stopped reading the join — is it still answering?"
    assert len(season_joins) == 1, f"{len(season_joins)} reads of the season join"
    show_reads = [s for s in seen if s.startswith("SELECT") and " FROM shows" in s]
    assert len(show_reads) == 1, f"{len(show_reads)} whole-table reads of shows"


def test_sharing_the_load_does_not_change_the_answers(client):
    """NEGATIVE CONTROL: the cheap way must give the same result as the dear one.

    An injected read that the callee quietly ignored — or one loaded at the wrong
    grain — would satisfy the statement count above while reporting a different
    library. Ask both questions both ways and require the answers to match.
    """
    from sift.analysis import outliers as outlier_analysis
    from sift.analysis import tv_size

    c, factory = client
    _seed_tv(factory)

    with factory() as session:
        baselines = outlier_analysis.load_baselines(session)
        alone_sized, alone_excess = tv_size.seasons(session, baselines=baselines)
        alone_odd = tv_size.inconsistencies(session)

        groups = tv_size.load_seasons(session)
        shows = tv_size.load_shows(session)
        shared_sized, shared_excess = tv_size.seasons(
            session, baselines=baselines, groups=groups, shows=shows
        )
        shared_odd = tv_size.inconsistencies(session, groups=groups, shows=shows)

    assert alone_sized == shared_sized and alone_excess == shared_excess
    assert alone_odd == shared_odd
    # And the answers are not vacuously empty on both sides.
    assert shared_sized and shared_odd


def _seed_surplus_pairs(factory, *, tvdb_id: int, count: int) -> list[str]:
    """`count` episodes, each held twice. Returns the surplus paths."""
    from sift.db.models import Episode, MediaFile, Season, Show

    surplus: list[str] = []
    with factory() as session:
        session.add(Show(tvdb_id=tvdb_id, title=f"Show {tvdb_id}", library_section="TV"))
        season = Season(show_id=tvdb_id, season_number=1, air_year=2010)
        session.add(season)
        session.flush()
        for n in range(1, count + 1):
            episode = Episode(season_id=season.id, episode_number=n, has_file=True)
            session.add(episode)
            session.flush()
            keep = f"/tv/{tvdb_id}/s01e{n:02d}.1080p.mkv"
            drop = f"/tv/{tvdb_id}/s01e{n:02d}.sd.mkv"
            for path, size, res in ((keep, 3 * GB, "1080p"), (drop, 1 * GB, "480p")):
                session.add(
                    MediaFile(
                        episode_id=episode.id,
                        path=path,
                        part_group=path,
                        size=size,
                        duration_ms=22 * MIN_MS,
                        resolution=res,
                        video_codec="h264",
                        source="plex",
                    )
                )
            surplus.append(drop)
        session.commit()
    return surplus


def _act(c, tvdb_id: int, paths: list[str]):
    return c.post(
        "/api/storage/act",
        json={
            "target_kind": "show",
            "target_id": str(tvdb_id),
            "paths": paths,
            "label": "surplus",
        },
    )


def _round_trips(factory, run) -> tuple[list[str], int]:
    """Statements issued, and how many transactions were committed."""
    from sqlalchemy import event

    seen: list[str] = []
    commits = 0
    engine = factory.kw["bind"]

    @event.listens_for(engine, "before_cursor_execute")
    def _record(_conn, _cur, statement, *_a, **_kw):
        seen.append(" ".join(statement.split()))

    @event.listens_for(engine, "commit")
    def _committed(_conn):
        nonlocal commits
        commits += 1

    try:
        run()
    finally:
        event.remove(engine, "before_cursor_execute", _record)
        event.remove(engine, "commit", _committed)
    return seen, commits


def test_staging_an_approval_commits_once_however_many_files_it_covers(client):
    """One button press, one transaction.

    Each staged job was committed and then read back individually, so approving a
    show's worth of duplicate episodes cost two extra round trips per file. On
    local SQLite that is free; against a hosted database it is the difference
    between the approval landing and the page appearing to hang.

    What is counted here is the commit and the read-back, not the inserts: the
    inserts themselves collapse into one statement on Postgres and stay one per
    row on SQLite, so counting them would pin the test database's behaviour
    rather than the app's.
    """
    c, factory = client
    small = _seed_surplus_pairs(factory, tvdb_id=101, count=3)
    large = _seed_surplus_pairs(factory, tvdb_id=202, count=12)

    small_stmts, small_commits = _round_trips(factory, lambda: _act(c, 101, small))
    large_stmts, large_commits = _round_trips(factory, lambda: _act(c, 202, large))

    def read_backs(stmts: list[str]) -> int:
        return len([s for s in stmts if s.startswith("SELECT") and " FROM file_jobs" in s])

    assert [s for s in large_stmts if "INSERT INTO file_jobs" in s], "nothing was staged"
    # Four times the files, and the transaction count does not move.
    assert large_commits == small_commits, f"{large_commits} commits vs {small_commits}"
    assert read_backs(large_stmts) == read_backs(small_stmts) == 0


def test_every_file_still_gets_its_own_job(client):
    """NEGATIVE CONTROL: cheapness must not become fewer jobs.

    Collapsing twelve deletions into one row would satisfy the count above and
    quietly drop eleven files from the approval — the opposite of what the
    per-item gate exists for.
    """
    from sift.db.models import FileJob

    c, factory = client
    paths = _seed_surplus_pairs(factory, tvdb_id=303, count=12)

    body = _act(c, 303, paths).json()
    assert len(body["job_ids"]) == 12

    with factory() as session:
        jobs = [session.get(FileJob, jid) for jid in body["job_ids"]]
    assert all(j is not None for j in jobs)
    assert {j.source_path for j in jobs if j} == set(paths)
    # Sizes are carried per job, not shared — the ledger reports what each frees.
    assert all(j.source_size == 1 * GB for j in jobs if j)
