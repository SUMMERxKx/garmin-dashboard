"""The application tier: the API, the website, and the door in front of both.

Everything a browser touches lives here. `data_stack.py` holds the two things that must
outlive any mistake -- the table and the raw archive -- and is deployed separately for
that reason. Everything in THIS stack is rebuildable from the repository in a couple of
minutes, so it carries no retention policies and can be destroyed and recreated freely.

The shape
---------

    browser ──► CloudFront ──► (viewer request) basic_auth.js ──► 401, or onward
                     │
                     ├── /api/*  ──► Lambda function URL (IAM auth, signed by CloudFront)
                     │                   └── FastAPI, unchanged, reading DynamoDB
                     │
                     └── everything else ──► S3 bucket (private, read via OAC)
                                                 └── the built React app

One distribution serving both halves is what makes the dashboard's existing code work
untouched: it already asks for `/api/days` relative to its own origin, exactly as it does
behind Vite's proxy on the laptop. Nothing in the browser knows it moved.

Neither the bucket nor the function is reachable directly. The bucket blocks all public
access and only trusts this distribution; the function URL requires a signed AWS request,
which only this distribution can produce. So the Basic Auth check at the edge is not a
curtain in front of an open door -- it is the only way in.
"""

from __future__ import annotations

import os
from pathlib import Path

import aws_cdk
from aws_cdk import aws_cloudfront
from aws_cdk import aws_cloudfront_origins
from aws_cdk import aws_dynamodb
from aws_cdk import aws_events
from aws_cdk import aws_events_targets
from aws_cdk import aws_iam
from aws_cdk import aws_lambda
from aws_cdk import aws_s3
from aws_cdk import aws_s3_deployment
from constructs import Construct

#: infra/stacks/app_stack.py -> stacks -> infra -> the project root.
THIS_FILE = Path(__file__).resolve()
INFRA_DIRECTORY = THIS_FILE.parent.parent
PROJECT_ROOT = INFRA_DIRECTORY.parent

#: Built by `scripts.build_lambda`, which fetches Linux wheels so nothing has to be
#: compiled in a container. The deploy fails with a clear message if either is missing.
LAMBDA_PACKAGE_DIRECTORY = PROJECT_ROOT / "build" / "api"
FETCHER_PACKAGE_DIRECTORY = PROJECT_ROOT / "build" / "fetcher"

#: Built by `npm run build` in `dashboard/`.
WEBSITE_DIRECTORY = PROJECT_ROOT / "dashboard" / "dist"

#: Must match `scripts/build_lambda.py`. The compiled parts of pydantic are built for a
#: specific interpreter and processor, so a mismatch here fails at import time in AWS
#: with an error that says nothing useful about the real cause.
LAMBDA_RUNTIME = aws_lambda.Runtime.PYTHON_3_12
LAMBDA_ARCHITECTURE = aws_lambda.Architecture.X86_64

#: 512 MB. Lambda scales processor speed with memory, so a larger setting can be both
#: faster AND cheaper -- the bill is memory multiplied by time, and halving the time pays
#: for doubling the memory. 512 is where this workload stops getting meaningfully faster.
LAMBDA_MEMORY_MEGABYTES = 512

#: Generous for a request that reads one DynamoDB query and does arithmetic. It is here
#: to bound a cold start plus a slow first call, not because the work is slow.
LAMBDA_TIMEOUT_SECONDS = 30

#: Seventeen Garmin calls for each of three days, over somebody else's network. Nothing
#: here is slow, but the whole thing is at the mercy of how fast Garmin answers, so the
#: timeout is set by what is tolerable rather than by what is expected.
FETCHER_TIMEOUT_SECONDS = 300

#: Fetching is almost entirely waiting on the network, so more memory buys nothing.
FETCHER_MEMORY_MEGABYTES = 512

