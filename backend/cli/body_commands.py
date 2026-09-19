"""Body measurements: `weigh`, `weights` and `body`.

Two different kinds of fact live here and are deliberately never mixed. A morning
weigh-in is typed in by hand, at a consistent time, before eating -- which is exactly
what makes a run of them comparable. A DEXA scan is a measurement of what the weight is
made of, taken on one date, and it stays true for that date forever.
"""

from __future__ import annotations

import datetime

from backend.body import dexa
from backend.body import weight
from backend.cli import days
from backend.cli import formatting
from backend.store import day_store
from backend.store import open_store
from backend.store import weight_store

#: How far back to look for a previous weigh-in when sanity-checking a new one. Six
#: weeks is long enough to find one after a holiday, and short enough that the
#: comparison is still meaningful.
WEIGH_IN_LOOKBACK_DAYS = 42



def run_weigh(kilograms: float, date_text: str | None, force: bool) -> int:
    """Record a weigh-in.

    Defaults to today, like the other logging commands: you weigh yourself and then
    type it in.
    """
    day = days.work_out_day_for_logging(date_text)

    if day is None:
        return 1

    problem = weight.describe_problem(kilograms)

    if problem:
        print(problem)
        return 1

    open_database = open_store.open_store()

    # Compare against the most recent weigh-in BEFORE this day, which is what makes the
    # pounds-and-decimal-point check possible at all.
    earlier = weight_store.load_weighings_between(
        open_database,
        day - datetime.timedelta(days=WEIGH_IN_LOOKBACK_DAYS),
        day - datetime.timedelta(days=1),
    )

    previous = earlier[-1] if earlier else None
    surprising = weight.describe_jump(previous, kilograms)

    if surprising and not force:
        open_database.close()
        print()
        print(surprising)
        print()
        print("  If that is right, record it with --force.")
        print()
        return 1

    already_there = weight_store.load_weighing(open_database, day)

    one_weighing = weight.Weighing(
        day=day,
        kilograms=kilograms,
        # The clock is read here, at the edge, never inside the weight module.
        recorded_at=datetime.datetime.now(),
        source="manual",
    )

    weight_store.save_weighing(open_database, one_weighing)
    open_database.close()

    print()

    if already_there is not None:
        # A day holds one weigh-in, so this replaced something. Say so rather than
        # letting a number quietly disappear.
        print(f"  replaced {already_there.kilograms:g} kg with"
              f" {kilograms:g} kg for {day.isoformat()}")
    else:
        print(f"  recorded {kilograms:g} kg for {day.isoformat()}")

    if previous is not None:
        difference, days_between = weight.change_between(previous, one_weighing)
        print(f"  {difference:+.1f} kg since {previous.day.isoformat()}"
              f" ({days_between} day(s) ago)")

    print()

    return 0

def print_weights(weighings: list[weight.Weighing]) -> None:
    """Print recent weigh-ins, oldest first, with the change between them."""
    formatting.print_heading("WEIGH-INS")

    if not weighings:
        print("  none recorded")
        return

    previous = None

    for one_weighing in weighings:
        if previous is None:
            change = ""
        else:
            difference, days_between = weight.change_between(previous, one_weighing)
            change = f"   {difference:+.1f} kg over {days_between} day(s)"

        # Where a reading came from is printed when it was not typed in, because a
        # weight lifted from a DEXA report or from Garmin is a different kind of fact
        # from one you read off your own scale that morning.
        if one_weighing.source == "manual":
            origin = ""
        else:
            origin = f"   [{one_weighing.source}]"

        print(f"  {one_weighing.day.isoformat()}  "
              f"{one_weighing.kilograms:6.1f} kg{change}{origin}")

        previous = one_weighing

    if len(weighings) < 2:
        return

    difference, days_between = weight.change_between(weighings[0], weighings[-1])

    print()
    print(f"  net {difference:+.1f} kg over {days_between} day(s)")

    # You weigh every morning, so a gap is a missed morning rather than a rest day, and
    # it is worth seeing. Averages quietly get worse as coverage drops, and nothing else
    # on the screen would tell you that was happening.
    days_covered = days_between + 1
    missed = days_covered - len(weighings)

    if missed > 0:
        print(f"  {len(weighings)} weigh-ins across {days_covered} days"
              f" -- {missed} morning(s) missed")

    print()
    # Said plainly because it is the single easiest way to read too much into this
    # screen. Water, salt, glycogen and gut contents move weight by more than a real
    # week of fat loss does.
    print("  Day-to-day movement is mostly water and food weight. Only a run of")
    print("  weigh-ins across weeks says anything about fat.")

def run_weights(how_many_days: int) -> int:
    """Show recent weigh-ins."""
    last_day = datetime.date.today()
    first_day = last_day - datetime.timedelta(days=how_many_days - 1)

    open_database = open_store.open_store()
    weighings = weight_store.load_weighings_between(open_database, first_day, last_day)
    open_database.close()

    if not weighings:
        print()
        print(f"No weigh-ins in the last {how_many_days} days.")
        print("Record one:")
        print("    .venv/bin/python -m backend.cli.main weigh 80.0")
        print()
        return 1

    print_weights(weighings)
    print()

    return 0

