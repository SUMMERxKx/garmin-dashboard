#!/usr/bin/env python3
"""Phase 0: discover exactly what the Forerunner 165 exposes through garminconnect.

Run this BEFORE any normalization code exists. Its whole job is to replace assumptions
about response shapes with saved evidence.

    python scripts/garmin_probe.py                    # yesterday
    python scripts/garmin_probe.py --date 2026-09-01
    python scripts/garmin_probe.py --days 3           # three days back from yesterday

What it writes
--------------
  fixtures/raw/garmin/dt=YYYY-MM-DD/<endpoint>.json   full raw responses -- GITIGNORED,
                                                      these contain real health data
  docs/fr165-fields.md                                structure-only report -- field
                                                      names and types, NO values

Privacy: the report records field names, types and presence, but never a health value,
so it is safe to keep next to real data. The raw fixtures stay local.

Security: the password is read with getpass, never echoed, never written to disk and
never logged. Only the token bundle is saved, into ./.garmin_tokens (gitignored, mode
0700). That bundle is the only thing the cloud would ever hold.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from datetime import timedelta
from getpass import getpass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Where things live on disk
# ---------------------------------------------------------------------------
#
# This file lives at:  <project root>/scripts/garmin_probe.py
# So the project root is the parent of the folder this file sits in.
#
#   Path(__file__)  ->  ".../Garmin Dashboard/scripts/garmin_probe.py"
#   .resolve()      ->  turns it into a full absolute path, following any symlinks
#   .parent         ->  ".../Garmin Dashboard/scripts"
#   .parent.parent  ->  ".../Garmin Dashboard"          <- what we want

THIS_FILE = Path(__file__).resolve()
SCRIPTS_DIRECTORY = THIS_FILE.parent
PROJECT_ROOT = SCRIPTS_DIRECTORY.parent

# This script lives in "scripts/" but needs to import from "backend/". Python only
# searches the folder of the script being run, so "import backend.providers..." would
# fail. Adding the project root to the front of the import search path fixes that.
sys.path.insert(0, str(PROJECT_ROOT))

# These imports have to come after the sys.path line above. The linter rule that
# objects to this (E402) is switched off for this file in pyproject.toml.
from backend.providers import garmin
from backend.providers import introspect

# pathlib lets you join paths with "/" instead of gluing strings together:
#
#   PROJECT_ROOT / "fixtures" / "raw"
#
# means the same thing as PROJECT_ROOT + "/fixtures/raw", except pathlib uses the right
# separator for the operating system, so this also works on Windows.

TOKEN_DIRECTORY = PROJECT_ROOT / ".garmin_tokens"
FIXTURE_DIRECTORY = PROJECT_ROOT / "fixtures" / "raw" / "garmin"
REPORT_FILE = PROJECT_ROOT / "docs" / "fr165-fields.md"

# How much text to show in various places, so the numbers are not scattered through
# the code as unexplained "magic numbers".
MAX_ERROR_CHARS_IN_CONSOLE = 70
MAX_ERROR_CHARS_IN_REPORT = 50
MAX_PATHS_PER_METRIC = 3
MAX_FIELDS_PER_ENDPOINT = 60
ENDPOINT_NAME_COLUMN_WIDTH = 20


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def path_for_display(path: Path) -> str:
    """Shorten a path for printing, e.g. "fixtures/raw/garmin/dt=2026-09-02".

    We would rather print a short path relative to the project than a long absolute one.
    `relative_to` raises a ValueError if the path is not actually inside the project (for
    example if someone points the report somewhere else entirely), so we catch that and
    fall back to the full path instead of crashing.
    """
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def is_empty_response(payload: Any) -> bool:
    """True when the endpoint answered but gave us nothing usable.

    Note this is NOT the same as the request failing. Some Forerunner 165 endpoints
    return a perfectly valid HTTP 200 response whose body is an empty list, or a full
    object where every single value is null. That is why the report separates "failed"
    from "empty": a monitoring system watching only for HTTP errors would call this
    healthy while the dashboard had no data to show.
    """
    if payload is None:
        return True
    if isinstance(payload, (list, dict)) and len(payload) == 0:
        return True
    return False


def count_top_level_items(payload: Any) -> int:
    """How many keys (for an object) or entries (for a list) came back."""
    if isinstance(payload, (list, dict)):
        return len(payload)
    return 1


def describe_endpoint_result(endpoint_name: str, payload: Any, errors: dict[str, str]) -> str:
    """One short word for what happened: "failed", "empty" or "ok"."""
    if endpoint_name in errors:
        short_error = errors[endpoint_name][:MAX_ERROR_CHARS_IN_REPORT]
        return f"failed: {short_error}"
    if is_empty_response(payload):
        return "empty"
    return "ok"


# ---------------------------------------------------------------------------
# Step 1: log in
# ---------------------------------------------------------------------------


def ask_for_mfa_code() -> str:
    """Called by the Garmin client when the account has two-factor authentication on.

    This is why the whole token-bundle design exists: answering this prompt needs a
    human, and a Lambda function in the cloud has no human to ask. So we log in here
    once, save the token bundle, and the cloud only ever refreshes that bundle.
    """
    return input("  MFA code from your authenticator/email: ").strip()


def connect_to_garmin(email_from_command_line: str | None) -> Any:
    """Log in, preferring the saved token bundle over asking for a password.

    `Garmin.login(tokenstore)` does the whole dance internally:
      1. loads a saved token bundle from that folder, if one is there
      2. refreshes the access token when it is close to expiring
      3. only if there is no usable bundle, logs in with email + password
         (calling `ask_for_mfa_code` if two-factor is enabled)
      4. saves the resulting bundle back to the folder

    The important consequence: once the bundle exists, no password is needed at all.
    That is exactly what the ingest Lambda will rely on -- it holds tokens, never a
    credential -- so the Garmin password never has to exist in the cloud.
    """
    from garminconnect import Garmin

    # mode=0o700 means "only the owner of this folder can read, write or open it".
    TOKEN_DIRECTORY.mkdir(mode=0o700, exist_ok=True)

    # `iterdir()` lists the folder's contents. `any(...)` is True if there is at least
    # one thing in there, which means a previous run already saved a token bundle.
    a_token_bundle_already_exists = any(TOKEN_DIRECTORY.iterdir())

    # These start as None. If a bundle exists we deliberately leave them as None, so
    # the library uses the tokens and never sees a credential.
    email: str | None = None
    password: str | None = None

    if a_token_bundle_already_exists:
        print(f"  using saved token bundle in {TOKEN_DIRECTORY.name}/ (no password needed)")
    else:
        print("  no token bundle yet -- one interactive login will create it")

        # Try the command-line flag first, then an environment variable, then just ask.
        email = email_from_command_line
        if not email:
            email = os.environ.get("GARMIN_EMAIL")
        if not email:
            email = input("  Garmin email: ").strip()

        # getpass reads the password without printing it to the screen.
        password = os.environ.get("GARMIN_PASSWORD")
        if not password:
            password = getpass("  Garmin password (not echoed, not stored): ")

    client = Garmin(email=email, password=password, prompt_mfa=ask_for_mfa_code)
    client.login(str(TOKEN_DIRECTORY))

    # Drop our reference to the plaintext password as soon as login is done. The library
    # clears its own copy too. This does not make anything cryptographically safe, but
    # there is no reason to keep a password sitting in memory for the rest of the run.
    del password

    if not a_token_bundle_already_exists:
        print(f"  authenticated; token bundle written to {TOKEN_DIRECTORY.name}/")
        print("  future runs (and the Lambda) need only this bundle, never the password")

    return client


# ---------------------------------------------------------------------------
# Step 2: fetch one day and save every response
# ---------------------------------------------------------------------------


def probe_one_day(
    provider: garmin.GarminProvider,
    day: date,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Fetch every endpoint for one day, save each response, and print what happened.

    Returns two dictionaries:
      payloads -- endpoint name -> whatever the endpoint returned
      errors   -- endpoint name -> error message, for the endpoints that failed
    """
    print(f"\n== {day.isoformat()} ==")

    raw = provider.fetch_day(day)

    # One folder per day, named "dt=2026-09-02". The "dt=" prefix is a convention
    # ("Hive partitioning") that query tools understand, and it keeps the folders sorted.
    day_directory = FIXTURE_DIRECTORY / f"dt={day.isoformat()}"
    day_directory.mkdir(parents=True, exist_ok=True)

    for endpoint in garmin.ENDPOINTS:
        name = endpoint.name

        # Case 1: the call itself failed. Print it and move on -- one broken endpoint
        # must not cost us the other sixteen.
        if name in raw.errors:
            short_error = raw.errors[name][:MAX_ERROR_CHARS_IN_CONSOLE]
            padded_name = name.ljust(ENDPOINT_NAME_COLUMN_WIDTH)
            print(f"  [tier {endpoint.tier}] {padded_name} FAILED  {short_error}")
            continue

        payload = raw.payloads.get(name)
        padded_name = name.ljust(ENDPOINT_NAME_COLUMN_WIDTH)

        # Case 2: the call worked but there was nothing in it.
        if is_empty_response(payload):
            print(f"  [tier {endpoint.tier}] {padded_name} EMPTY   (no data for this day)")

        # Case 3: we got something.
        else:
            item_count = count_top_level_items(payload)
            print(f"  [tier {endpoint.tier}] {padded_name} ok      {item_count} top-level item(s)")

        # Save the response either way, including when it was empty -- knowing that an
        # endpoint reliably returns nothing is itself a Phase 0 finding.
        #
        # `default=str` tells json.dumps to fall back to str() for anything it cannot
        # serialize on its own (a date, for example) instead of raising.
        response_file = day_directory / f"{name}.json"
        response_file.write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )

    print(f"  raw responses -> {path_for_display(day_directory)}/")

    return dict(raw.payloads), dict(raw.errors)