#: Four times a day, in UTC. In Vancouver that is roughly 06:00, 12:00, 18:00 and
#: midnight, drifting an hour with daylight saving, which does not matter for a job whose
#: whole purpose is to eventually notice a day the phone synced late.
#:
#: Four rather than more because Garmin only has what your watch last uploaded, which is
#: itself only as often as your phone syncs. Asking more often returns the same answer
#: and, on an unofficial API, is how accounts get blocked.
FETCH_HOURS_UTC = "1,7,13,19"

#: How many days back each run re-fetches, ending with yesterday. Re-fetching is free and
#: repairs a day that was thin when it was first seen.
FETCH_DAYS_BACK = 3

#: Where the Garmin token bundle lives. Matches `backend/garmin/fetch_lambda.py`. Not
#: created by this stack -- `scripts/upload_garmin_token.py` puts it there, because it
#: comes from an interactive login on the laptop.
TOKEN_PARAMETER_NAME = "/garmin-dashboard/garmin-tokens"

#: The cookie the session lives in, matching `backend/api/auth.py` and `session_gate.js`.
SESSION_COOKIE_NAME = "session"

#: The key the session signing secret is stored under, matching `session_gate.js` and
#: `backend/api/auth.py`. The API signs cookies with this value and the edge verifies them
#: with it, so the two must hold exactly the same string.
SESSION_SECRET_KEY = "session-secret"

#: Read from the environment at synth time. `scripts/deploy.py` supplies it from the
#: local secrets file and writes the same value into the KeyValueStore after deploying.
SESSION_SECRET_VARIABLE = "GARMIN_SESSION_SECRET"

#: Where the login password lives. Deliberately NOT created or written by this stack: it
#: is the one value meant to be changed by hand in the AWS console, and a stack that
#: managed it would overwrite that change on the next deploy.
PASSWORD_PARAMETER_PATH = "/garmin-dashboard/*"

#: The header CloudFront adds to every request it forwards to the API, matching
#: `backend/api/lambda_handler.py`. CloudFront overwrites it, so a viewer cannot supply
#: their own -- presenting it is proof the request came through the distribution.
ORIGIN_SECRET_HEADER = "x-origin-secret"

#: Read from the environment at synth time rather than written here, so the value stays
#: out of the repository. `scripts/deploy.py` sets it from the local secrets file.
ORIGIN_SECRET_VARIABLE = "GARMIN_ORIGIN_SECRET"


def read_secret(variable_name: str, used_for: str) -> str:
    """A secret from the environment, with a useful error when it is missing.

    Deliberately not generated here. A value invented during synth would change on every
    deploy, and CDK would rewrite the distribution and the function each time for no
    reason -- and worse, a new signing secret would sign everybody out on every deploy.
    Deliberately not written in this file either, because this file is public.
    """
    secret = os.environ.get(variable_name, "").strip()

    if secret == "":
        raise ValueError(
            f"{variable_name} is not set. It is used for {used_for}.\n"
            "Deploy with `.venv/bin/python -m scripts.deploy`, which reads it from\n"
            "docs/personal/, or export it yourself."
        )

    return secret


