from __future__ import annotations

from datetime import date

from backend.core import models
from backend.providers import base as provider_base
from backend.providers import garmin
from backend.providers import introspect


def test_endpoint_names_are_unique() -> None:
    names = [e.name for e in garmin.ENDPOINTS]
    assert len(names) == len(set(names))


def test_every_endpoint_is_well_formed() -> None:
    valid_args = {provider_base.ArgStyle.NONE, provider_base.ArgStyle.DATE, provider_base.ArgStyle.RANGE, provider_base.ArgStyle.START_END}
    for endpoint in garmin.ENDPOINTS:
        assert endpoint.tier in (1, 2), endpoint.name
        assert endpoint.args in valid_args, endpoint.name
        assert endpoint.method.startswith("get_"), endpoint.name
        assert endpoint.feeds, endpoint.name


def test_endpoint_methods_exist_on_the_real_client() -> None:
    """Catches a typo in the registry without a network call."""
    from garminconnect import Garmin

    missing = [e.method for e in garmin.ENDPOINTS if not hasattr(Garmin, e.method)]
    assert not missing, f"registry references non-existent methods: {missing}"


def test_tier_1_covers_the_dashboard_minimum() -> None:
    feeds = " ".join(e.feeds for e in garmin.TIER_1)
    for section in ("energy", "activity", "recovery"):
        assert section in feeds


def test_endpoint_lookup() -> None:
    assert garmin.endpoint_by_name("sleep") is not None
    assert garmin.endpoint_by_name("nope") is None


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
    raw = garmin.GarminProvider(FakeClient()).fetch_day(date(2026, 9, 2))
    assert raw.payloads["user_summary"]["totalSteps"] == 13842
    assert "sleep" in raw.errors
    assert "RuntimeError" in raw.errors["sleep"]
    assert raw.payloads["hrv"] is None


def test_missing_methods_are_recorded_as_errors_not_crashes() -> None:
    raw = garmin.GarminProvider(FakeClient()).fetch_day(date(2026, 9, 2))
    assert "AttributeError" in raw.errors["stress"]


def test_provider_satisfies_the_port() -> None:
    assert isinstance(garmin.GarminProvider(FakeClient()), provider_base.MetricsProvider)


def test_normalize_delegates_to_the_pure_mapping() -> None:
    """Phase 0 is complete, so `normalize` now maps real discovered field paths.

    Until fixtures existed this test asserted `NotImplementedError` -- Phase 0 discipline
    made executable, so field extraction could not be built on guessed shapes. That guard
    has served its purpose; what matters now is that the provider stays a thin pass-through
    to the pure mapping module, which is what keeps normalization testable against saved
    fixtures without a client. Field-level assertions live in test_garmin_mapping.py.
    """
    provider = garmin.GarminProvider(FakeClient())
    raw = provider_base.RawPayloads(provider="garmin", on=date(2026, 9, 2), payloads={})
    snapshot = provider.normalize(raw)
    assert isinstance(snapshot, models.DailyHealthSnapshot)
    assert snapshot.date == date(2026, 9, 2)
    # nothing to extract from empty payloads, and that is not an error
    assert snapshot.measured.provenance == {}


