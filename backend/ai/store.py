"""Keeping the most recent AI reading, so Bedrock is called once and not once per refresh.

One record, replaced each time. It carries the fingerprint of the facts it was written
about, and `api/server.py` compares that against the current facts before deciding whether
to ask again. So a reading survives as long as the numbers it describes and no longer,
with nobody having to decide how long "fresh" is.

The practical effect: opening the dashboard ten times in a day costs one Bedrock call, and
a new weigh-in or an overnight fetch invalidates it automatically.
"""

from __future__ import annotations

from typing import Any

from backend.store import keys
from backend.store import open_store


def save(store: open_store.Store, reading: dict[str, Any], user_id: str = keys.DEFAULT_USER_ID) -> None:
    """Store the reading, replacing whatever was there."""
    store.save(
        partition_key=keys.user_partition(user_id),
        sort_key=keys.insight_key(),
        body=reading,
    )


def load(store: open_store.Store, user_id: str = keys.DEFAULT_USER_ID) -> dict[str, Any] | None:
    """The stored reading, or None if there has never been one."""
    return store.load(
        partition_key=keys.user_partition(user_id),
        sort_key=keys.insight_key(),
    )


def load_if_still_about(
    store: open_store.Store,
    fingerprint: str,
    user_id: str = keys.DEFAULT_USER_ID,
) -> dict[str, Any] | None:
    """The stored reading, but only if it was written about these exact facts.

    Returning None when the fingerprint differs is what makes the cache self-invalidating.
    There is no expiry to tune and no stale reading to explain: the moment a number
    changes, the old commentary stops being returned.
    """
    stored = load(store, user_id)

    if stored is None:
        return None

    if stored.get("facts_fingerprint") != fingerprint:
        return None

    return stored
