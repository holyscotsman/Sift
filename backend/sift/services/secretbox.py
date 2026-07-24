"""Encryption at rest for the service credentials stored in the database.

Why this exists: connection secrets (Plex token, Radarr/TMDB/Overseerr/Anthropic
keys) are entered in the browser and persisted in the ``settings`` table. On the
default throwaway SQLite file that's low-exposure — the database dies with the
container. Point Sift at a persistent hosted Postgres (the recommended fix for
login/config surviving redeploys) and those same secrets would sit in a cloud
database indefinitely, in its backups and replicas, readable by anyone holding
the connection string. So they get encrypted before they're written.

**Key material never lives in the database.** It is resolved, in order:

1. ``SIFT_SECRET_KEY`` — an explicit key, for operators who want to rotate it
   independently of everything else.
2. ``SIFT_SERVER__API_TOKEN`` — the access token the app is already deployed
   with (``render.yaml`` generates it). This is what makes encryption turn
   itself on with no extra operator step.
3. Nothing — encryption is off and values are stored as before. A local SQLite
   install with no token set therefore behaves exactly as it always has.

The stored form is ``enc:v1:<fernet token>``. Anything without that prefix is
legacy plaintext and is read straight through, so an existing database keeps
working; :func:`sift.services.config_store.upgrade_stored_secrets` rewrites
those in place at boot once key material is available.

Losing the key material is not destructive: undecryptable values are reported as
missing (the affected service reads as not-configured and is re-entered in
Settings), never raised as a crash.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

log = logging.getLogger("sift.secretbox")

# Stored ciphertext marker. The version segment means a future scheme change can
# be told apart from v1 values instead of guessing.
PREFIX = "enc:v1:"

# The key material is a deploy token, not a user password, but it's still run
# through a KDF so a Fernet key is derived rather than assumed to be 32 raw bytes.
_KDF_SALT = b"sift.secretbox.v1"
_KDF_ROUNDS = 200_000

# Set at app boot from resolved settings so key material in .env / sift.toml works
# too — process env alone would miss those.
_configured_material: str | None = None


def configure(material: str | None) -> None:
    """Pin the key material explicitly (called once at startup)."""
    global _configured_material
    _configured_material = material.strip() if material and material.strip() else None


def _key_material() -> str | None:
    if _configured_material:
        return _configured_material
    # Fallback for paths that never call configure() (CLI, tests, direct imports).
    for name in ("SIFT_SECRET_KEY", "SIFT_SERVER__API_TOKEN"):
        raw = os.environ.get(name)
        if raw and raw.strip():
            return raw.strip()
    return None


@lru_cache(maxsize=4)
def _fernet_for(material: str) -> Fernet:
    """Derive the Fernet key. Cached because the KDF is deliberately slow and the
    material is stable for the life of the process."""
    digest = hashlib.pbkdf2_hmac("sha256", material.encode(), _KDF_SALT, _KDF_ROUNDS)
    return Fernet(base64.urlsafe_b64encode(digest))


def enabled() -> bool:
    """True when key material is available, i.e. new writes will be encrypted."""
    return _key_material() is not None


def is_encrypted(value: object) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def encrypt(value: str) -> str:
    """Encrypt a secret for storage. With no key material configured, or for an
    empty value (which means 'cleared'), the input is returned unchanged."""
    material = _key_material()
    if material is None or not value:
        return value
    if is_encrypted(value):  # already sealed — don't double-wrap
        return value
    return PREFIX + _fernet_for(material).encrypt(value.encode()).decode()


def decrypt(value: str) -> str | None:
    """Plaintext for a stored value.

    Legacy plaintext passes through untouched. ``None`` means the value *is*
    encrypted but this instance cannot open it (key rotated, lost, or not yet
    set) — callers treat that as 'not configured' rather than failing hard.
    """
    if not is_encrypted(value):
        return value
    material = _key_material()
    if material is None:
        log.warning(
            "A stored secret is encrypted but no key material is set "
            "(SIFT_SECRET_KEY / SIFT_SERVER__API_TOKEN) — treating it as unset."
        )
        return None
    try:
        return _fernet_for(material).decrypt(value[len(PREFIX) :].encode()).decode()
    except InvalidToken:
        log.warning(
            "A stored secret could not be decrypted with the current key — "
            "treating it as unset. Re-enter it in Settings to replace it."
        )
        return None
