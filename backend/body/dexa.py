"""DEXA scans: the only direct measurement of body composition this project gets.

Why a scan is treated differently from everything else
------------------------------------------------------
A scale tells you what you weigh. It cannot tell you what the weight is made of, and on
a cut that is the only question that matters: losing 3 kg is a success if it is fat and
a problem if a third of it is muscle. Nothing on the wrist can answer it either --
Garmin has no body composition input on a Forerunner 165.

A DEXA scan measures it directly. So a scan is an ANCHOR: a date where the answer is
known rather than modelled. Everything between two scans is an estimate, and the next
scan is what tells you how good the estimate was.

Where the numbers come from
---------------------------
`private/dexa-scans.yaml`, which is gitignored along with the rest of that folder. The
report itself is a medical document with your name, your patient id and the clinic's
details on it; none of that belongs in a code repository, and none of it is needed here.
Only the measurements are copied across.

Units
-----
DEXA reports in North America come in pounds. Everything in this project is metric, so
the conversion happens once, here, on the way in -- the same rule the Garmin normalizer
follows with seconds and grams. Nothing downstream ever has to ask which unit it holds.
"""

from __future__ import annotations

import dataclasses
import datetime
from pathlib import Path
from typing import Any

import yaml

from backend import paths

#: Where the scans live. Inside `private/`, which is gitignored entirely.
DEFAULT_SCANS_PATH = paths.PROJECT_ROOT / "private" / "dexa-scans.yaml"

#: One pound in kilograms. The exact international definition, not an approximation --
#: a scan is the most precise measurement in this project and it would be careless to
#: round its units on the way in.
KILOGRAMS_PER_POUND = 0.45359237


def pounds_to_kilograms(pounds: float | None) -> float | None:
    """Convert pounds to kilograms, passing None straight through."""
    if pounds is None:
        return None

    return pounds * KILOGRAMS_PER_POUND


@dataclasses.dataclass
class Region:
    """One region of the body, as the scan reports it.

    Regional numbers are worth keeping rather than just the total, because they answer
    the question a total cannot: if lean mass falls, was it everywhere, or is it the
    legs? Arms and legs are where training shows up first.
    """

    name: str
    fat_kilograms: float | None = None
    lean_kilograms: float | None = None
    total_kilograms: float | None = None
    fat_percent: float | None = None


@dataclasses.dataclass
class Scan:
    """One whole-body DEXA scan."""

    scan_date: datetime.date
    total_mass_kilograms: float | None = None
    fat_mass_kilograms: float | None = None

    #: Lean tissue PLUS bone mineral content, which is how the report groups them. It is
    #: named for what it contains rather than being called "lean mass", because lean
    #: mass elsewhere usually excludes bone and the two differ by a couple of kilograms.
    lean_and_bone_kilograms: float | None = None

    fat_percent: float | None = None
    visceral_fat_grams: float | None = None
    bone_mineral_density: float | None = None
    bmd_t_score: float | None = None
    bmd_z_score: float | None = None
    provider: str | None = None
    regions: list[Region] = dataclasses.field(default_factory=list)

    def fat_free_mass_kilograms(self) -> float | None:
        """DERIVED: everything that is not fat.

        Computed from the total rather than read, so it always agrees with the two
        numbers it sits beside.
        """
        if self.total_mass_kilograms is None:
            return None

        if self.fat_mass_kilograms is None:
            return None

        return self.total_mass_kilograms - self.fat_mass_kilograms

    def check_adds_up(self) -> str | None:
        """Confirm fat + lean + bone equals the total, or say by how much it does not.

        The report's own figures should reconcile. If they do not, something was typed
        wrong on the way into the YAML, and it is far better to hear that now than to
        anchor months of estimates to a mistyped number.
        """
        if self.total_mass_kilograms is None:
            return None

        if self.fat_mass_kilograms is None or self.lean_and_bone_kilograms is None:
            return None

        parts = self.fat_mass_kilograms + self.lean_and_bone_kilograms
        difference = abs(parts - self.total_mass_kilograms)

        # A tenth of a kilogram covers the rounding in a report quoted to two decimal
        # places in pounds. Anything larger is a typo.
        if difference > 0.1:
            return (
                f"fat ({self.fat_mass_kilograms:.2f}) + lean and bone"
                f" ({self.lean_and_bone_kilograms:.2f}) ="
                f" {parts:.2f} kg, but the total says"
                f" {self.total_mass_kilograms:.2f} kg"
            )

        return None


def read_region(entry: dict[str, Any]) -> Region:
    """Turn one region from the YAML into a Region, converting pounds as it goes."""
    return Region(
        name=entry["name"],
        fat_kilograms=pounds_to_kilograms(entry.get("fat_lb")),
        lean_kilograms=pounds_to_kilograms(entry.get("lean_lb")),
        total_kilograms=pounds_to_kilograms(entry.get("total_lb")),
        fat_percent=entry.get("fat_percent"),
    )


def read_scan(entry: dict[str, Any]) -> Scan:
    """Turn one scan from the YAML into a Scan."""
    scan_date = entry["scan_date"]

    if isinstance(scan_date, str):
        scan_date = datetime.date.fromisoformat(scan_date)

    regions = []

    for one_region in entry.get("regions", []):
        regions.append(read_region(one_region))

    return Scan(
        scan_date=scan_date,
        total_mass_kilograms=pounds_to_kilograms(entry.get("total_lb")),
        fat_mass_kilograms=pounds_to_kilograms(entry.get("fat_lb")),
        lean_and_bone_kilograms=pounds_to_kilograms(entry.get("lean_lb")),
        fat_percent=entry.get("fat_percent"),
        visceral_fat_grams=entry.get("visceral_fat_g"),
        bone_mineral_density=entry.get("bmd"),
        bmd_t_score=entry.get("bmd_t_score"),
        bmd_z_score=entry.get("bmd_z_score"),
        provider=entry.get("provider"),
        regions=regions,
    )


def load_scans(scans_path: str | Path = DEFAULT_SCANS_PATH) -> list[Scan]:
    """Read every scan, oldest first.

    An absent file is not an error. Most people have no DEXA scan, and the rest of the
    project has to work exactly the same without one.
    """
    path_to_read = Path(scans_path)

    if not path_to_read.exists():
        return []

    with open(path_to_read, encoding="utf-8") as open_file:
        contents = yaml.safe_load(open_file)

    if not contents:
        return []

    scans = []

    for entry in contents.get("scans", []):
        scans.append(read_scan(entry))

    scans.sort(key=lambda one_scan: one_scan.scan_date)

    return scans


def scan_nearest_to(scans: list[Scan], day: datetime.date) -> Scan | None:
    """The most recent scan on or before a given day, or None if there is not one.

    On or BEFORE, deliberately. A scan taken next month is not evidence about today: it
    has not happened yet from the point of view of the day being looked at, and using it
    would let the future rewrite the past.
    """
    applicable = []

    for one_scan in scans:
        if one_scan.scan_date <= day:
            applicable.append(one_scan)

    if not applicable:
        return None

    return applicable[-1]