# ---------------------------------------------------------------------------
# Step 3: write the structure-only report
# ---------------------------------------------------------------------------


def build_report_header(days: list[date]) -> list[str]:
    """The title and the privacy note at the top of the report."""
    probed_dates = ", ".join(day.isoformat() for day in days)
    return [
        "# Forerunner 165 field availability",
        "",
        "Generated by `scripts/garmin_probe.py` (Phase 0).",
        "",
        f"Probed dates: {probed_dates}",
        "",
        "**Structure only — field names, types and presence. No health values appear in",
        "this file, so it is safe to commit. The raw responses stay local in",
        "`fixtures/raw/`.**",
        "",
    ]


def build_metric_availability_section(metric_locations: dict[str, list[str]]) -> list[str]:
    """A table of "the metric I care about" -> "where it actually lives in the JSON"."""
    lines = [
        "## Metric availability",
        "",
        "| Metric | Found at |",
        "|---|---|",
    ]

    for metric_name in introspect.METRIC_PATTERNS:
        found_paths = metric_locations.get(metric_name)

        if not found_paths:
            where = "**not found**"
        else:
            # Show the first few places we found it. "<br>" is a line break in a
            # markdown table cell, which cannot contain a real newline.
            where = "<br>".join(found_paths[:MAX_PATHS_PER_METRIC])

        lines.append(f"| {metric_name} | {where} |")

    lines.append("")
    return lines


