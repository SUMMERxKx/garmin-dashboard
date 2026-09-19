#!/usr/bin/env python3
"""The CDK application: the entry point describing what to build in AWS.

Run these from the `infra/` directory:

    cdk synth      turn this Python into a CloudFormation template and print it
    cdk diff       show what would change if deployed
    cdk deploy     make AWS match this description
    cdk destroy    tear the stack down (the bucket and table are KEPT -- see data_stack)

`cdk synth` needs no credentials and changes nothing, so it is the safe way to check this
file is valid before going anywhere near a real account.

What the CDK actually is
------------------------
A library that turns Python into a CloudFormation template -- the JSON document AWS reads
to create resources. You are not calling AWS APIs here; you are describing what should
exist, and CloudFormation works out the difference between that description and reality.
Nothing in this project is ever clicked in the console, which is what makes the setup
reviewable, repeatable, and still explainable in six months.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# infra/app.py -> infra -> the project root. Needed so `from infra.stacks...` works when
# the cdk command runs this file directly from inside the infra directory.
THIS_FILE = Path(__file__).resolve()
INFRA_DIRECTORY = THIS_FILE.parent
PROJECT_ROOT = INFRA_DIRECTORY.parent
sys.path.insert(0, str(PROJECT_ROOT))

import aws_cdk

from infra.stacks import app_stack
from infra.stacks import data_stack

#: Montreal. The health data stays in Canada, and it is the closest AWS region to
#: Vancouver. CDK_DEFAULT_ACCOUNT and CDK_DEFAULT_REGION are filled in automatically by
#: the cdk command from whatever `aws configure` set up, so no account number is ever
#: written down in this repository.
DEFAULT_REGION = "ca-central-1"

#: Put on every resource in the stack. Tags are what make a bill readable: without them
#: the monthly statement is a list of service names, and with them it says which project
#: spent the money.
STACK_TAGS = {
    "Project": "garmin-health-dashboard",
    "ManagedBy": "cdk",
}


def build_app() -> aws_cdk.App:
    """Describe every stack, and return the app without synthesising it.

    Kept separate from the module-level call below so the tests can build the app,
    inspect the template it produces, and never write anything to disk.
    """
    environment = aws_cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION", DEFAULT_REGION),
    )

    app = aws_cdk.App()

    storage = data_stack.DataStack(
        app,
        "HealthDashboardData",
        env=environment,
        description="Raw Garmin response storage and the application database.",
    )

    # Two stacks rather than one, and the split is deliberate. The data stack holds the
    # table and the raw archive, both set to survive deletion, and it should be touched as
    # rarely as possible. Everything in the application stack is rebuildable from this
    # repository in two minutes, so it can be destroyed and redeployed without a thought.
    # Keeping them apart means a careless `cdk destroy` on the app cannot reach the data.
    app_stack.AppStack(
        app,
        "HealthDashboardApp",
        table=storage.table,
        env=environment,
        description="The dashboard's API, website and the door in front of them.",
    )

    for tag_name, tag_value in STACK_TAGS.items():
        aws_cdk.Tags.of(app).add(tag_name, tag_value)

    return app


if __name__ == "__main__":
    build_app().synth()