class ExplodingClient:
    """Every attribute access raises. Used to prove `normalize` never touches the client."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"normalize must not call the client (tried {name!r})")


def test_normalize_does_not_touch_the_client() -> None:
    """`normalize` is pure. If it reached for the client this would raise, which is what
    lets normalization be tested against saved fixtures with no network at all."""
    provider = garmin.GarminProvider(ExplodingClient())
    snapshot = provider.normalize(
        provider_base.RawPayloads(
            provider="garmin", on=date(2026, 9, 2),
            payloads={"user_summary": {"totalKilocalories": 2421.0, "totalSteps": 13842}},
        )
    )
    assert snapshot.measured.energy.total_kcal == 2421.0
    assert snapshot.measured.activity.steps == 13842


def test_capabilities_are_queried_not_assumed() -> None:
    caps = provider_base.ProviderCapabilities(
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
    rendered = "\n".join(f"{path}: {kind}" for path, kind in introspect.summarize(payload))
    assert "SECRET-VALUE-12345" not in rendered
    assert "53" not in rendered
    assert "79.4" not in rendered
    assert "restingHeartRate: int" in rendered
    assert "nested.weight: float" in rendered


def test_summarize_records_nulls_distinctly() -> None:
    fields = dict(introspect.summarize({"hrv": None, "steps": 100}))
    assert fields["hrv"] == "null"
    assert fields["steps"] == "int"


def test_summarize_samples_only_the_first_list_element() -> None:
    """Walking a 1,440-point intraday series would bury the signal."""
    fields = introspect.summarize({"series": [{"v": 1}, {"v": 2}, {"v": 3}]})
    paths = [p for p, _ in fields]
    assert "series[]" in paths
    assert "series[0].v" in paths
    assert not any("[1]" in p for p in paths)


def test_summarize_respects_max_depth() -> None:
    deep = {"a": {"b": {"c": {"d": {"e": 1}}}}}
    paths = [p for p, _ in introspect.summarize(deep, max_depth=2)]
    assert "a.b.c" in paths
    assert not any(p.endswith(".e") for p in paths)


def test_find_metrics_locates_fields_without_hardcoded_paths() -> None:
    payloads = {
        "user_summary": {"totalKilocalories": 2421, "totalSteps": 13842},
        "sleep": {"dailySleepDTO": {"sleepTimeSeconds": 25440, "sleepScores": {"overallSleepScore": 81}}},
        "rhr": {"allMetrics": {"metricsMap": {"WELLNESS_RESTING_HEART_RATE": [{"value": 53}]}}},
    }
    hits = introspect.find_metrics(payloads)
    assert any("sleepTimeSeconds" in loc for loc in hits["sleep duration"])
    assert any("totalKilocalories" in loc for loc in hits["total calories"])
    assert "sleep score" in hits


def test_find_metrics_ignores_nulls() -> None:
    assert "HRV" not in introspect.find_metrics({"hrv": {"hrvSummary": None}})


def test_missing_tier_1_reports_what_the_dashboard_cannot_do() -> None:
    assert set(introspect.missing_tier_1({})) == set(introspect.TIER_1_METRICS)
    complete = {m: ["`x` -> `y`"] for m in introspect.TIER_1_METRICS}
    assert introspect.missing_tier_1(complete) == []


def test_find_metrics_skips_endpoints_that_returned_nothing() -> None:
    """A failed or empty endpoint contributes no field paths rather than crashing."""
    located = introspect.find_metrics({"sleep": None, "user_summary": {"totalKilocalories": 2421}})
    assert "total calories" in located
    assert len(located["total calories"]) == 1


class MultiStyleClient:
    """Exercises all three endpoint argument styles in the registry."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def __getattr__(self, name: str):
        def record_and_return(*args):
            self.calls.append((name, args))
            return {"called": name, "argument_count": len(args)}

        return record_and_return


def test_each_argument_style_is_called_with_the_right_number_of_dates() -> None:
    """The registry stores how each endpoint wants its dates. Endpoints taking a range
    get the same day twice; endpoints taking none get called bare."""
    client = MultiStyleClient()
    raw = garmin.GarminProvider(client).fetch_day(date(2026, 9, 2))

    calls_by_method = {name: args for name, args in client.calls}

    for endpoint in garmin.ENDPOINTS:
        arguments = calls_by_method[endpoint.method]

        if endpoint.args == provider_base.ArgStyle.DATE:
            assert len(arguments) == 1, endpoint.name
        elif endpoint.args in (provider_base.ArgStyle.RANGE, provider_base.ArgStyle.START_END):
            assert len(arguments) == 2, endpoint.name
            assert arguments[0] == arguments[1], endpoint.name
        else:
            assert len(arguments) == 0, endpoint.name

    assert not raw.errors