def build_endpoint_outcome_section(
    payloads: dict[str, Any],
    errors: dict[str, str],
) -> list[str]:
    """A table of which endpoints worked, which were empty and which failed."""
    lines = [
        "## Endpoint outcomes",
        "",
        "| Endpoint | Tier | Feeds | Result |",
        "|---|---|---|---|",
    ]

    for endpoint in garmin.ENDPOINTS:
        payload = payloads.get(endpoint.name)
        result = describe_endpoint_result(endpoint.name, payload, errors)
        lines.append(f"| `{endpoint.name}` | {endpoint.tier} | {endpoint.feeds} | {result} |")

    lines.append("")
    return lines


def build_response_structure_section(
    payloads: dict[str, Any],
    errors: dict[str, str],
) -> list[str]:
    """The field-name-and-type tree for every endpoint.

    This is the part the normalizer gets written from: it shows the exact path to every
    field, which is how we found that the numeric sleep score lives at
    `dailySleepDTO.sleepScores.overall.value` rather than next to the similarly-named
    text fields.
    """
    lines = ["## Response structure", ""]

    for endpoint in garmin.ENDPOINTS:
        lines.append(f"### `{endpoint.name}`")
        lines.append("")

        if endpoint.note:
            lines.append(f"_{endpoint.note}_")
            lines.append("")

        if endpoint.name in errors:
            lines.append(f"Failed: `{errors[endpoint.name]}`")
            lines.append("")
            continue

        payload = payloads.get(endpoint.name)
        fields = introspect.summarize(payload, max_depth=3)

        if not fields:
            lines.append("Empty response.")
            lines.append("")
            continue

        lines.append("```")
        for field_path, type_name in fields[:MAX_FIELDS_PER_ENDPOINT]:
            lines.append(f"{field_path}: {type_name}")

        number_of_extra_fields = len(fields) - MAX_FIELDS_PER_ENDPOINT
        if number_of_extra_fields > 0:
            lines.append(f"... {number_of_extra_fields} more fields")

        lines.append("```")
        lines.append("")

    return lines


