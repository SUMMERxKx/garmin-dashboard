"""Provider port: one interface, one implementation.

Deliberately not a plugin registry. The abstraction that matters is that the canonical
model is shaped by what the ENGINE needs rather than by what any provider returns --
normalise to your first provider's JSON and you inherit its gaps permanently.

The FR165 tests this abstraction for free: it reports no Training Readiness or Training
Load, so the engine already has to handle "provider doesn't supply this" from day one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from datetime import date
from typing import Any
from typing import Protocol
from typing import runtime_checkable


class ArgStyle:
    """How a provider endpoint wants its date arguments."""

    NONE = "none"
    DATE = "date"          # (cdate)
    RANGE = "range"        # (start, end)
    START_END = "start_end"  # (startdate, enddate)


@dataclass(frozen=True)
class Endpoint:
    """One provider call.

    Tier 1 endpoints must be enough to render the dashboard on their own; tier 2 only
    enriches the detail views. Keeping this as data rather than code means adding an
    endpoint is a one-line change and the Phase 0 probe stays generic.
    """

    name: str          # fixture filename and report key
    method: str        # method on the provider client
    args: str          # ArgStyle
    tier: int          # 1 = required, 2 = enhancement
    feeds: str         # which dashboard section consumes it
    note: str = ""


@dataclass(frozen=True)
class ProviderCapabilities:
    """What this provider/device actually supplies, discovered rather than assumed.

    Populated from a Phase 0 probe and stored per provider link, so the engine can say
    *which* input it lacked instead of silently producing a thinner answer.
    """

    provider: str
    device: str | None = None
    available: frozenset[str] = field(default_factory=frozenset)
    unavailable: frozenset[str] = field(default_factory=frozenset)

    def has(self, metric: str) -> bool:
        return metric in self.available


@dataclass(frozen=True)
class RawPayloads:
    """Exactly what the provider returned, before any parsing.

    Persisted to S3 as the immutable landing zone: a parser bug then becomes a replay
    rather than a re-fetch, and the normalized store is never the only copy.
    """

    provider: str
    on: date
    payloads: Mapping[str, Any]
    errors: Mapping[str, str] = field(default_factory=dict)

    def get(self, endpoint: str) -> Any | None:
        return self.payloads.get(endpoint)


@runtime_checkable
class MetricsProvider(Protocol):
    """The port. `fetch_day` touches the network; `normalize` is pure."""

    name: str
    capabilities: ProviderCapabilities

    def fetch_day(self, on: date) -> RawPayloads: ...

    def normalize(self, raw: RawPayloads) -> Any:  # -> DailyHealthSnapshot
        ...
