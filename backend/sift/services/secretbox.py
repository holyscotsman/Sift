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

# Key material, highest priority first. Set at app boot from resolved settings so
# material in .env / sift.toml works too — process env alone would miss those.
#
# It's a *list* because the two sources legitimately change places: an instance that
# sealed its secrets under the access token and later gains a SIFT_SECRET_KEY (Render
# generates one when the blueprint syncs) must still be able to open them. New writes
# always use the first entry; reads try each in turn, and the boot upgrade re-seals
# anything that only opened under a fallback.
_configured_materials: list[str] = []

# Below this, key material is too weak to resist an offline dictionary attack against
# a stolen database: the KDF salt is a constant in a public repo, so a short,
# human-chosen token is precomputable. Generated tokens are far longer.
_WEAK_MATERIAL_CHARS = 16
_warned_weak = False


def configure(*materials: str | None) -> None:
    """Pin the key material explicitly (called once at startup), highest priority
    first. Entries after the first are accepted for decryption only."""
    global _configured_materials
    kept: list[str] = []
    for material in materials:
        text = material.strip() if material else ""
        if text and text not in kept:
            kept.append(text)
    _configured_materials = kept


def _key_materials() -> list[str]:
    if _configured_materials:
        return _configured_materials
    # Fallback for paths that never call configure() (CLI, tests, direct imports).
    found: list[str] = []
    for name in ("SIFT_SECRET_KEY", "SIFT_SERVER__API_TOKEN"):
        raw = os.environ.get(name)
        if raw and raw.strip() and raw.strip() not in found:
            found.append(raw.strip())
    return found


def _warn_if_weak(material: str) -> None:
    global _warned_weak
    if not _warned_weak and len(material) < _WEAK_MATERIAL_CHARS:
        _warned_weak = True
        log.warning(
            "Encryption key material is short (<%d chars). Stored credentials are only "
            "as strong as it is — prefer a generated SIFT_SECRET_KEY.",
            _WEAK_MATERIAL_CHARS,
        )


@lru_cache(maxsize=4)
def _fernet_for(material: str) -> Fernet:
    """Derive the Fernet key. Cached because the KDF is deliberately slow and the
    material is stable for the life of the process."""
    digest = hashlib.pbkdf2_hmac("sha256", material.encode(), _KDF_SALT, _KDF_ROUNDS)
    return Fernet(base64.urlsafe_b64encode(digest))


def enabled() -> bool:
    """True when key material is available, i.e. new writes will be encrypted."""
    return bool(_key_materials())


def is_encrypted(value: object) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def encrypt(value: str) -> str:
    """Encrypt a secret for storage. With no key material configured, or for an
    empty value (which means 'cleared'), the input is returned unchanged."""
    materials = _key_materials()
    if not materials or not value:
        return value
    if is_encrypted(value):  # already sealed — don't double-wrap
        return value
    _warn_if_weak(materials[0])
    return PREFIX + _fernet_for(materials[0]).encrypt(value.encode()).decode()


def decrypt(value: str) -> str | None:
    """Plaintext for a stored value.

    Legacy plaintext passes through untouched. ``None`` means the value *is*
    encrypted but this instance cannot open it with any configured key (rotated,
    lost, or not yet set) — callers treat that as 'not configured' rather than
    failing hard.
    """
    if not is_encrypted(value):
        return value
    materials = _key_materials()
    if not materials:
        log.warning(
            "A stored secret is encrypted but no key material is set "
            "(SIFT_SECRET_KEY / SIFT_SERVER__API_TOKEN) — treating it as unset."
        )
        return None
    body = value[len(PREFIX) :].encode()
    for material in materials:
        try:
            return _fernet_for(material).decrypt(body).decode()
        except InvalidToken:
            continue
    log.warning(
        "A stored secret could not be decrypted with any current key — treating it "
        "as unset. Re-enter it in Settings to replace it."
    )
    return None


def needs_resealing(value: object) -> bool:
    """True when a stored value should be rewritten: still plaintext, or sealed under
    a fallback key rather than the current primary one."""
    if not enabled() or not isinstance(value, str) or not value:
        return False
    if not is_encrypted(value):
        return True  # legacy plaintext
    body = value[len(PREFIX) :].encode()
    try:
        _fernet_for(_key_materials()[0]).decrypt(body)
    except InvalidToken:
        # Opens under a fallback → reseal. Unreadable entirely → leave it alone,
        # overwriting would destroy data the owner may still recover with the old key.
        return decrypt(value) is not None
    return False


def reseal(value: str) -> str:
    """Rewrite a value under the primary key, preserving the plaintext. Returns the
    input untouched when it can't be opened — never destroys an unreadable secret."""
    plain = decrypt(value)
    if plain is None:
        return value
    materials = _key_materials()
    if not materials:
        return value
    return PREFIX + _fernet_for(materials[0]).encrypt(plain.encode()).decode()
