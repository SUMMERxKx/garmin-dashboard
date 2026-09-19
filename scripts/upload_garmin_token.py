"""Copy the Garmin token bundle from this laptop into AWS, so the fetcher can log in.

    .venv/bin/python -m scripts.upload_garmin_token

Why this exists at all
----------------------
Logging in to Garmin needs an email, a password and a two-factor code, which needs a
human. The token bundle that login produces needs none of those, and `garminconnect`
refreshes it by itself as long as it keeps being used.

So the password never goes to AWS. You log in once here -- which you already have -- and
only the resulting bundle travels. It goes into Parameter Store as a `SecureString`,
which is encrypted at rest and free, and which the fetcher function is given permission to
read and write.

When to run it again
--------------------
Only if the scheduled fetch starts failing every day. That means Garmin has invalidated
the bundle and wants a real login, so: run any fetch command here to refresh it
interactively, then run this again.
"""

from __future__ import annotations

import json
import sys

import boto3

from backend.garmin import fetch_lambda
from backend.garmin import login


def collect_the_bundle() -> dict[str, str]:
    """Read every file in the local token folder."""
    if not login.a_saved_token_bundle_exists():
        raise SystemExit(
            f"No token bundle in {login.TOKEN_DIRECTORY}.\n"
            "Run a fetch first so one gets created:\n"
            "    .venv/bin/python -m backend.garmin.run_fetch --days 1"
        )

    bundle = {}

    for one_file in sorted(login.TOKEN_DIRECTORY.iterdir()):
        if one_file.is_file():
            bundle[one_file.name] = one_file.read_text(encoding="utf-8")

    return bundle


def main() -> int:
    """Entry point. 0 if the bundle was uploaded."""
    bundle = collect_the_bundle()

    print()
    print(f"Found {len(bundle)} file(s) in {login.TOKEN_DIRECTORY}:")

    for file_name, contents in bundle.items():
        print(f"  {file_name}  ({len(contents)} bytes)")

    # Check it actually works before sending it. Uploading a stale bundle would produce a
    # scheduled fetch that fails four times a day for a reason nobody would look for here.
    print()
    print("Checking it still works…")

    client = login.log_in()
    print(f"  logged in as {client.get_full_name()}")

    boto3.client("ssm").put_parameter(
        Name=fetch_lambda.TOKEN_PARAMETER_NAME,
        Value=json.dumps(bundle),
        Type="SecureString",
        Description="Garmin session tokens for the scheduled fetcher. No password here.",
        Overwrite=True,
    )

    print()
    print(f"Uploaded to {fetch_lambda.TOKEN_PARAMETER_NAME} (encrypted).")
    print("The scheduled fetcher can now log in without a password.")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
