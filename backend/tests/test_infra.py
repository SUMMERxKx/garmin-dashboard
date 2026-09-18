"""Tests for the AWS data stack.

These run with no AWS account, no credentials and no network. The CDK turns the Python in
`infra/` into a CloudFormation template in memory, and each test asserts something about
that template. It is the cheapest possible check on infrastructure: a typo in a key name
would otherwise deploy perfectly and then fail on every read at runtime.

What is worth testing here, and what is not
-------------------------------------------
Not: that a bucket is a bucket. The CDK already guarantees that, and a test asserting it
only re-states the code.

Yes: the handful of properties that are DECISIONS -- the key names the application code
depends on, the refusal to destroy data with the stack, encryption, and the block on
public access. Each of those is a sentence in `data_stack.py`'s comments, and a sentence
in a comment is one careless edit away from being untrue.
"""

from __future__ import annotations

import aws_cdk
from aws_cdk import assertions

from backend.store import keys
from infra.stacks import data_stack

#: CloudFormation's own names for the two resource types, as they appear in a template.
BUCKET_TYPE = "AWS::S3::Bucket"
TABLE_TYPE = "AWS::DynamoDB::Table"


def build_template() -> assertions.Template:
    """Synthesise the stack once and hand back its template, ready to assert against."""
    app = aws_cdk.App()
    stack = data_stack.DataStack(app, "TestStack")

    return assertions.Template.from_stack(stack)


# ---------------------------------------------------------------------------
# The keys the application code depends on
# ---------------------------------------------------------------------------


def test_the_table_uses_the_same_key_names_as_the_local_store() -> None:
    """The one test that would catch a silent, total failure.

    `backend/store/keys.py` builds every address as a `pk`/`sk` pair. If the table were
    deployed with different key names, every deploy would succeed and every read would
    raise `ValidationException` at runtime. Asserting against the constants rather than
    against string literals means renaming a key in one place fails here rather than in
    production.
    """
    template = build_template()

    template.has_resource_properties(
        TABLE_TYPE,
        {
            "KeySchema": [
                {"AttributeName": data_stack.PARTITION_KEY_NAME, "KeyType": "HASH"},
                {"AttributeName": data_stack.SORT_KEY_NAME, "KeyType": "RANGE"},
            ]
        },
    )


def test_the_key_names_match_what_the_store_actually_writes() -> None:
    """The stack's constants and the store's own SQL must agree.

    `database.py` writes columns literally called `pk` and `sk`. This pins the two
    together so the infrastructure cannot drift from the code that uses it.
    """
    assert data_stack.PARTITION_KEY_NAME == "pk"
    assert data_stack.SORT_KEY_NAME == "sk"

    # And the store's own key builder must still produce values for those columns.
    assert keys.user_partition("me") == "USER#me"


# ---------------------------------------------------------------------------
# Data must survive the stack
# ---------------------------------------------------------------------------


def test_deleting_the_stack_does_not_delete_the_data() -> None:
    """The most important property in this file.

    `cdk destroy` tearing down years of health history would be unrecoverable. RETAIN
    makes deleting the data a separate, deliberate act.
    """
    template = build_template()

    for resource_type in (BUCKET_TYPE, TABLE_TYPE):
        resources = template.find_resources(resource_type)

        assert resources, f"no {resource_type} in the template"

        for logical_id, resource in resources.items():
            assert resource["DeletionPolicy"] == "Retain", f"{logical_id} would be deleted"
            assert resource["UpdateReplacePolicy"] == "Retain", f"{logical_id} would be replaced"


def test_the_table_can_be_restored_to_any_recent_second() -> None:
    """Point-in-time recovery. What this protects against is not AWS losing anything --
    it is a bad import overwriting a month of days with a parser bug."""
    template = build_template()

    template.has_resource_properties(
        TABLE_TYPE,
        {"PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True}},
    )


# ---------------------------------------------------------------------------
# It is health data, so: private and encrypted
# ---------------------------------------------------------------------------


def test_the_raw_bucket_blocks_every_route_to_being_public() -> None:
    """All four settings, not just the obvious one."""
    template = build_template()

    template.has_resource_properties(
        BUCKET_TYPE,
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            }
        },
    )


def test_the_raw_bucket_is_encrypted_at_rest() -> None:
    template = build_template()

    template.has_resource_properties(
        BUCKET_TYPE,
        {
            "BucketEncryption": {
                "ServerSideEncryptionConfiguration": [
                    {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
                ]
            }
        },
    )


def test_the_raw_bucket_refuses_plain_http() -> None:
    """`enforce_ssl` adds a bucket policy denying any request where SecureTransport is
    false. Checking the policy exists, rather than the flag, is checking the effect."""
    template = build_template()

    policies = template.find_resources("AWS::S3::BucketPolicy")

    assert policies, "no bucket policy: enforce_ssl did not take"

    rendered = str(policies)

    assert "aws:SecureTransport" in rendered
    assert "Deny" in rendered


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------


def test_the_table_is_billed_per_request() -> None:
    """One person opening a dashboard a few times a day. Reserved capacity would mean
    paying for an idle table all month."""
    template = build_template()

    template.has_resource_properties(TABLE_TYPE, {"BillingMode": "PAY_PER_REQUEST"})


def test_old_raw_responses_move_to_cheaper_storage() -> None:
    """They are read only when the parser is re-run over history, which is rare."""
    template = build_template()

    buckets = template.find_resources(BUCKET_TYPE)
    rendered = str(buckets)

    assert "GLACIER_IR" in rendered
    assert str(data_stack.ARCHIVE_RAW_AFTER_DAYS) in rendered


# ---------------------------------------------------------------------------
# The deploy has to tell you the names it generated
# ---------------------------------------------------------------------------


def test_the_stack_prints_the_names_the_app_needs() -> None:
    """AWS generates both names, so they are unknowable until the stack exists. Without
    these outputs the next step -- pointing the app at the table -- means hunting in the
    console."""
    template = build_template()

    outputs = template.find_outputs("*")

    assert "TableName" in outputs
    assert "RawBucketName" in outputs
