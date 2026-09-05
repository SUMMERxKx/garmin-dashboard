from __future__ import annotations

import pytest

from backend.core import units


def test_known_conversions() -> None:
    assert units.kg_to_lb(79.0) == pytest.approx(174.165, abs=0.01)
    assert units.lb_to_kg(174.165) == pytest.approx(79.0, abs=0.01)
    assert units.ft_in_to_cm(5, 11) == pytest.approx(180.34, abs=0.01)
    feet, inches = units.cm_to_ft_in(180.0)
    assert feet == 5 and inches == pytest.approx(10.9, abs=0.05)


@pytest.mark.parametrize("kg", [40.0, 79.0, 80.5, 120.0])
def test_weight_round_trip(kg: float) -> None:
    assert units.lb_to_kg(units.kg_to_lb(kg)) == pytest.approx(kg, abs=1e-9)


def test_display_formatting() -> None:
    assert units.format_weight(80.0) == "80.0 kg"
    assert units.format_weight(80.0, units.UnitPreference.IMPERIAL) == "176.4 lb"
    assert units.format_height(180.0) == "180 cm"
    assert units.format_height(180.0, units.UnitPreference.IMPERIAL) == "5'11\""


def test_protein_target_uses_the_unit_a_lifter_thinks_in() -> None:
    assert units.format_protein_target(2.25) == "2.25 g/kg"
    assert units.format_protein_target(2.25, units.UnitPreference.IMPERIAL) == "1.02 g/lb"


@pytest.mark.parametrize(("minutes", "expected"), [(424, "7h 04m"), (58, "58m"), (60, "1h 00m"), (0, "0m")])
def test_duration_formatting(minutes: float, expected: str) -> None:
    assert units.format_duration(minutes) == expected
