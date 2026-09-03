from __future__ import annotations

from datetime import date

import pytest

from backend.providers.base import ArgStyle, MetricsProvider, ProviderCapabilities, RawPayloads
from backend.providers.garmin import ENDPOINTS, TIER_1, GarminProvider, endpoint_by_name
from backend.providers.introspect import TIER_1_METRICS, find_metrics, missing_tier_1, summarize


def test_endpoint_names_are_unique() -> None:
    names = [e.name for e in ENDPOINTS]
    assert len(names) == len(set(names))


def test_every_endpoint_is_well_formed() -> None:
    valid_args = {ArgStyle.NONE, ArgStyle.DATE, ArgStyle.RANGE, ArgStyle.START_END}
    for endpoint in ENDPOINTS:
        assert endpoint.tier in (1, 2), endpoint.name
        assert endpoint.args in valid_args, endpoint.name
        assert endpoint.method.startswith("get_"), endpoint.name
        assert endpoint.feeds, endpoint.name


def test_endpoint_methods_exist_on_the_real_client() -> None:
    """Catches a typo in the registry without a network call."""
    from garminconnect import Garmin

    missing = [e.method for e in ENDPOINTS if not hasattr(Garmin, e.method)]
    assert not missing, f"registry references non-existent methods: {missing}"


def test_tier_1_covers_the_dashboard_minimum() -> None:
    feeds = " ".join(e.feeds for e in TIER_1)
    for section in ("energy", "activity", "recovery"):
        assert section in feeds


def test_endpoint_lookup() -> None:
    assert endpoint_by_name("sleep") is not None
    assert endpoint_by_name("nope") is None


class FakeClient:
    """Two endpoints work, one raises. Everything else is simply absent."""

    def get_user_summary(self, cdate: str) -> dict:
        return {"totalKilocalories": 2421, "totalSteps": 13842, "restingHeartRate": 53}

    def get_sleep_data(self, cdate: str) -> dict:
        raise RuntimeError("404 Client Error")

    def get_hrv_data(self, cdate: str) -> None:
        return None


def test_one_failing_endpoint_does_not_cost_the_others() -> None:
    """No HRV before the baseline forms is normal; it must not abort the sync."""
    raw = GarminProvider(FakeClient()).fetch_day(date(2026, 9, 2))
    assert raw.payloads["user_summary"]["totalSteps"] == 13842
    assert "sleep" in raw.errors
    assert "RuntimeError" in raw.errors["sleep"]
    assert raw.payloads["hrv"] is None


def test_missing_methods_are_recorded_as_errors_not_crashes() -> None:
    raw = GarminProvider(FakeClient()).fetch_day(date(2026, 9, 2))
    assert "AttributeError" in raw.errors["stress"]


def test_provider_satisfies_the_port() -> None:
    assert isinstance(GarminProvider(FakeClient()), MetricsProvider)


def test_normalize_refuses_to_guess_at_shapes() -> None:
    """Phase 0 discipline, enforced: no field extraction before real fixtures exist."""
    provider = GarminProvider(FakeClient())
    raw = RawPayloads(provider="garmin", on=date(2026, 9, 2), payloads={})
    with pytest.raises(NotImplementedError, match="fixtures"):
        provider.normalize(raw)


def test_capabilities_are_queried_not_assumed() -> None:
    caps = ProviderCapabilities(
        provider="garmin", device="fr165",
        available=frozenset({"hrv", "body_battery"}),
        unavailable=frozenset({"training_readiness"}),
    )
    assert caps.has("hrv") is True
    assert caps.has("training_readiness") is False


# --- introspection ---------------------------------------------------------


def test_summarize_never_emits_a_value() -> None:
    """The property that makes the generated report safe to commit."""
    payload = {"restingHeartRate": 53, "note": "SECRET-VALUE-12345", "nested": {"weight": 79.4}}
    rendered = "\n".join(f"{path}: {kind}" for path, kind in summarize(payload))
    assert "SECRET-VALUE-12345" not in rendered
    assert "53" not in rendered
    assert "79.4" not in rendered
    assert "restingHeartRate: int" in rendered
    assert "nested.weight: float" in rendered


def test_summarize_records_nulls_distinctly() -> None:
    fields = dict(summarize({"hrv": None, "steps": 100}))
    assert fields["hrv"] == "null"
    assert fields["steps"] == "int"


def test_summarize_samples_only_the_first_list_element() -> None:
    """Walking a 1,440-point intraday series would bury the signal."""
    fields = summarize({"series": [{"v": 1}, {"v": 2}, {"v": 3}]})
    paths = [p for p, _ in fields]
    assert "series[]" in paths
    assert "series[0].v" in paths
    assert not any("[1]" in p for p in paths)


def test_summarize_respects_max_depth() -> None:
    deep = {"a": {"b": {"c": {"d": {"e": 1}}}}}
    paths = [p for p, _ in summarize(deep, max_depth=2)]
    assert "a.b.c" in paths
    assert not any(p.endswith(".e") for p in paths)


def test_find_metrics_locates_fields_without_hardcoded_paths() -> None:
    payloads = {
        "user_summary": {"totalKilocalories": 2421, "totalSteps": 13842},
        "sleep": {"dailySleepDTO": {"sleepTimeSeconds": 25440, "sleepScores": {"overallSleepScore": 81}}},
        "rhr": {"allMetrics": {"metricsMap": {"WELLNESS_RESTING_HEART_RATE": [{"value": 53}]}}},
    }
    hits = find_metrics(payloads)
    assert any("sleepTimeSeconds" in loc for loc in hits["sleep duration"])
    assert any("totalKilocalories" in loc for loc in hits["total calories"])
    assert "sleep score" in hits


def test_find_metrics_ignores_nulls() -> None:
    assert "HRV" not in find_metrics({"hrv": {"hrvSummary": None}})


def test_missing_tier_1_reports_what_the_dashboard_cannot_do() -> None:
    assert set(missing_tier_1({})) == set(TIER_1_METRICS)
    complete = {m: ["`x` -> `y`"] for m in TIER_1_METRICS}
    assert missing_tier_1(complete) == []
