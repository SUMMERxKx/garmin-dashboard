"""Unit conversion and display formatting -- the ONLY place either happens.

SI is canonical everywhere in the engine and storage: kg, cm, kcal, grams, minutes.
Two rules that prevent the classic bugs:

  1. Never do math on display units. The engine only ever sees kg.
  2. Never round-trip. 79 kg -> 174.2 lb -> 79.01 kg. Store canonical, format for
     display, and never parse a displayed value back into storage.
"""

from __future__ import annotations

from enum import StrEnum

KG_PER_LB = 0.45359237
CM_PER_INCH = 2.54


class UnitPreference(StrEnum):
    METRIC = "metric"
    IMPERIAL = "imperial"


def kg_to_lb(kg: float) -> float:
    return kg / KG_PER_LB


def lb_to_kg(lb: float) -> float:
    return lb * KG_PER_LB


def cm_to_ft_in(cm: float) -> tuple[int, float]:
    total_inches = cm / CM_PER_INCH
    feet = int(total_inches // 12)
    return feet, round(total_inches - feet * 12, 1)


def ft_in_to_cm(feet: int, inches: float) -> float:
    return (feet * 12 + inches) * CM_PER_INCH


def format_weight(kg: float, pref: UnitPreference = UnitPreference.METRIC) -> str:
    if pref is UnitPreference.IMPERIAL:
        return f"{kg_to_lb(kg):.1f} lb"
    return f"{kg:.1f} kg"


def format_height(cm: float, pref: UnitPreference = UnitPreference.METRIC) -> str:
    if pref is UnitPreference.IMPERIAL:
        feet, inches = cm_to_ft_in(cm)
        return f"{feet}'{inches:.0f}\""
    return f"{cm:.0f} cm"


def format_protein_target(grams_per_kg: float, pref: UnitPreference = UnitPreference.METRIC) -> str:
    """A lifter using imperial thinks in g/lb. Showing them g/kg is a tell that units were bolted on."""
    if pref is UnitPreference.IMPERIAL:
        return f"{grams_per_kg * KG_PER_LB:.2f} g/lb"
    return f"{grams_per_kg:.2f} g/kg"


def format_duration(minutes: float) -> str:
    hours, mins = divmod(int(round(minutes)), 60)
    return f"{hours}h {mins:02d}m" if hours else f"{mins}m"
