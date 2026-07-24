"""Encryption at rest for stored service credentials.

The property that matters: a dump of the database must not contain a usable key.
Every test here asserts against the *raw stored value*, not just the round-trip.
"""

from __future__ import annotations

import pytest

from sift.db.models import Setting
from sift.services import config_store, secretbox


@pytest.fixture(autouse=True)
def _reset_secretbox():
    """Key material is process-global; keep tests independent of each other."""
    secretbox.configure(None)
    yield
    secretbox.configure(None)


def _stored(factory) -> dict:
    """The bytes actually on disk — bypasses the decrypting accessor."""
    with factory() as session:
        row = session.get(Setting, "connections")
        return dict(row.value) if row and row.value else {}


# ------------------------------------------------------------------ the primitive


def test_encrypt_round_trips_and_hides_the_plaintext():
    secretbox.configure("deploy-token-abc")
    sealed = secretbox.encrypt("rk-super-secret")
    assert sealed.startswith(secretbox.PREFIX)
    assert "rk-super-secret" not in sealed  # the point of the exercise
    assert secretbox.decrypt(sealed) == "rk-super-secret"


def test_without_key_material_values_pass_through_unchanged():
    # Negative control: no key configured → today's behaviour, byte for byte.
    secretbox.configure(None)
    assert secretbox.enabled() is False
    assert secretbox.encrypt("plain") == "plain"
    assert secretbox.decrypt("plain") == "plain"


def test_wrong_key_cannot_decrypt_and_reports_unset_instead_of_crashing():
    secretbox.configure("original-key")
    sealed = secretbox.encrypt("tmdb-key")
    # Negative control: a different key must NOT open it...
    secretbox.configure("rotated-key")
    assert secretbox.decrypt(sealed) is None
    # ...and neither does having no key at all (rather than raising).
    secretbox.configure(None)
    assert secretbox.decrypt(sealed) is None
    # The original key still works — the data isn't damaged, just unreadable.
    secretbox.configure("original-key")
    assert secretbox.decrypt(sealed) == "tmdb-key"


def test_legacy_plaintext_is_read_through_and_not_double_wrapped():
    secretbox.configure("k")
    assert secretbox.decrypt("legacy-plain-key") == "legacy-plain-key"
    sealed = secretbox.encrypt("v")
    assert secretbox.encrypt(sealed) == sealed  # already sealed → unchanged
    assert secretbox.encrypt("") == ""  # empty means 'cleared', stays empty


def test_env_fallback_prefers_explicit_key_then_the_access_token(monkeypatch):
    secretbox.configure(None)
    monkeypatch.delenv("SIFT_SECRET_KEY", raising=False)
    monkeypatch.setenv("SIFT_SERVER__API_TOKEN", "token-material")
    assert secretbox.enabled() is True
    from_token = secretbox.encrypt("s")
    # An explicit key takes precedence, so the token-sealed value stops opening.
    monkeypatch.setenv("SIFT_SECRET_KEY", "explicit-material")
    assert secretbox.decrypt(from_token) is None


# ------------------------------------------------------------- through the store


def test_saved_secrets_are_encrypted_on_disk_but_plaintext_to_callers(factory):
    secretbox.configure("deploy-token")
    with factory() as session:
        config_store.set_config(
            session,
            {
                "radarr": {"base_url": "http://radarr.test", "api_key": "rk-live"},
                "plex": {"token": "px-live"},
            },
        )

    raw = _stored(factory)
    # On disk: sealed, and the secret string appears nowhere in the whole blob.
    assert raw["radarr"]["api_key"].startswith(secretbox.PREFIX)
    assert raw["plex"]["token"].startswith(secretbox.PREFIX)
    assert "rk-live" not in str(raw) and "px-live" not in str(raw)
    # Non-secret fields stay readable — only credentials are sealed.
    assert raw["radarr"]["base_url"] == "http://radarr.test"

    # To the app: unchanged plaintext, so the overlay keeps working.
    with factory() as session:
        cfg = config_store.get_config(session)
    assert cfg["radarr"]["api_key"] == "rk-live"
    assert cfg["plex"]["token"] == "px-live"


def test_overlay_still_builds_live_settings_from_sealed_values(settings, factory):
    secretbox.configure("deploy-token")
    with factory() as session:
        config_store.set_config(session, {"tmdb": {"api_key": "tk"}})
        cfg = config_store.get_config(session)
    eff = config_store.apply_to_settings(settings, cfg)
    assert eff.tmdb.api_key.get_secret_value() == "tk" and eff.tmdb.enabled


def test_boot_upgrade_seals_preexisting_plaintext(factory):
    # A database written before encryption existed: plaintext on disk.
    secretbox.configure(None)
    with factory() as session:
        config_store.set_config(session, {"radarr": {"api_key": "old-plain"}})
    assert _stored(factory)["radarr"]["api_key"] == "old-plain"

    # Key material arrives (deployed with a token) → boot seals it in place.
    secretbox.configure("deploy-token")
    with factory() as session:
        assert config_store.upgrade_stored_secrets(session) == 1
    assert _stored(factory)["radarr"]["api_key"].startswith(secretbox.PREFIX)
    with factory() as session:
        assert config_store.get_config(session)["radarr"]["api_key"] == "old-plain"
        # Idempotent: a second boot finds nothing left to do.
        assert config_store.upgrade_stored_secrets(session) == 0


def test_upgrade_is_a_noop_without_key_material(factory):
    # Negative control: with no key, boot must not rewrite anything.
    secretbox.configure(None)
    with factory() as session:
        config_store.set_config(session, {"radarr": {"api_key": "plain"}})
        assert config_store.upgrade_stored_secrets(session) == 0
    assert _stored(factory)["radarr"]["api_key"] == "plain"


def test_unrelated_save_never_destroys_an_unreadable_secret(factory):
    """The dangerous edge: saving one service while another's key can't be opened
    must not overwrite the sealed value with a null."""
    secretbox.configure("original-key")
    with factory() as session:
        config_store.set_config(session, {"plex": {"token": "px-live"}})
    sealed_before = _stored(factory)["plex"]["token"]

    secretbox.configure("rotated-key")  # plex token is now unreadable
    with factory() as session:
        cfg = config_store.get_config(session)
        assert cfg["plex"]["token"] is None  # reads as not-configured
        config_store.set_config(session, {"radarr": {"api_key": "rk"}})

    # The untouched ciphertext survived byte for byte...
    assert _stored(factory)["plex"]["token"] == sealed_before
    # ...and is readable again once the original key is back.
    secretbox.configure("original-key")
    with factory() as session:
        assert config_store.get_config(session)["plex"]["token"] == "px-live"


def test_masked_view_reports_an_unreadable_secret_as_unset(factory):
    secretbox.configure("original-key")
    with factory() as session:
        config_store.set_config(session, {"radarr": {"api_key": "rk"}})
    secretbox.configure("rotated-key")
    with factory() as session:
        masked = config_store.masked(config_store.get_config(session))
    assert masked["radarr"]["api_key_set"] is False
