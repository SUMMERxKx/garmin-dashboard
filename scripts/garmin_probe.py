#!/usr/bin/env python3
"""Phase 0: discover exactly what the Forerunner 165 exposes through garminconnect.

Run this BEFORE any normalization code exists. Its whole job is to replace assumptions
about response shapes with saved evidence.

    python scripts/garmin_probe.py                    # yesterday
    python scripts/garmin_probe.py --date 2026-09-01
    python scripts/garmin_probe.py --days 3           # three days back from yesterday

Outputs
-------
  fixtures/raw/garmin/dt=YYYY-MM-DD/<endpoint>.json   full raw responses -- GITIGNORED,
                                                      these contain real health data
  docs/fr165-fields.md                                structure-only report -- committed,
                                                      field names and types, NO values

Privacy: the report deliberately records field names, types and presence but never a
health value, so it is safe in a public repo. The raw fixtures stay local.

Security: the password is read with getpass, never echoed, never written to disk and
never logged. Only the token bundle is persisted, into ./.garmin_tokens (gitignored,
mode 0700). That bundle is what the cloud would ever hold -- see PLAN.md section 7.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from getpass import getpass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.providers.garmin import ENDPOINTS, GarminProvider  # noqa: E402
from backend.providers.introspect import (  # noqa: E402
    METRIC_PATTERNS,
    find_metrics,
    missing_tier_1,
    summarize,
)

TOKEN_DIR = REPO / ".garmin_tokens"
FIXTURE_ROOT = REPO / "fixtures" / "raw" / "garmin"
REPORT = REPO / "docs" / "fr165-fields.md"


def _rel(path: Path) -> str:
    """Repo-relative when possible, absolute otherwise -- never raises on an odd path."""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)

def connect(email: str | None) -> Any:
    """Authenticate, preferring the saved token bundle.

    `Garmin.login(tokenstore)` does the whole dance itself: it loads the bundle if
    present, proactively refreshes an expiring token, falls back to a credential login
    (prompting for MFA) when there is no usable bundle, and persists the result.

    The important property for PLAN.md section 7: **once the bundle exists, no password
    is needed at all.** That is exactly the flow the ingest Lambda will use -- it holds
    tokens, never a credential. The library also clears the plaintext password from the
    object after a successful login.
    """
    from garminconnect import Garmin

    TOKEN_DIR.mkdir(mode=0o700, exist_ok=True)
    tokenstore = str(TOKEN_DIR)
    has_bundle = any(TOKEN_DIR.iterdir())

    email_arg: str | None = None
    password: str | None = None
    if has_bundle:
        print(f"  using saved token bundle in {TOKEN_DIR.name}/ (no password needed)")
    else:
        print("  no token bundle yet -- one interactive login will create it")
        email_arg = email or os.environ.get("GARMIN_EMAIL") or input("  Garmin email: ").strip()
        password = os.environ.get("GARMIN_PASSWORD") or getpass(
            "  Garmin password (not echoed, not stored): "
        )

    def prompt_mfa() -> str:
        return input("  MFA code from your authenticator/email: ").strip()

    client = Garmin(email=email_arg, password=password, prompt_mfa=prompt_mfa)
    client.login(tokenstore)
    del password

    if not has_bundle:
        print(f"  authenticated; token bundle written to {TOKEN_DIR.name}/")
        print("  future runs (and the Lambda) need only this bundle, never the password")
    return client


def probe_day(provider: GarminProvider, on: date) -> tuple[dict[str, Any], dict[str, str]]:
    print(f"\n== {on.isoformat()} ==")
    raw = provider.fetch_day(on)
    out_dir = FIXTURE_ROOT / f"dt={on.isoformat()}"
    out_dir.mkdir(parents=True, exist_ok=True)

    for endpoint in ENDPOINTS:
        name = endpoint.name
        if name in raw.errors:
            print(f"  [tier {endpoint.tier}] {name:<20} FAILED  {raw.errors[name][:70]}")
            continue
        payload = raw.payloads.get(name)
        if payload is None or (isinstance(payload, list | dict) and len(payload) == 0):
            print(f"  [tier {endpoint.tier}] {name:<20} EMPTY   (no data for this day)")
        else:
            size = len(payload) if isinstance(payload, list | dict) else 1
            print(f"  [tier {endpoint.tier}] {name:<20} ok      {size} top-level item(s)")
        (out_dir / f"{name}.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    print(f"  raw responses -> {_rel(out_dir)}/")
    return dict(raw.payloads), dict(raw.errors)


def write_report(all_payloads: dict[str, Any], errors: dict[str, str], days: list[date]) -> None:
    hits = find_metrics(all_payloads)
    lines: list[str] = [
        "# Forerunner 165 field availability",
        "",
        "Generated by `scripts/garmin_probe.py` (Phase 0).",
        "",
        f"Probed dates: {', '.join(d.isoformat() for d in days)}",
        "",
        "**Structure only — field names, types and presence. No health values appear in this",
        "file, so it is safe to commit. The raw responses stay local in `fixtures/raw/`.**",
        "",
        "## Metric availability",
        "",
        "| Metric | Found at |",
        "|---|---|",
    ]
    for metric in METRIC_PATTERNS:
        found = hits.get(metric)
        lines.append(f"| {metric} | {'<br>'.join(found[:3]) if found else '**not found**'} |")

    lines += ["", "## Endpoint outcomes", "", "| Endpoint | Tier | Feeds | Result |", "|---|---|---|---|"]
    for endpoint in ENDPOINTS:
        payload = all_payloads.get(endpoint.name)
        if endpoint.name in errors:
            result = f"failed: {errors[endpoint.name][:50]}"
        elif payload is None or (isinstance(payload, list | dict) and len(payload) == 0):
            result = "empty"
        else:
            result = "ok"
        lines.append(f"| `{endpoint.name}` | {endpoint.tier} | {endpoint.feeds} | {result} |")

    lines += ["", "## Response structure", ""]
    for endpoint in ENDPOINTS:
        payload = all_payloads.get(endpoint.name)
        lines += [f"### `{endpoint.name}`", ""]
        if endpoint.note:
            lines += [f"_{endpoint.note}_", ""]
        if endpoint.name in errors:
            lines += [f"Failed: `{errors[endpoint.name]}`", ""]
            continue
        fields = summarize(payload, max_depth=3)
        if not fields:
            lines += ["Empty response.", ""]
            continue
        lines += ["```", *[f"{path}: {kind}" for path, kind in fields[:60]]]
        if len(fields) > 60:
            lines.append(f"... {len(fields) - 60} more fields")
        lines += ["```", ""]

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nreport -> {_rel(REPORT)}")

    missing_tier1 = missing_tier_1(hits)
    if missing_tier1:
        print(f"\n!! tier-1 metrics not found: {', '.join(missing_tier1)}")
        print("   Check the structure section -- they may be under names the patterns missed.")
    else:
        print("\nAll tier-1 metrics located. The Recovery and Energy screens are viable as designed.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="YYYY-MM-DD (default: yesterday)")
    parser.add_argument("--days", type=int, default=1, help="how many days back to probe")
    parser.add_argument("--email", help="Garmin account email (or set GARMIN_EMAIL)")
    args = parser.parse_args()

    end = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1)
    days = [end - timedelta(days=i) for i in range(args.days)]

    print("Phase 0 probe: discovering what the Forerunner 165 actually returns.\n")
    try:
        client = connect(args.email)
    except Exception as exc:
        print(f"\nLogin failed: {type(exc).__name__}: {exc}")
        print("If MFA is enabled, run this interactively so it can prompt for the code.")
        return 1

    provider = GarminProvider(client)
    merged: dict[str, Any] = {}
    all_errors: dict[str, str] = {}
    for day in sorted(days):
        payloads, errors = probe_day(provider, day)
        for name, payload in payloads.items():
            if payload and (name not in merged or not merged[name]):
                merged[name] = payload   # keep the richest day's shape for the report
        all_errors.update({k: v for k, v in errors.items() if k not in merged})

    write_report(merged, all_errors, sorted(days))
    print("\nNext: review docs/fr165-fields.md, then the normalizer gets written against")
    print("these fixtures rather than against assumptions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
