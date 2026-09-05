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

from backend.core import models
from backend.providers import base as provider_base
from backend.providers import garmin_mapping

#: Every call we make, and why. Selected against the six dashboard questions -- not
#: against what the API happens to expose. Golf metrics, race predictors and per-second
#: streams are available and irrelevant.
ENDPOINTS: tuple[provider_base.Endpoint, ...] = (
    # ---- tier 1: the dashboard must work on these alone --------------------
    provider_base.Endpoint("user_summary", "get_user_summary", provider_base.ArgStyle.DATE, 1, "energy+activity",
             "steps, distance, active/resting/total calories, intensity minutes"),
    provider_base.Endpoint("stats", "get_stats", provider_base.ArgStyle.DATE, 1, "energy", "daily totals, overlaps user_summary"),
    provider_base.Endpoint("sleep", "get_sleep_data", provider_base.ArgStyle.DATE, 1, "recovery", "duration, score, stages if present"),
    provider_base.Endpoint("hrv", "get_hrv_data", provider_base.ArgStyle.DATE, 1, "recovery", "may be None before the baseline forms"),
    provider_base.Endpoint("rhr", "get_rhr_day", provider_base.ArgStyle.DATE, 1, "recovery", "resting heart rate"),
    provider_base.Endpoint("body_battery", "get_body_battery", provider_base.ArgStyle.START_END, 1, "recovery", ""),
    provider_base.Endpoint("activities", "get_activities_by_date", provider_base.ArgStyle.START_END, 1, "activity",
             "workouts: type, duration, calories, HR"),
    # ---- tier 2: enrichment only, every field Optional ---------------------
    provider_base.Endpoint("stress", "get_stress_data", provider_base.ArgStyle.DATE, 2, "recovery", ""),
    provider_base.Endpoint("heart_rates", "get_heart_rates", provider_base.ArgStyle.DATE, 2, "activity", "intraday HR series"),
    provider_base.Endpoint("intensity_minutes", "get_intensity_minutes_data", provider_base.ArgStyle.DATE, 2, "activity", ""),
    provider_base.Endpoint("respiration", "get_respiration_data", provider_base.ArgStyle.DATE, 2, "recovery", "availability unknown on FR165"),
    provider_base.Endpoint("spo2", "get_spo2_data", provider_base.ArgStyle.DATE, 2, "recovery", "availability unknown on FR165"),
    provider_base.Endpoint("max_metrics", "get_max_metrics", provider_base.ArgStyle.DATE, 2, "trends", "VO2 max"),
    provider_base.Endpoint("daily_weigh_ins", "get_daily_weigh_ins", provider_base.ArgStyle.DATE, 2, "body",
             "picks up weight typed into Garmin Connect"),
    provider_base.Endpoint("steps_intraday", "get_steps_data", provider_base.ArgStyle.DATE, 2, "activity", ""),
    # ---- expected to be EMPTY on the FR165 ---------------------------------
    # Probed anyway so the report proves it rather than assuming it. If these do return
    # data, the derived recovery composite in core/recovery.py becomes optional.
    provider_base.Endpoint("training_readiness", "get_training_readiness", provider_base.ArgStyle.DATE, 2, "-",
             "expected unavailable: FR265 and up"),
    provider_base.Endpoint("training_status", "get_training_status", provider_base.ArgStyle.DATE, 2, "-",
             "expected unavailable: FR265 and up"),
)

TIER_1 = tuple(e for e in ENDPOINTS if e.tier == 1)


def endpoint_by_name(name: str) -> provider_base.Endpoint | None:
    return next((e for e in ENDPOINTS if e.name == name), None)


class GarminProvider:
    """Thin adapter over `garminconnect`.

    The client is injected so the probe, the future Lambda and tests all share this code
    without this module owning credential handling.
    """

    name = "garmin"

    def __init__(self, client: Any, capabilities: provider_base.ProviderCapabilities | None = None) -> None:
        self._client = client
        self.capabilities = capabilities or provider_base.ProviderCapabilities(provider="garmin", device="fr165")

    def fetch_day(self, on: date) -> provider_base.RawPayloads:
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
                if endpoint.args == provider_base.ArgStyle.DATE:
                    payloads[endpoint.name] = method(cdate)
                elif endpoint.args in (provider_base.ArgStyle.RANGE, provider_base.ArgStyle.START_END):
                    payloads[endpoint.name] = method(cdate, cdate)
                else:
                    payloads[endpoint.name] = method()
            except Exception as exc:  # collecting per-endpoint failures is the point
                errors[endpoint.name] = f"{type(exc).__name__}: {exc}"
        return provider_base.RawPayloads(provider=self.name, on=on, payloads=payloads, errors=errors)

    def normalize(self, raw: provider_base.RawPayloads) -> models.DailyHealthSnapshot:
        """Delegate to the pure mapping module.

        Kept as a thin pass-through so normalization can be tested against saved fixtures
        without constructing a client or touching the network. Every field path in there
        was discovered by `scripts/garmin_probe.py`, not guessed.
        """
        return garmin_mapping.normalize_day(raw)
