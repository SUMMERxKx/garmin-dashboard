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

#: The variables the stack reads at synth time, and the lines they are stored under in
#: the secrets file.
ORIGIN_SECRET_VARIABLE = "GARMIN_ORIGIN_SECRET"
SESSION_SECRET_VARIABLE = "GARMIN_SESSION_SECRET"

#: Where the session signing secret has to end up as well as in the Lambda: the edge
#: verifies cookies with it. Matches `infra/stacks/app_stack.py`.
SESSION_SECRET_KEY = "session-secret"

#: Node versions the CDK supports. 25 is not one of them.
SUPPORTED_NODE_MAJORS = [20, 22, 24]


def read_secret(variable_name: str) -> str:
    """Pull one secret out of the local secrets file, creating it if it is not there yet.

    Generating a missing secret rather than failing means a fresh clone can deploy, and
    keeping it in the file rather than regenerating each time means a deploy does not sign
    everybody out.
    """
    if not SECRETS_FILE.exists():
        SECRETS_FILE.parent.mkdir(parents=True, exist_ok=True)
        SECRETS_FILE.write_text("# Dashboard secrets. Gitignored.\n")

    text = SECRETS_FILE.read_text()
    found = re.search(rf"{variable_name}=(\S+)", text)

    if found is not None:
        return found.group(1)

    from backend.api import auth

    made = auth.random_secret()
    SECRETS_FILE.write_text(text.rstrip("\n") + f"\n\n    {variable_name}={made}\n")
    print(f"  generated a new {variable_name} and saved it to {SECRETS_FILE.name}")

    return made


def ensure_login_password() -> None:
    """Make sure there is a password in Parameter Store, without ever overwriting one.

    The password is the value meant to be changed by hand in the AWS console, so this
    only ever creates it. If one is already there it is left completely alone -- which is
    what lets you change it there and redeploy without losing the change.
    """
    import boto3

    from backend.api import auth

    client = boto3.client("ssm")

    try:
        client.get_parameter(Name=auth.PASSWORD_PARAMETER_NAME)
        print("  login password already set (left untouched)")
        return
    except client.exceptions.ParameterNotFound:
        pass

    chosen = auth.random_password()

    client.put_parameter(
        Name=auth.PASSWORD_PARAMETER_NAME,
        Value=chosen,
        Type="SecureString",
        Description="The dashboard login password. Change it here; no deploy needed.",
    )

    text = SECRETS_FILE.read_text().rstrip("\n")
    SECRETS_FILE.write_text(
        text + f"\n\n## Login password\n\n    Password: {chosen}\n\n"
        f"Change it in the AWS console: Systems Manager -> Parameter Store ->\n"
        f"`{auth.PASSWORD_PARAMETER_NAME}`. It takes effect within a minute, no deploy.\n"
    )

    print(f"  created the login password at {auth.PASSWORD_PARAMETER_NAME}")
    print(f"  written down in {SECRETS_FILE.name}")


def write_session_secret_to_the_edge(session_secret: str) -> None:
    """Put the signing secret in the KeyValueStore the edge function reads.

    Done after the deploy rather than in the stack, so the value never lands in a
    CloudFormation template. Needs `botocore[crt]`: the KeyValueStore API is signed with
    SigV4a, which plain botocore cannot do, and the failure without it looks like a DNS
    problem rather than a missing dependency.
    """
    import boto3

    outputs = subprocess.run(
        [
            "aws", "cloudformation", "describe-stacks",
            "--stack-name", "HealthDashboardApp",
            "--query", "Stacks[0].Outputs[?OutputKey=='CredentialStoreArn'].OutputValue",
            "--output", "text",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    store_arn = outputs.stdout.strip()

    if store_arn == "" or store_arn == "None":
        raise SystemExit("Could not find the KeyValueStore ARN in the stack outputs.")

    client = boto3.client("cloudfront-keyvaluestore", region_name="us-east-1")
    etag = client.describe_key_value_store(KvsARN=store_arn)["ETag"]

    client.put_key(
        KvsARN=store_arn,
        Key=SESSION_SECRET_KEY,
        Value=session_secret,
        IfMatch=etag,
    )

    print("  session signing secret written to the edge")


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


def deploy(origin_secret: str, session_secret: str) -> None:
    """`cdk deploy`, with the secrets in the environment the stack reads."""
    print()
    print("Deploying…")

    environment = dict(os.environ)
    environment[ORIGIN_SECRET_VARIABLE] = origin_secret
    environment[SESSION_SECRET_VARIABLE] = session_secret

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

    origin_secret = read_secret(ORIGIN_SECRET_VARIABLE)
    session_secret = read_secret(SESSION_SECRET_VARIABLE)
    print(f"  secrets read from {SECRETS_FILE.name}")

    build_the_dashboard()

    print()
    build_lambda.main()

    deploy(origin_secret, session_secret)

    print()
    print("Fitting the lock…")
    write_session_secret_to_the_edge(session_secret)
    ensure_login_password()

    print()
    print("Deployed.")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
