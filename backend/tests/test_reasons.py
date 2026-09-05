from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.core import reasons


def test_every_code_has_a_template() -> None:
    """The app must be fully readable with the LLM switched off."""
    missing = [c for c in reasons.ReasonCode if c not in reasons.TEMPLATES]
    assert not missing, f"codes without templates: {missing}"


def test_no_orphan_templates() -> None:
    assert not set(reasons.TEMPLATES) - set(reasons.ReasonCode)


def test_every_template_renders_without_placeholders_leaking() -> None:
    """A template whose placeholder is never supplied would leak `{target}` to the UI."""
    for code in reasons.ReasonCode:
        rendered = reasons.Reason(
            code=code,
            metric="hrv",
            current=47.0,
            baseline=53.0,
            unit="ms",
            difference=-6.0,
            difference_percent=-11.3,
            window_days=30,
            n=30,
            detail={
                "target": 180, "abs_balance": 510, "burned": 2760, "consumed": 2250,
                "consecutive_days": 4, "minutes": 58, "rate": 0.42, "threshold": 0.1,
                "avg_deficit": 430, "window": 21, "required": 15,
                "anchor_date": "2026-10-01", "p_fat": 0.85,
            },
        ).render()
        assert "{" not in rendered and "}" not in rendered, f"{code}: {rendered}"
        assert rendered != code.value, f"{code} did not render"


def test_number_formatting_is_clean() -> None:
    r = reasons.Reason(code=reasons.ReasonCode.HRV_BELOW_BASELINE, current=47.0, baseline=52.20000000001,
               unit="ms", difference_percent=-9.9999, window_days=30)
    text = r.render()
    assert "52.2" in text and "47 ms" in text
    assert "0000" not in text


def test_reasons_are_immutable() -> None:
    """Traces are snapshot data -- a past explanation must stay true to what was known."""
    r = reasons.Reason(code=reasons.ReasonCode.NO_WEIGH_IN)
    with pytest.raises(ValidationError):
        r.code = reasons.ReasonCode.NO_FOOD_LOGGED  # type: ignore[misc]
