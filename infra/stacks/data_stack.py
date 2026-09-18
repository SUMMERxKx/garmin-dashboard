"""The storage layer: a bucket for raw responses, and one table for the app's data.

This is the first thing to deploy, and deliberately the only thing in this stack. Get
storage working and the application pointed at it before adding a scheduled fetcher on
top -- a broken ingest Lambda over working storage is a small problem, and the reverse
is a lost month of history.

The two halves mirror what already runs locally:

    fixtures/raw/garmin/dt=YYYY-MM-DD/*.json   ->  the S3 bucket
    dashboard.db (SQLite, pk/sk/body)          ->  the DynamoDB table

Neither is a redesign. The local SQLite store was shaped like DynamoDB from the first
day precisely so this step would be a swap rather than a rewrite.
"""

from __future__ import annotations

import aws_cdk
from aws_cdk import aws_dynamodb
from aws_cdk import aws_s3
from constructs import Construct

#: Raw responses move to cheaper storage after this long. They are only read when the
#: parser is re-run over history, which is rare -- and Glacier Instant Retrieval still
#: returns them in milliseconds when it happens, unlike the cheaper Glacier tiers that
#: take hours.
ARCHIVE_RAW_AFTER_DAYS = 90

#: An upload that fails halfway leaves parts behind that are billed but invisible in the
#: console. Cleaning them up after a week costs nothing and avoids a bill nobody can
#: explain.
ABANDON_INCOMPLETE_UPLOADS_AFTER_DAYS = 7

#: The two key columns, spelled here so the names cannot drift from `backend/store/keys.py`.
#: A typo in either would deploy cleanly and then fail at runtime on every single read.
PARTITION_KEY_NAME = "pk"
SORT_KEY_NAME = "sk"

#: Records carrying this attribute are deleted by DynamoDB once the timestamp passes, at
#: no cost. Records without it are never expired, which is every record the app writes
#: today -- it is here for drafts and caches later.
TIME_TO_LIVE_ATTRIBUTE = "expires_at"


class DataStack(aws_cdk.Stack):
    """The raw landing zone and the application database."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.raw_bucket = self.create_raw_bucket()
        self.table = self.create_table()

        self.publish_outputs()

    def create_raw_bucket(self) -> aws_s3.Bucket:
        """Where every Garmin response is saved exactly as it arrived.

        This is written to BEFORE anything is parsed, which is the whole point of it. If
        the parser has a bug, or Garmin renames a field, the fix is to re-run the parser
        over these files. Without them the data would simply be gone: the Garmin API is
        unofficial and does not keep history forever.
        """
        bucket = aws_s3.Bucket(
            self,
            "RawResponses",
            # Files are only ever added, never edited, so keeping old versions of the
            # same key would buy nothing and cost storage.
            versioned=False,
            # Encrypt at rest. This is health data.
            encryption=aws_s3.BucketEncryption.S3_MANAGED,
            # Block every route to making this public, not just the obvious one. There
            # are four separate settings behind this flag and all of them matter.
            block_public_access=aws_s3.BlockPublicAccess.BLOCK_ALL,
            # Reject any request that is not over HTTPS.
            enforce_ssl=True,
            # RETAIN means: if the stack is deleted, keep the bucket. Deliberate --
            # tearing down infrastructure must never silently destroy years of health
            # history. Deleting it has to be a separate, conscious act.
            removal_policy=aws_cdk.RemovalPolicy.RETAIN,
        )

        bucket.add_lifecycle_rule(
            id="ArchiveOldRawResponses",
            transitions=[
                aws_s3.Transition(
                    storage_class=aws_s3.StorageClass.GLACIER_INSTANT_RETRIEVAL,
                    transition_after=aws_cdk.Duration.days(ARCHIVE_RAW_AFTER_DAYS),
                )
            ],
            abort_incomplete_multipart_upload_after=aws_cdk.Duration.days(
                ABANDON_INCOMPLETE_UPLOADS_AFTER_DAYS
            ),
        )

        return bucket

    def create_table(self) -> aws_dynamodb.Table:
        """The application database: one table, two key columns.

        This is *single table design*. Instead of one table per kind of record,
        everything lives together and the KEY says what each record is:

            pk  "USER#me"                    who it belongs to
            sk  "DAY#2026-09-02#SNAPSHOT"    what it is

        Because sort keys are stored in order, asking for every key starting with
        "DAY#2026-09-02#" returns that whole day -- the Garmin snapshot, the weigh-in,
        the typed intake and every food entry -- in a single request. That one access
        pattern is the reason this is a key-value store rather than a relational one.

        `backend/store/database.py` already uses exactly these keys against SQLite, and
        the same tests run against both, so switching stores changes nothing else.
        """
        return aws_dynamodb.Table(
            self,
            "HealthData",
            partition_key=aws_dynamodb.Attribute(
                name=PARTITION_KEY_NAME,
                type=aws_dynamodb.AttributeType.STRING,
            ),
            sort_key=aws_dynamodb.Attribute(
                name=SORT_KEY_NAME,
                type=aws_dynamodb.AttributeType.STRING,
            ),
            # Pay only for requests actually made. For one person opening a dashboard a
            # few times a day this rounds to pennies, where reserving capacity would mean
            # paying for an idle table all month.
            billing_mode=aws_dynamodb.BillingMode.PAY_PER_REQUEST,
            # Lets the table be restored to any second within the last 35 days. The thing
            # it protects against is not AWS losing the data -- it is a bad import run
            # overwriting a month of days with a parser bug.
            point_in_time_recovery_specification=aws_dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            encryption=aws_dynamodb.TableEncryption.AWS_MANAGED,
            time_to_live_attribute=TIME_TO_LIVE_ATTRIBUTE,
            # Same reasoning as the bucket: never destroy the data with the stack.
            removal_policy=aws_cdk.RemovalPolicy.RETAIN,
        )

    def publish_outputs(self) -> None:
        """Print the generated names after a deploy, so they can go into the environment.

        AWS generates the real names -- a bucket name has to be unique across every
        account on earth -- so neither is known until the stack exists.
        """
        aws_cdk.CfnOutput(
            self,
            "RawBucketName",
            value=self.raw_bucket.bucket_name,
            description="S3 bucket holding raw Garmin responses.",
        )
        aws_cdk.CfnOutput(
            self,
            "TableName",
            value=self.table.table_name,
            description="DynamoDB table holding the application data. Set GARMIN_DASHBOARD_TABLE to this.",
        )