def write_report(payloads: dict[str, Any], errors: dict[str, str], days: list[date]) -> None:
    """Assemble the three report sections and save them to docs/fr165-fields.md."""
    metric_locations = introspect.find_metrics(payloads)

    lines: list[str] = []
    lines.extend(build_report_header(days))
    lines.extend(build_metric_availability_section(metric_locations))
    lines.extend(build_endpoint_outcome_section(payloads, errors))
    lines.extend(build_response_structure_section(payloads, errors))

    REPORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\nreport -> {path_for_display(REPORT_FILE)}")

    # The dashboard is designed to work on the tier-1 metrics alone, so if any of them
    # is missing that is the one thing worth shouting about.
    not_found = introspect.missing_tier_1(metric_locations)
    if not_found:
        print(f"\n!! tier-1 metrics not found: {', '.join(not_found)}")
        print("   Check the structure section -- they may be under names the patterns missed.")
    else:
        print("\nAll tier-1 metrics located. The Recovery and Energy screens are viable as designed.")


# ---------------------------------------------------------------------------
# Putting it together
# ---------------------------------------------------------------------------


def work_out_which_days_to_probe(date_argument: str | None, number_of_days: int) -> list[date]:
    """Turn the command-line arguments into a sorted list of dates.

    Default is yesterday, not today, because today's data is still incomplete -- the
    watch has not finished syncing and you have not finished the day.
    """
    if date_argument:
        most_recent_day = date.fromisoformat(date_argument)
    else:
        most_recent_day = date.today() - timedelta(days=1)

    days = []
    for days_back in range(number_of_days):
        days.append(most_recent_day - timedelta(days=days_back))

    return sorted(days)


def merge_payloads_for_report(
    merged: dict[str, Any],
    payloads_from_one_day: dict[str, Any],
) -> None:
    """Keep the richest example of each endpoint's response, across all probed days.

    The report only needs one good example per endpoint to show its structure. A day
    with no workout gives an empty `activities` list, which tells us nothing about the
    shape of an activity -- so a later day that does have one should replace it.

    This modifies `merged` in place.
    """
    for endpoint_name, payload in payloads_from_one_day.items():
        if is_empty_response(payload):
            continue

        we_have_nothing_yet = endpoint_name not in merged
        what_we_have_is_empty = not we_have_nothing_yet and is_empty_response(merged[endpoint_name])

        if we_have_nothing_yet or what_we_have_is_empty:
            merged[endpoint_name] = payload


def main() -> int:
    """Entry point. Returns 0 on success, 1 on failure (the usual shell convention)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="YYYY-MM-DD (default: yesterday)")
    parser.add_argument("--days", type=int, default=1, help="how many days back to probe")
    parser.add_argument("--email", help="Garmin account email (or set GARMIN_EMAIL)")
    arguments = parser.parse_args()

    days_to_probe = work_out_which_days_to_probe(arguments.date, arguments.days)

    print("Phase 0 probe: discovering what the Forerunner 165 actually returns.\n")

    try:
        client = connect_to_garmin(arguments.email)
    except Exception as error:
        # Deliberately broad: any login problem should print a useful message and exit
        # cleanly, rather than dumping a stack trace at someone typing a password.
        print(f"\nLogin failed: {type(error).__name__}: {error}")
        print("If MFA is enabled, run this interactively so it can prompt for the code.")
        return 1

    provider = garmin.GarminProvider(client)

    merged_payloads: dict[str, Any] = {}
    all_errors: dict[str, str] = {}

    for day in days_to_probe:
        payloads, errors = probe_one_day(provider, day)

        merge_payloads_for_report(merged_payloads, payloads)

        # Only record an error if we never managed to get that endpoint on any day.
        for endpoint_name, message in errors.items():
            if endpoint_name not in merged_payloads:
                all_errors[endpoint_name] = message

    write_report(merged_payloads, all_errors, days_to_probe)

    print("\nNext: review docs/fr165-fields.md, then the normalizer gets written against")
    print("these fixtures rather than against assumptions.")
    return 0


if __name__ == "__main__":
    # SystemExit with a number is how a Python script sets its shell exit code.
    raise SystemExit(main())
