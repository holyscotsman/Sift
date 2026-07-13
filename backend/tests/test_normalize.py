"""Pure normalization functions."""

from __future__ import annotations

from sift.ingest import normalize


def test_normalize_radarr_movie():
    raw = {
        "id": 5,
        "tmdbId": 27205,
        "imdbId": "tt1375666",
        "title": "Inception",
        "year": 2010,
        "runtime": 148,
        "monitored": True,
        "hasFile": True,
        "sizeOnDisk": 734003200,
        "genres": ["Action", "Sci-Fi"],
        "overview": "A thief...",
        "images": [{"coverType": "poster", "remoteUrl": "http://img/p.jpg"}],
        "movieFile": {"quality": {"quality": {"name": "Bluray-1080p"}}},
        "collection": {"tmdbId": 8945, "title": "Nolan set"},
        "ratings": {
            "imdb": {"value": 8.8, "votes": 200000},
            "tmdb": {"value": 8.3, "votes": 30000},
        },
        "added": "2020-01-02T03:04:05Z",
    }
    out = normalize.normalize_radarr_movie(raw)
    assert out["tmdb_id"] == 27205
    assert out["quality"] == "Bluray-1080p"
    assert out["poster_url"] == "http://img/p.jpg"
    assert out["collection"] == {"tmdb_collection_id": 8945, "name": "Nolan set"}
    assert {r["source"] for r in out["ratings"]} == {"imdb", "tmdb"}
    assert out["added_at"] is not None and out["added_at"].tzinfo is not None


def test_extract_plex_ids_from_guid_list_and_legacy():
    item = {"Guid": [{"id": "tmdb://27205"}, {"id": "imdb://tt1375666"}]}
    assert normalize.extract_plex_ids(item) == (27205, "tt1375666")
    legacy = {"guid": "com.plexapp.agents.themoviedb://603?lang=en"}
    assert normalize.extract_plex_ids(legacy)[0] == 603


def test_normalize_plex_item_marks_kids():
    item = {"ratingKey": 2001, "title": "Toy Story", "year": 1995, "Guid": [{"id": "tmdb://862"}]}
    out = normalize.normalize_plex_item(item, section_title="Kids Movies", is_kids=True)
    assert out["tmdb_id"] == 862
    assert out["is_kids"] is True
    assert out["plex_rating_key"] == "2001"


def test_aggregate_watch_rows():
    rows = [
        normalize.normalize_tautulli_row(
            {"rating_key": 1001, "user": "Dad", "date": 1700000000, "percent_complete": 100},
            kids_accounts=set(),
        ),
        normalize.normalize_tautulli_row(
            {"rating_key": 1001, "user": "Dad", "date": 1700100000, "percent_complete": 50},
            kids_accounts=set(),
        ),
        normalize.normalize_tautulli_row(
            {"rating_key": 2001, "user": "Kiddo", "date": 1700000000, "percent_complete": 80},
            kids_accounts={"Kiddo"},
        ),
    ]
    agg = normalize.aggregate_watch_rows(rows)
    dad = agg[("1001", "Dad")]
    assert dad["plays"] == 2
    assert dad["completion_pct"] == 0.75  # (1.0 + 0.5) / 2
    assert agg[("2001", "Kiddo")]["is_kids_account"] is True


def test_normalize_tmdb_movie_people_and_keywords():
    raw = {
        "id": 27205,
        "keywords": {"keywords": [{"id": 1, "name": "dream"}, {"id": 2, "name": "heist"}]},
        "credits": {
            "crew": [{"id": 525, "name": "Christopher Nolan", "job": "Director"}],
            "cast": [{"id": 6193, "name": "Leonardo DiCaprio"}],
        },
        "belongs_to_collection": {"id": 8945, "name": "Nolan set"},
    }
    out = normalize.normalize_tmdb_movie(raw)
    assert out["keywords"] == ["dream", "heist"]
    jobs = {(p["name"], p["job"]) for p in out["people"]}
    assert ("Christopher Nolan", "director") in jobs
    assert ("Leonardo DiCaprio", "actor") in jobs
    assert out["collection"]["tmdb_collection_id"] == 8945
