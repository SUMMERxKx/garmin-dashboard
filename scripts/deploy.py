"""One command to put the current code online.

    .venv/bin/python -m scripts.deploy

Three steps that have to happen in order and are easy to half-do by hand:

  1. build the dashboard        `npm run build` in dashboard/
  2. build the Lambda package   Linux wheels plus the backend, into build/api/
  3. deploy                     `cdk deploy`, with the origin secret in the environment

Doing them separately is how you end up deploying a Lambda that matches the code and a
website that does not, or the reverse -- and the symptom is a dashboard that looks right
and returns yesterday's behaviour.

The origin secret
-----------------
CloudFront and the API function share a secret so the function can refuse anything that
did not come through the distribution. It lives in `docs/personal/`, which is gitignored,
and is read from there and exported for the deploy. It never appears in this repository
and never has to be typed, which means it never lands in shell history either.

Node
----
The CDK does not support Node 25, and the failure is confusing rather than obvious. This
checks the version and stops with a clear instruction rather than letting cdk produce a
warning nobody reads.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

from backend import paths
from scripts import build_lambda

#: Where the origin secret is written down. Gitignored, along with all of docs/.
SECRETS_FILE = paths.PROJECT_ROOT / "docs" / "personal" / "dashboard-credentials.md"

#: The variable the stack reads at synth time.
ORIGIN_SECRET_VARIABLE = "GARMIN_ORIGIN_SECRET"

#: Node versions the CDK supports. 25 is not one of them.
SUPPORTED_NODE_MAJORS = [20, 22, 24]


def read_origin_secret() -> str:
    """Pull the shared secret out of the local secrets file."""
    if not SECRETS_FILE.exists():
        raise SystemExit(
            f"{SECRETS_FILE} is missing.\n"
            f"It holds {ORIGIN_SECRET_VARIABLE}, the secret CloudFront sends to the API."
        )

    found = re.search(rf"{ORIGIN_SECRET_VARIABLE}=(\S+)", SECRETS_FILE.read_text())

    if found is None:
        raise SystemExit(f"No {ORIGIN_SECRET_VARIABLE}=... line in {SECRETS_FILE}.")

    return found.group(1)


def check_node_version() -> None:
    """Stop early if the CDK is about to run on a Node it does not support."""
    result = subprocess.run(
        ["node", "--version"], capture_output=True, text=True, check=False
    )

    version = result.stdout.strip()
    found = re.match(r"v(\d+)", version)

    if found is None:
        raise SystemExit("Could not read the Node version. Is Node installed?")

    major = int(found.group(1))

    if major not in SUPPORTED_NODE_MAJORS:
        raise SystemExit(
            f"Node {version} is not supported by the CDK.\n"
            "Run `nvm use 22` in this terminal, then try again."
        )

    print(f"  node {version}")


def build_the_dashboard() -> None:
    """`npm run build`, which writes dashboard/dist."""
    print()
    print("Building the dashboard…")

    subprocess.run(
        ["npm", "run", "build"],
        cwd=paths.PROJECT_ROOT / "dashboard",
        check=True,
    )


def deploy(origin_secret: str) -> None:
    """`cdk deploy`, with the secret in the environment the stack reads."""
    print()
    print("Deploying…")

    environment = dict(os.environ)
    environment[ORIGIN_SECRET_VARIABLE] = origin_secret

    subprocess.run(
        ["cdk", "deploy", "--all", "--require-approval", "never"],
        cwd=paths.PROJECT_ROOT / "infra",
        env=environment,
        check=True,
    )


def main() -> int:
    """Entry point. 0 if everything deployed."""
    print()
    print("Checks:")
    check_node_version()

    origin_secret = read_origin_secret()
    print(f"  origin secret read from {SECRETS_FILE.name}")

    build_the_dashboard()

    print()
    build_lambda.main()

    deploy(origin_secret)

    print()
    print("Deployed.")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
