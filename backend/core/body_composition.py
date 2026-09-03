"""Body composition: DEXA anchors, estimates between them, and comparison.

Scale weight cannot tell you whether a cut is working. Down 3 kg could be 3 kg of fat, or
2 kg of fat and 1 kg of lean mass -- a good cut and a bad one, identical on the scale.
DEXA is the only input here that separates them; everything between scans is explicitly
an estimate and carries `measured=False`.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from backend.core.models import Composition, DexaScan, ScanComparison
from backend.core.reasons import Reason, ReasonCode

#: Fraction of weight change that is fat, used between anchors.
#: 0.85 rather than the generic 0.75 because 3 resistance sessions/week at ~2.25 g/kg
#: protein is close to the textbook prescription for preserving lean mass in a deficit.
#: Still a default -- section 6.2 of ENGINE.md replaces it with a measured ratio once
#: two scans exist.
DEFAULT_P_FAT = 0.85


def from_dexa(scan: DexaScan) -> Composition:
    return Composition(
        date=scan.date,
        weight_kg=scan.total_mass_kg,
        fat_mass_kg=scan.fat_mass_kg,
        lean_mass_kg=scan.lean_mass_kg,
        body_fat_pct=scan.body_fat_pct,
        measured=True,
        anchor_scan_date=scan.date,
        reasons=[
            Reason(
                code=ReasonCode.COMPOSITION_MEASURED,
                metric="body_composition",
                detail={"anchor_date": scan.date.isoformat()},
            )
        ],
    )


def latest_scan_before(scans: Sequence[DexaScan], on: date) -> DexaScan | None:
    applicable = [s for s in scans if s.date <= on]
    return max(applicable, key=lambda s: s.date) if applicable else None


def estimate(
    weight_kg: float,
    on: date,
    anchor: DexaScan,
    *,
    p_fat: float = DEFAULT_P_FAT,
) -> Composition:
    """Project composition forward from an anchor scan.

    fat_mass = fat_at_anchor + (weight_now - weight_at_anchor) * p_fat

    Always `measured=False`. The `Composition.measured` flag is the guard that stops this
    ever rendering as if a scan had happened.
    """
    delta = weight_kg - anchor.total_mass_kg
    fat_mass = max(0.0, anchor.fat_mass_kg + delta * p_fat)
    lean_mass = max(0.0, weight_kg - fat_mass)
    body_fat_pct = (fat_mass / weight_kg * 100.0) if weight_kg else 0.0
    return Composition(
        date=on,
        weight_kg=weight_kg,
        fat_mass_kg=fat_mass,
        lean_mass_kg=lean_mass,
        body_fat_pct=body_fat_pct,
        measured=False,
        anchor_scan_date=anchor.date,
        p_fat_used=p_fat,
        reasons=[
            Reason(
                code=ReasonCode.COMPOSITION_ESTIMATED,
                metric="body_composition",
                detail={"anchor_date": anchor.date.isoformat(), "p_fat": p_fat},
            )
        ],
    )


def composition_on(
    weight_kg: float | None,
    on: date,
    scans: Sequence[DexaScan],
    *,
    p_fat: float = DEFAULT_P_FAT,
) -> Composition | None:
    """Measured if a scan landed on this day, estimated if an anchor exists, else None.

    With no scan at all the Body screen shows weight and trend only -- inventing a body
    fat percentage from height and weight would be a guess dressed as a measurement.
    """
    if weight_kg is None:
        return None
    exact = next((s for s in scans if s.date == on), None)
    if exact is not None:
        return from_dexa(exact)
    anchor = latest_scan_before(scans, on)
    if anchor is None:
        return None
    return estimate(weight_kg, on, anchor, p_fat=p_fat)


def compare_scans(a: DexaScan, b: DexaScan) -> ScanComparison:
    """Chronological regardless of argument order."""
    first, second = sorted((a, b), key=lambda s: s.date)
    return ScanComparison(
        from_date=first.date,
        to_date=second.date,
        days_between=(second.date - first.date).days,
        weight_change_kg=second.total_mass_kg - first.total_mass_kg,
        fat_change_kg=second.fat_mass_kg - first.fat_mass_kg,
        lean_change_kg=second.lean_mass_kg - first.lean_mass_kg,
        body_fat_pct_change=second.body_fat_pct - first.body_fat_pct,
    )


def solve_p_fat(a: DexaScan, b: DexaScan) -> float | None:
    """Your actual fat/lean partitioning ratio, from two scans.

    This is the point of section 6.2: the literature default gets retired and replaced by
    a personal constant. Returns None when the two scans show no weight change, since the
    ratio is then undefined rather than zero.
    """
    first, second = sorted((a, b), key=lambda s: s.date)
    weight_delta = second.total_mass_kg - first.total_mass_kg
    if abs(weight_delta) < 0.5:
        return None
    fat_delta = second.fat_mass_kg - first.fat_mass_kg
    return fat_delta / weight_delta
