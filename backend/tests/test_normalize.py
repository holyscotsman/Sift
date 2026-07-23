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
    # No cutoff flag in the payload → not an upgrade candidate.
    assert out["cutoff_unmet"] is False


def test_normalize_radarr_cutoff_unmet_variants():
    # Flag on the movieFile, with a file present → upgrade wanted.
    on_file = normalize.normalize_radarr_movie(
        {"tmdbId": 1, "hasFile": True, "movieFile": {"qualityCutoffNotMet": True}}
    )
    assert on_file["cutoff_unmet"] is True

    # Flag at the movie root (older Radarr shape) → still detected.
    on_root = normalize.normalize_radarr_movie(
        {"tmdbId": 2, "hasFile": True, "qualityCutoffNotMet": True}
    )
    assert on_root["cutoff_unmet"] is True

    # NEGATIVE CONTROL: cutoff flag set but no file → not a candidate (nothing to upgrade).
    no_file = normalize.normalize_radarr_movie(
        {"tmdbId": 3, "hasFile": False, "qualityCutoffNotMet": True}
    )
    assert no_file["cutoff_unmet"] is False


def test_normalize_tmdb_classifier_facts():
    raw = {
        "id": 27205,
        "adult": False,
        "original_language": "en",
        "budget": 160_000_000,
        "production_companies": [{"name": "Warner Bros. Pictures"}],
        "release_dates": {
            "results": [
                {"iso_3166_1": "US", "release_dates": [{"type": 3}]},  # theatrical
                {"iso_3166_1": "FR", "release_dates": [{"type": 1}]},  # premiere only
            ]
        },
        "keywords": {"keywords": [{"name": "dream"}]},
    }
    out = normalize.normalize_tmdb_movie(raw)
    assert out["us_theatrical"] is True
    assert out["is_adult"] is False
    assert out["is_independent"] is False  # big budget + major studio
    assert out["original_language"] == "en"


def test_normalize_tmdb_independent_and_adult():
    indie = normalize.normalize_tmdb_movie(
        {"id": 1, "budget": 200_000, "production_companies": [{"name": "Tiny Indie LLC"}]}
    )
    assert indie["is_independent"] is True
    assert indie["us_theatrical"] is False  # no release_dates

    adult = normalize.normalize_tmdb_movie({"id": 2, "adult": True})
    assert adult["is_adult"] is True


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


def test_theatrical_scale_covers_streaming_studio_releases():
    from sift.ingest.normalize import _us_theatrical

    # Streaming-only, but a major studio is attached → kept (theatrical-scale).
    amazon_streamer = {
        "release_dates": {"results": [
            {"iso_3166_1": "US", "release_dates": [{"type": 4}]},  # 4 = digital
        ]},
        "production_companies": [{"name": "Amazon MGM Studios"}],
        "budget": 0,
    }
    assert _us_theatrical(amazon_streamer) is True

    # Studio-scale budget with no studio name match → still kept.
    big_budget = {"release_dates": {}, "production_companies": [], "budget": 60_000_000}
    assert _us_theatrical(big_budget) is True

    # Negative control: small-budget indie with no theatrical run stays unprotected.
    indie = {
        "release_dates": {"results": [
            {"iso_3166_1": "US", "release_dates": [{"type": 4}]},
        ]},
        "production_companies": [{"name": "Tiny Films LLC"}],
        "budget": 900_000,
    }
    assert _us_theatrical(indie) is False


def test_radarr_relative_poster_paths_are_dropped():
    from sift.ingest.normalize import normalize_radarr_movie

    relative = normalize_radarr_movie(
        {"tmdbId": 1, "title": "X",
         "images": [{"coverType": "poster", "url": "/MediaCover/1/poster.jpg"}]}
    )
    assert relative["poster_url"] is None  # unfetchable → let TMDB-by-id resolve it

    absolute = normalize_radarr_movie(
        {"tmdbId": 2, "title": "Y",
         "images": [{"coverType": "poster",
                     "remoteUrl": "https://image.tmdb.org/t/p/original/y.jpg"}]}
    )
    assert absolute["poster_url"] == "https://image.tmdb.org/t/p/original/y.jpg"
