from __future__ import annotations

from datetime import date

import pytest

from backend.core import body_composition as bc
from backend.core import models
from backend.core import reasons


def scan(day: date, total: float, fat: float, lean: float, bone: float = 3.2) -> models.DexaScan:
    return models.DexaScan(
        date=day, total_mass_kg=total, fat_mass_kg=fat, lean_mass_kg=lean,
        bone_mass_kg=bone, body_fat_pct=fat / total * 100.0,
    )


def test_reconciliation_guard_accepts_a_real_scan() -> None:
    assert scan(date(2026, 10, 1), 80.0, 15.2, 61.5).reconciles() is True


def test_reconciliation_guard_catches_a_misread_decimal() -> None:
    """Same pattern as the nutrition label check: our arithmetic validates the extraction."""
    assert scan(date(2026, 10, 1), 80.0, 1.52, 61.5).reconciles() is False


def test_a_scan_is_measured() -> None:
    result = bc.from_dexa(scan(date(2026, 10, 1), 80.0, 15.2, 61.5))
    assert result.measured is True
    assert result.reasons[0].code is reasons.ReasonCode.COMPOSITION_MEASURED


def test_an_estimate_is_never_marked_measured() -> None:
    """The guard that stops an estimate rendering as a scan."""
    anchor = scan(date(2026, 10, 1), 80.0, 15.2, 61.5)
    result = bc.estimate(77.0, date(2026, 11, 15), anchor)
    assert result.measured is False
    assert result.p_fat_used == bc.DEFAULT_P_FAT
    assert result.reasons[0].code is reasons.ReasonCode.COMPOSITION_ESTIMATED


def test_estimate_attributes_most_loss_to_fat() -> None:
    anchor = scan(date(2026, 10, 1), 80.0, 15.2, 61.5)
    result = bc.estimate(77.0, date(2026, 11, 15), anchor)
    # 3 kg lost, 85% of it fat -> fat down 2.55, lean down 0.45
    assert result.fat_mass_kg == pytest.approx(15.2 - 2.55)
    assert result.lean_mass_kg == pytest.approx(77.0 - result.fat_mass_kg)
    assert result.body_fat_pct < anchor.body_fat_pct


def test_no_scan_means_no_composition_at_all() -> None:
    """Inventing a body fat percentage from height and weight would be a guess dressed
    as a measurement. The Body screen shows weight and trend only."""
    assert bc.composition_on(79.0, date(2026, 9, 3), []) is None


def test_no_weigh_in_means_no_composition() -> None:
    anchor = scan(date(2026, 10, 1), 80.0, 15.2, 61.5)
    assert bc.composition_on(None, date(2026, 11, 1), [anchor]) is None


def test_composition_prefers_a_scan_on_the_same_day() -> None:
    anchor = scan(date(2026, 10, 1), 80.0, 15.2, 61.5)
    result = bc.composition_on(80.0, date(2026, 10, 1), [anchor])
    assert result is not None and result.measured is True


def test_composition_uses_the_latest_prior_scan_as_anchor() -> None:
    first = scan(date(2026, 10, 1), 80.0, 15.2, 61.5)
    second = scan(date(2027, 1, 15), 75.8, 12.4, 60.1)
    result = bc.composition_on(75.0, date(2027, 2, 1), [first, second])
    assert result is not None and result.anchor_scan_date == second.date


def test_compare_scans_is_order_independent() -> None:
    first = scan(date(2026, 10, 1), 80.0, 15.2, 61.5)
    second = scan(date(2027, 1, 15), 75.8, 12.4, 60.1)
    a = bc.compare_scans(first, second)
    b = bc.compare_scans(second, first)
    assert a == b
    assert a.fat_change_kg == pytest.approx(-2.8)
    assert a.lean_change_kg == pytest.approx(-1.4)
    assert a.days_between == 106


def test_solve_p_fat_replaces_the_default_with_a_measured_ratio() -> None:
    """The point of the second feedback loop: the literature guess gets retired."""
    first = scan(date(2026, 10, 1), 80.0, 15.2, 61.5)
    second = scan(date(2027, 1, 15), 75.8, 12.4, 60.1)
    solved = bc.solve_p_fat(first, second)
    assert solved is not None
    # 2.8 kg of the 4.2 kg lost was fat
    assert solved == pytest.approx(2.8 / 4.2, abs=0.001)
    assert solved < bc.DEFAULT_P_FAT  # this hypothetical cut went worse than assumed


def test_solve_p_fat_is_undefined_without_weight_change() -> None:
    first = scan(date(2026, 10, 1), 80.0, 15.2, 61.5)
    second = scan(date(2027, 1, 15), 80.1, 14.0, 62.8)
    assert bc.solve_p_fat(first, second) is None
