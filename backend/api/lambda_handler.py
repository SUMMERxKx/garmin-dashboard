"""The same FastAPI app, running in Lambda instead of under uvicorn.

There is no second copy of the API here. `server.py` is imported unchanged and wrapped,
which is the whole point: the thing that runs in AWS is the thing that was tested locally,
not a reimplementation of it that can drift.

What mangum does
----------------
Lambda does not speak HTTP. It hands a function a JSON object describing a request and
expects a JSON object describing a response. FastAPI, like every Python web framework,
speaks ASGI -- a different shape entirely. `mangum` is the adapter between the two: it
translates the Lambda event into an ASGI request, runs the app, and translates the
response back. It is about four hundred lines and it is the entire reason this move costs
one file.

`mangum` was put in the project's `api` extra at the very beginning, before there was an
API at all, for exactly this moment.

Why this file also checks a header
----------------------------------
The function has a public URL. Anybody who learns it could call the API directly and walk
straight around the password at the CloudFront edge, which would make that password
decorative.

So CloudFront is configured to add a secret header to every request it forwards, and this
file refuses any request that does not carry it. CloudFront OVERWRITES that header on the
way through, so a viewer cannot supply their own -- the only way to present it is to come
through the distribution.

The alternative, and why it is not what runs here: a function URL set to `AWS_IAM`, with
CloudFront signing each request through an origin access control. That is the tidier
design and it was tried first. CloudFront's signature was rejected every time with a bare
403, while the identical request signed by hand succeeded -- so the function, its
permissions and the access control were all provably correct, and the fault sat somewhere
inside CloudFront's signing that no configuration change reached. This pattern is the
common alternative, it is simple enough to verify by reading, and it fails closed.

The check is skipped entirely when the variable is unset, so `uvicorn` on the laptop is
unaffected.
"""

from __future__ import annotations

import os

import mangum
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.api import server

#: The header CloudFront adds to every request it forwards, and the environment variable
#: holding the value to expect. Both are set by `infra/stacks/app_stack.py` from one
#: secret, so they cannot drift apart.
ORIGIN_SECRET_HEADER = "x-origin-secret"
ORIGIN_SECRET_VARIABLE = "GARMIN_ORIGIN_SECRET"


class OnlyThroughCloudFront(BaseHTTPMiddleware):
    """Reject any request that did not arrive through the distribution."""

    def __init__(self, app, expected_secret: str) -> None:
        super().__init__(app)
        self.expected_secret = expected_secret

    async def dispatch(self, request, call_next):
        offered = request.headers.get(ORIGIN_SECRET_HEADER)

        # A plain `!=` on secrets leaks a little information through how long the
        # comparison takes, because it stops at the first differing byte. `compare_digest`
        # always looks at everything. The attack is impractical over the internet; using
        # the right function costs nothing and removes the need to argue about it.
        import hmac

        if offered is None or not hmac.compare_digest(offered, self.expected_secret):
            return JSONResponse(
                status_code=403,
                content={"detail": "This API is only reachable through the dashboard."},
            )

        return await call_next(request)


def build_handler():
    """Wrap the app, adding the origin check only when a secret is configured."""
    expected_secret = os.environ.get(ORIGIN_SECRET_VARIABLE, "")

    if expected_secret != "":
        server.app.add_middleware(OnlyThroughCloudFront, expected_secret=expected_secret)

    # `lifespan="off"` because the app has no startup or shutdown work, and the default
    # would make every cold start wait for a protocol that answers immediately.
    return mangum.Mangum(server.app, lifespan="off")


#: The function Lambda calls, named in the stack as
#: `backend.api.lambda_handler.handler`. Built at import time, which in Lambda means once
#: per container rather than once per request.
handler = build_handler()