class AppStack(aws_cdk.Stack):
    """The API Lambda, the static site, and the CloudFront distribution over both."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        table: aws_dynamodb.ITable,
        raw_bucket: aws_s3.IBucket,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.table = table
        self.raw_bucket = raw_bucket
        self.origin_secret = read_secret(ORIGIN_SECRET_VARIABLE, "CloudFront and the API")
        self.session_secret = read_secret(SESSION_SECRET_VARIABLE, "signing session cookies")

        self.api_function = self.create_api_function()
        self.fetcher = self.create_fetcher()
        self.api_url = self.create_function_url()
        self.website_bucket = self.create_website_bucket()
        self.credential_store = self.create_credential_store()
        self.gate = self.create_gate()
        self.distribution = self.create_distribution()

        self.publish_the_website()
        self.publish_outputs()

    # -----------------------------------------------------------------------
    # The API
    # -----------------------------------------------------------------------

    def create_api_function(self) -> aws_lambda.Function:
        """The FastAPI app, running in Lambda.

        The code is the directory `scripts.build_lambda` assembles. Handing CDK a plain
        directory rather than asking it to bundle one means the deploy needs no Docker
        and no network beyond the upload itself.
        """
        if not LAMBDA_PACKAGE_DIRECTORY.exists():
            raise FileNotFoundError(
                f"{LAMBDA_PACKAGE_DIRECTORY} does not exist. Build it first:\n"
                "    .venv/bin/python -m scripts.build_lambda"
            )

        function = aws_lambda.Function(
            self,
            "Api",
            runtime=LAMBDA_RUNTIME,
            architecture=LAMBDA_ARCHITECTURE,
            handler="backend.api.lambda_handler.handler",
            code=aws_lambda.Code.from_asset(str(LAMBDA_PACKAGE_DIRECTORY)),
            memory_size=LAMBDA_MEMORY_MEGABYTES,
            timeout=aws_cdk.Duration.seconds(LAMBDA_TIMEOUT_SECONDS),
            environment={
                # The one variable that decides which store the app opens. Set here, so
                # the deployed function reads DynamoDB while the same code on the laptop
                # keeps reading SQLite.
                "GARMIN_DASHBOARD_TABLE": self.table.table_name,
                # What the function requires every caller to present. Only CloudFront
                # knows it, because only CloudFront is configured to send it.
                ORIGIN_SECRET_VARIABLE: self.origin_secret,
                # What it signs session cookies with. The edge verifies them with the
                # same value, read from the KeyValueStore.
                SESSION_SECRET_VARIABLE: self.session_secret,
            },
            description="The dashboard's read and write API.",
        )

        # Exactly what the API does, and nothing else: it reads and writes days, weigh-ins
        # and typed intake, so it gets read/write on the table and no access at all to the
        # raw archive, which it never touches. Granting from the resource itself rather
        # than attaching a written-out policy means the permissions cannot drift from the
        # thing they describe.
        self.table.grant_read_write_data(function)

        # Read the login password, and only that path. The parameter itself is not
        # managed by this stack -- see PASSWORD_PARAMETER_PATH -- so permission is granted
        # by path rather than by pointing at a resource CDK owns.
        function.add_to_role_policy(
            aws_iam.PolicyStatement(
                actions=["ssm:GetParameter"],
                resources=[
                    aws_cdk.Arn.format(
                        aws_cdk.ArnComponents(
                            service="ssm",
                            resource="parameter",
                            resource_name=PASSWORD_PARAMETER_PATH.lstrip("/"),
                        ),
                        self,
                    )
                ],
            )
        )

        return function

    def create_fetcher(self) -> aws_lambda.Function:
        """The scheduled Garmin fetch, and the timer that runs it.

        This is the piece that makes the dashboard independent of the laptop. It does
        what `run_fetch` and `import` do together: ask Garmin for a few recent days, put
        the raw responses in the bucket untouched, then interpret them into the table.

        It logs in with a token bundle rather than a password -- see
        `backend/garmin/fetch_lambda.py` for why that is possible and why it matters.
        """
        if not FETCHER_PACKAGE_DIRECTORY.exists():
            raise FileNotFoundError(
                f"{FETCHER_PACKAGE_DIRECTORY} does not exist. Build it first:\n"
                "    .venv/bin/python -m scripts.build_lambda"
            )

        function = aws_lambda.Function(
            self,
            "Fetcher",
            runtime=LAMBDA_RUNTIME,
            architecture=LAMBDA_ARCHITECTURE,
            handler="backend.garmin.fetch_lambda.handler",
            code=aws_lambda.Code.from_asset(str(FETCHER_PACKAGE_DIRECTORY)),
            memory_size=FETCHER_MEMORY_MEGABYTES,
            timeout=aws_cdk.Duration.seconds(FETCHER_TIMEOUT_SECONDS),
            environment={
                "GARMIN_DASHBOARD_TABLE": self.table.table_name,
                "GARMIN_DASHBOARD_BUCKET": self.raw_bucket.bucket_name,
                "GARMIN_FETCH_DAYS": str(FETCH_DAYS_BACK),
            },
            description="Fetches recent days from Garmin, on a schedule.",
        )

        # Writes interpreted days, and writes raw responses. It never reads either back
        # for anything but its own normalising, so read is granted with write rather than
        # separately.
        self.table.grant_read_write_data(function)
        self.raw_bucket.grant_put(function)

        # Reads the token bundle and writes the refreshed one back. Scoped to that single
        # parameter: this function has no business reading the login password, which sits
        # under the same prefix.
        token_parameter_arn = aws_cdk.Arn.format(
            aws_cdk.ArnComponents(
                service="ssm",
                resource="parameter",
                resource_name=TOKEN_PARAMETER_NAME.lstrip("/"),
            ),
            self,
        )

        function.add_to_role_policy(
            aws_iam.PolicyStatement(
                actions=["ssm:GetParameter", "ssm:PutParameter"],
                resources=[token_parameter_arn],
            )
        )

        aws_events.Rule(
            self,
            "FetchSchedule",
            description="Fetch recent days from Garmin four times a day.",
            schedule=aws_events.Schedule.cron(minute="0", hour=FETCH_HOURS_UTC),
            targets=[aws_events_targets.LambdaFunction(function)],
        )

        return function

    def create_function_url(self) -> aws_lambda.FunctionUrl:
        """An HTTPS endpoint for the function, guarded by a secret only CloudFront sends.

        `NONE` here does not mean open. The function itself refuses any request that does
        not carry the secret header, and CloudFront is the only thing configured to send
        it -- see `backend/api/lambda_handler.py`. Anyone who finds this URL gets a 403.

        The tidier design is `AWS_IAM` with CloudFront signing each request through an
        origin access control, and that was tried first, three times. CloudFront's
        signature was rejected every time with a bare 403 raised before the function ran,
        while the same request signed by hand returned 200 -- proving the function, the
        resource policy and the access control were all correct. Rather than keep guessing
        at a signing fault with a ten-minute feedback loop, this takes the well-trodden
        alternative. It fails closed and it can be verified by reading forty lines.
        """
        return self.api_function.add_function_url(
            auth_type=aws_lambda.FunctionUrlAuthType.NONE
        )

    # -----------------------------------------------------------------------
    # The website
    # -----------------------------------------------------------------------

    def create_website_bucket(self) -> aws_s3.Bucket:
        """Where the built React app lives.

        Private, like everything else. It is not configured as an S3 "website", because
        that feature requires public access; CloudFront reads from it directly instead.

        DESTROY here, unlike the data stack's RETAIN. This bucket holds build output and
        nothing else -- `npm run build` recreates every byte of it -- so keeping it after
        the stack is gone would leave litter, not history.
        """
        return aws_s3.Bucket(
            self,
            "Website",
            encryption=aws_s3.BucketEncryption.S3_MANAGED,
            block_public_access=aws_s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=aws_cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

    # -----------------------------------------------------------------------
    # The door
    # -----------------------------------------------------------------------

    def create_credential_store(self) -> aws_cloudfront.KeyValueStore:
        """A tiny key-value store at the edge, holding the cookie signing secret.

        Created EMPTY on purpose. The secret is written afterwards by `scripts/deploy.py`,
        so it never appears in this repository and never appears in the CloudFormation
        template either. Until it is written, `session_gate.js` cannot read the key and
        turns everybody away, which is the correct state for a door whose lock is not
        fitted.
        """
        return aws_cloudfront.KeyValueStore(
            self,
            "Credential",
            comment="Session cookie signing secret for the dashboard.",
        )

    def create_gate(self) -> aws_cloudfront.Function:
        """The session check, running at the edge on every request.

        A CloudFront *Function*, not a Lambda@Edge: it runs in a tiny JavaScript sandbox
        inside the CloudFront node itself, starts in under a millisecond, and is billed
        per million invocations. The trade is that it may only touch the request and the
        response -- no network calls, no filesystem -- which is precisely why the
        credential has to come from a KeyValueStore rather than from a secrets service.
        """
        return aws_cloudfront.Function(
            self,
            "BasicAuth",
            code=aws_cloudfront.FunctionCode.from_file(
                file_path=str(INFRA_DIRECTORY / "functions" / "session_gate.js")
            ),
            # 2.0 is the runtime that can read a KeyValueStore and await a promise.
            runtime=aws_cloudfront.FunctionRuntime.JS_2_0,
            key_value_store=self.credential_store,
            comment="Session cookie check for the whole distribution.",
        )

    def create_distribution(self) -> aws_cloudfront.Distribution:
        """One distribution serving the site and the API, with the gate on both."""
        gate_association = aws_cloudfront.FunctionAssociation(
            function=self.gate,
            event_type=aws_cloudfront.FunctionEventType.VIEWER_REQUEST,
        )

        website_origin = aws_cloudfront_origins.S3BucketOrigin.with_origin_access_control(
            self.website_bucket
        )

        api_origin = aws_cloudfront_origins.FunctionUrlOrigin(
            self.api_url,
            # Added to every request CloudFront forwards, and overwritten if a viewer
            # tries to send their own. This is what the function checks.
            custom_headers={ORIGIN_SECRET_HEADER: self.origin_secret},
        )

        return aws_cloudfront.Distribution(
            self,
            "Distribution",
            comment="Garmin health dashboard.",
            default_root_object="index.html",
            default_behavior=aws_cloudfront.BehaviorOptions(
                origin=website_origin,
                viewer_protocol_policy=aws_cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=aws_cloudfront.CachePolicy.CACHING_OPTIMIZED,
                function_associations=[gate_association],
            ),
            additional_behaviors={
                "/api/*": aws_cloudfront.BehaviorOptions(
                    origin=api_origin,
                    viewer_protocol_policy=aws_cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    # Never cached, and -- the part that is not obvious -- the cache
                    # policy has to mention the session cookie. See `api_cache_policy`.
                    cache_policy=self.api_cache_policy(),
                    # POST is how a weigh-in and a day's calories are recorded, so the
                    # read-only default would break the Log page.
                    allowed_methods=aws_cloudfront.AllowedMethods.ALLOW_ALL,
                    # Forward only what the API actually reads, and above all NOT the
                    # Authorization header.
                    #
                    # This is not tidiness, it is the difference between working and not.
                    # CloudFront signs requests to an IAM-protected function URL by
                    # putting its signature in the Authorization header -- and it decides
                    # whether to do that by looking at the origin request POLICY. A policy
                    # that declares Authorization as forwarded tells CloudFront the viewer
                    # owns that header, so it does not sign, and the function URL rejects
                    # the unsigned request with a 403 that mentions nothing about headers.
                    # `basic_auth.js` deleting the header at runtime does not help: the
                    # policy is what is consulted, not the actual request.
                    origin_request_policy=self.api_request_policy(),
                    function_associations=[gate_association],
                ),
            },
            # North America and Europe. The cheapest class, and it is where you are.
            price_class=aws_cloudfront.PriceClass.PRICE_CLASS_100,
        )

    def api_cache_policy(self) -> aws_cloudfront.CachePolicy:
        """Never cache the API -- and keep the Set-Cookie header on the way back.

        Nothing is cached in practice, which is the obvious half: the API answers with
        today's numbers and accepts writes, so caching any of it would show stale readings
        and swallow a weigh-in. The DEFAULT time-to-live is zero and the Lambda sends no
        `Cache-Control`, so every response is fetched fresh.

        The non-obvious half is the cookie list, and it took two failures to land on.
        **CloudFront strips `Set-Cookie` from an origin response when the behaviour's
        CACHE policy does not mention cookies.** With the managed CACHING_DISABLED policy,
        signing in returned a perfectly good 204 -- verified by calling the Lambda
        directly, which did send the header -- and the browser received no cookie, so the
        login page simply bounced you back to itself.

        Naming the cookie fixes that, but CloudFront then refuses the policy outright:
        *"The parameter CookieBehavior is invalid for policy with caching disabled."* A
        cookie list is only allowed when caching is not switched off entirely, which is
        why the MAXIMUM is one second rather than zero. That single second is the whole
        price of being able to set a cookie, and it buys nothing back: the default of zero
        is what every response actually uses.

        The cookie is named rather than allowing all cookies, so anything else a browser
        happens to be carrying stays out of the cache key.
        """
        return aws_cloudfront.CachePolicy(
            self,
            "ApiNoCache",
            comment="Effectively no caching, but Set-Cookie survives.",
            default_ttl=aws_cdk.Duration.seconds(0),
            min_ttl=aws_cdk.Duration.seconds(0),
            # Not zero, and not a typo. See the paragraph above.
            max_ttl=aws_cdk.Duration.seconds(1),
            cookie_behavior=aws_cloudfront.CacheCookieBehavior.allow_list(SESSION_COOKIE_NAME),
            header_behavior=aws_cloudfront.CacheHeaderBehavior.none(),
            query_string_behavior=aws_cloudfront.CacheQueryStringBehavior.all(),
        )

    def api_request_policy(self) -> aws_cloudfront.OriginRequestPolicy:
        """What reaches the API from the viewer's request.

        An allow list rather than "everything except", so the set is stated positively and
        a future header cannot be forwarded by accident. The API is a JSON endpoint that
        reads a query string and, on a POST, a JSON body -- so it needs the content type,
        the accept header, and the query string. Nothing else, and emphatically not
        Authorization.
        """
        return aws_cloudfront.OriginRequestPolicy(
            self,
            "ApiRequests",
            comment="Minimal headers for the API origin. Must not include Authorization.",
            header_behavior=aws_cloudfront.OriginRequestHeaderBehavior.allow_list(
                "content-type",
                "accept",
            ),
            query_string_behavior=aws_cloudfront.OriginRequestQueryStringBehavior.all(),
            # The API has no sessions and reads no cookies.
            cookie_behavior=aws_cloudfront.OriginRequestCookieBehavior.none(),
        )

    def publish_the_website(self) -> None:
        """Upload the built dashboard and clear the caches that would hide it.

        The invalidation matters. CloudFront keeps copies at every edge it has served
        from, so without it a deploy would sit behind the previous version for hours and
        look like a broken build.
        """
        if not WEBSITE_DIRECTORY.exists():
            raise FileNotFoundError(
                f"{WEBSITE_DIRECTORY} does not exist. Build it first:\n"
                "    cd dashboard && npm run build"
            )

        aws_s3_deployment.BucketDeployment(
            self,
            "PublishWebsite",
            sources=[aws_s3_deployment.Source.asset(str(WEBSITE_DIRECTORY))],
            destination_bucket=self.website_bucket,
            distribution=self.distribution,
            distribution_paths=["/*"],
        )

    def publish_outputs(self) -> None:
        """The address, and the two names needed to fit the lock afterwards."""
        aws_cdk.CfnOutput(
            self,
            "DashboardUrl",
            value=f"https://{self.distribution.distribution_domain_name}",
            description="Open this. It will send you to the login page.",
        )
        aws_cdk.CfnOutput(
            self,
            "CredentialStoreArn",
            value=self.credential_store.key_value_store_arn,
            description="Write the session signing secret here after deploying.",
        )
        aws_cdk.CfnOutput(
            self,
            "FetcherFunctionName",
            value=self.fetcher.function_name,
            description="Invoke this by hand to fetch immediately.",
        )
        aws_cdk.CfnOutput(
            self,
            "DistributionId",
            value=self.distribution.distribution_id,
            description="For invalidating the cache after a website change.",
        )