def print_scan(one_scan: dexa.Scan) -> None:
    """Print one DEXA scan."""
    print()
    print(f"== DEXA, {one_scan.scan_date.strftime('%A %d %B %Y')} ==")

    if one_scan.provider:
        print(f"   {one_scan.provider}")

    formatting.print_heading("COMPOSITION")
    formatting.print_line("total mass", formatting.show_number(one_scan.total_mass_kilograms, "kg", 2))
    formatting.print_line("fat mass", formatting.show_number(one_scan.fat_mass_kilograms, "kg", 2))
    formatting.print_line("lean and bone", formatting.show_number(one_scan.lean_and_bone_kilograms, "kg", 2))
    formatting.print_line("body fat", formatting.show_number(one_scan.fat_percent, "%", 1))
    formatting.print_line("visceral fat", formatting.show_number(one_scan.visceral_fat_grams, "g"))

    formatting.print_heading("BONE")
    formatting.print_line("density", formatting.show_number(one_scan.bone_mineral_density, "g/cm2", 3))
    # Printed with what they mean. A T-score on its own is a number nobody can place.
    formatting.print_line("T-score", f"{formatting.show_number(one_scan.bmd_t_score, decimal_places=1)}"
                          f"   vs a young adult")
    formatting.print_line("Z-score", f"{formatting.show_number(one_scan.bmd_z_score, decimal_places=1)}"
                          f"   vs your own age group")

    if not one_scan.regions:
        return

    formatting.print_heading("BY REGION")
    print(build_region_row("region", "fat", "lean", "% fat"))
    print("  " + "-" * (len(build_region_row("", "", "", "")) - 2))

    for one_region in one_scan.regions:
        print(
            build_region_row(
                one_region.name,
                formatting.show_number(one_region.fat_kilograms, "kg", 2),
                formatting.show_number(one_region.lean_kilograms, "kg", 2),
                formatting.show_number(one_region.fat_percent, "%", 1),
            )
        )

def build_region_row(*cells: str) -> str:
    """Lay out one row of the regional table."""
    widths = [16, 10, 10, 8]

    laid_out = []

    for position, one_cell in enumerate(cells):
        if position == 0:
            laid_out.append(one_cell.ljust(widths[position]))
        else:
            laid_out.append(one_cell.rjust(widths[position]))

    return "  " + "  ".join(laid_out)

def print_change_since_scan(one_scan: dexa.Scan) -> None:
    """Compare the scan's total mass to the most recent weight we have.

    Deliberately stops at the weight change and refuses to split it into fat and lean.
    That split cannot be measured between scans -- it can only be modelled, and a
    modelled split printed beside measured numbers reads exactly as solid as they do.
    The second scan is what turns the estimate into a fact.
    """
    open_database = open_store.open_store()
    recent = day_store.load_snapshots_between(
        open_database,
        one_scan.scan_date,
        datetime.date.today(),
    )
    open_database.close()

    weighings = []

    for one_snapshot in recent:
        if one_snapshot.body.weight_kilograms is not None:
            weighings.append(one_snapshot)

    if not weighings:
        formatting.print_heading("SINCE THE SCAN")
        print("  no weigh-in recorded since the scan, so there is nothing to compare")
        return

    latest = weighings[-1]
    change = latest.body.weight_kilograms - one_scan.total_mass_kilograms
    days_between = (latest.day - one_scan.scan_date).days

    formatting.print_heading("SINCE THE SCAN")
    # "weight on 2026-09-12" is longer than the default label column, so this small
    # block sets its own width rather than silently running into its own numbers.
    width = len("weight on 0000-00-00") + 2

    formatting.print_line("scan total mass", formatting.show_number(one_scan.total_mass_kilograms, "kg", 2), width)
    formatting.print_line(
        f"weight on {latest.day.isoformat()}",
        formatting.show_number(latest.body.weight_kilograms, "kg", 1),
        width,
    )
    formatting.print_line("change", f"{change:+.2f} kg over {days_between} day(s)", width)
    print()
    print("  What that change is MADE OF cannot be measured between scans -- only")
    print("  modelled. The next scan is what turns the estimate into a fact.")

def run_body() -> int:
    """Show the most recent DEXA scan and what has happened since."""
    scans = dexa.load_scans()

    if not scans:
        print()
        print("No DEXA scans recorded.")
        print(f"Add one to {dexa.DEFAULT_SCANS_PATH}")
        print()
        return 1

    latest = scans[-1]

    problem = latest.check_adds_up()

    print_scan(latest)

    if latest.total_mass_kilograms is not None:
        print_change_since_scan(latest)

    if problem:
        print()
        print(f"  !! this scan does not reconcile: {problem}")
        print("     check the transcription against the report")
        print()
        return 1

    if len(scans) > 1:
        print()
        print(f"  ({len(scans)} scans recorded; showing the most recent)")

    print()

    return 0
