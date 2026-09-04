"""Garmin provider.

Auth architecture (PLAN.md section 7): the password is entered once, locally, under MFA.
The resulting token bundle is what the cloud ever sees, so the Garmin password never
exists in AWS -- worst case in a full compromise is a revocable token.

NOTE on the normalizer: `normalize()` is deliberately unimplemented until Phase 0 has
produced real FR165 fixtures. Writing field extraction against guessed response shapes
is exactly what the "don't build infrastructure before understanding the data" rule
exists to prevent. `ENDPOINTS` below is shared by the probe and the future normalizer so
there is one definition of what we fetch.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from backend.core.models import DailyHealthSnapshot
from backend.providers.base import ArgStyle, Endpoint, ProviderCapabilities, RawPayloads
from backend.providers.garmin_mapping import normalize_day

#: Every call we make, and why. Selected against the six dashboard questions -- not
#: against what the API happens to expose. Golf metrics, race predictors and per-second
#: streams are available and irrelevant.
ENDPOINTS: tuple[Endpoint, ...] = (
    # ---- tier 1: the dashboard must work on these alone --------------------
    Endpoint("user_summary", "get_user_summary", ArgStyle.DATE, 1, "energy+activity",
             "steps, distance, active/resting/total calories, intensity minutes"),
    Endpoint("stats", "get_stats", ArgStyle.DATE, 1, "energy", "daily totals, overlaps user_summary"),
    Endpoint("sleep", "get_sleep_data", ArgStyle.DATE, 1, "recovery", "duration, score, stages if present"),
    Endpoint("hrv", "get_hrv_data", ArgStyle.DATE, 1, "recovery", "may be None before the baseline forms"),
    Endpoint("rhr", "get_rhr_day", ArgStyle.DATE, 1, "recovery", "resting heart rate"),
    Endpoint("body_battery", "get_body_battery", ArgStyle.START_END, 1, "recovery", ""),
    Endpoint("activities", "get_activities_by_date", ArgStyle.START_END, 1, "activity",
             "workouts: type, duration, calories, HR"),
    # ---- tier 2: enrichment only, every field Optional ---------------------
    Endpoint("stress", "get_stress_data", ArgStyle.DATE, 2, "recovery", ""),
    Endpoint("heart_rates", "get_heart_rates", ArgStyle.DATE, 2, "activity", "intraday HR series"),
    Endpoint("intensity_minutes", "get_intensity_minutes_data", ArgStyle.DATE, 2, "activity", ""),
    Endpoint("respiration", "get_respiration_data", ArgStyle.DATE, 2, "recovery", "availability unknown on FR165"),
    Endpoint("spo2", "get_spo2_data", ArgStyle.DATE, 2, "recovery", "availability unknown on FR165"),
    Endpoint("max_metrics", "get_max_metrics", ArgStyle.DATE, 2, "trends", "VO2 max"),
    Endpoint("daily_weigh_ins", "get_daily_weigh_ins", ArgStyle.DATE, 2, "body",
             "picks up weight typed into Garmin Connect"),
    Endpoint("steps_intraday", "get_steps_data", ArgStyle.DATE, 2, "activity", ""),
    # ---- expected to be EMPTY on the FR165 ---------------------------------
    # Probed anyway so the report proves it rather than assuming it. If these do return
    # data, the derived recovery composite in core/recovery.py becomes optional.
    Endpoint("training_readiness", "get_training_readiness", ArgStyle.DATE, 2, "-",
             "expected unavailable: FR265 and up"),
    Endpoint("training_status", "get_training_status", ArgStyle.DATE, 2, "-",
             "expected unavailable: FR265 and up"),
)

TIER_1 = tuple(e for e in ENDPOINTS if e.tier == 1)


def endpoint_by_name(name: str) -> Endpoint | None:
    return next((e for e in ENDPOINTS if e.name == name), None)


class GarminProvider:
    """Thin adapter over `garminconnect`.

    The client is injected so the probe, the future Lambda and tests all share this code
    without this module owning credential handling.
    """

    name = "garmin"

    def __init__(self, client: Any, capabilities: ProviderCapabilities | None = None) -> None:
        self._client = client
        self.capabilities = capabilities or ProviderCapabilities(provider="garmin", device="fr165")

    def fetch_day(self, on: date) -> RawPayloads:
        """Call every endpoint for one day, collecting failures rather than aborting.

        One endpoint returning 404 (common: no HRV before the baseline forms) must not
        cost the other fifteen.
        """
        cdate = on.isoformat()
        payloads: dict[str, Any] = {}
        errors: dict[str, str] = {}
        for endpoint in ENDPOINTS:
            try:
                method = getattr(self._client, endpoint.method)
                if endpoint.args == ArgStyle.DATE:
                    payloads[endpoint.name] = method(cdate)
                elif endpoint.args in (ArgStyle.RANGE, ArgStyle.START_END):
                    payloads[endpoint.name] = method(cdate, cdate)
                else:
                    payloads[endpoint.name] = method()
            except Exception as exc:  # collecting per-endpoint failures is the point
                errors[endpoint.name] = f"{type(exc).__name__}: {exc}"
        return RawPayloads(provider=self.name, on=on, payloads=payloads, errors=errors)

    def normalize(self, raw: RawPayloads) -> DailyHealthSnapshot:
        """Delegate to the pure mapping module.

        Kept as a thin pass-through so normalization can be tested against saved fixtures
        without constructing a client or touching the network. Every field path in there
        was discovered by `scripts/garmin_probe.py`, not guessed.
        """
        return normalize_day(raw)
