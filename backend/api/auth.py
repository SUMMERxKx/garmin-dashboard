"""Signing in: checking the password, and minting the cookie that proves you did.

Why a cookie and not a header
------------------------------
The browser's own Basic Auth box worked and was ugly, and it could not be styled at all.
Replacing it means the check has to move somewhere a nicely-dressed page can drive, and a
cookie is the only credential a browser attaches to every request by itself -- including
the request for an image or a stylesheet, which a header set by JavaScript cannot reach.

What the cookie contains
------------------------
Nothing secret, and nothing worth stealing:

    <expiry as epoch seconds>.<HMAC-SHA256 of that, in hex>

The signature is what matters. Anyone can read the expiry; nobody can change it without
the signing secret, because the signature would stop matching. So the cookie proves "the
server issued this, and it has not expired" without the server remembering anything. That
is the whole point -- there is no session table, nothing to clean up, and the check can
happen at the CloudFront edge where there is no database to consult.

Where the two secrets live, and why they are different things
--------------------------------------------------------------
**The password** is in AWS Systems Manager Parameter Store, encrypted. It is the one you
change, and you change it in the AWS console with no deploy and no file on your laptop.

**The signing secret** is a random value the password is never derived from. It lives in
the Lambda's environment and, identically, in the CloudFront KeyValueStore so the edge can
verify what this file signs. Changing it signs everybody out, which is the emergency
lever if a cookie is ever stolen.

Keeping them separate means changing your password does not invalidate your other
sessions, and rotating the signing secret does not require you to pick a new password.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

import boto3

#: How long a session lasts. Thirty days for a dashboard only you open: long enough that
#: you are not retyping it constantly, short enough that a cookie copied off an old phone
#: stops working within a month.
SESSION_LENGTH_SECONDS = 30 * 24 * 60 * 60

#: The cookie's name, matching `infra/functions/session_gate.js`.
COOKIE_NAME = "session"

#: Where the password lives. A path rather than a bare name, so a future second secret
#: can sit beside it and one permission covers the pair.
PASSWORD_PARAMETER_NAME = "/garmin-dashboard/login-password"

#: The environment variable holding the signing secret, set by the stack.
SIGNING_SECRET_VARIABLE = "GARMIN_SESSION_SECRET"

#: How long to trust a password read from Parameter Store before reading it again.
#: Without this, every sign-in would be an extra network call; with it, a password you
#: change in the console takes effect within a minute rather than instantly. That is a
#: fair trade for one user, and a minute is short enough not to be confusing.
PASSWORD_CACHE_SECONDS = 60


class PasswordNotSet(Exception):
    """Raised when there is no password in Parameter Store yet.

    A distinct exception rather than a None, because the endpoint has to answer this case
    differently: it is not "wrong password", it is "this deployment is not finished", and
    saying so plainly is the difference between a two-minute fix and an afternoon.
    """


#: The last password read, and when. Module level so it survives between invocations of a
#: warm Lambda container, which is where the saving is.
_cached_password: str | None = None
_cached_at: float = 0.0


def read_password(now: float | None = None) -> str:
    """The current password, from Parameter Store, cached briefly.

    `now` is injectable so the cache can be tested without waiting a minute.
    """
    global _cached_password, _cached_at

    if now is None:
        now = time.time()

    if _cached_password is not None and (now - _cached_at) < PASSWORD_CACHE_SECONDS:
        return _cached_password

    client = boto3.client("ssm")

    try:
        answer = client.get_parameter(Name=PASSWORD_PARAMETER_NAME, WithDecryption=True)
    except client.exceptions.ParameterNotFound as error:
        raise PasswordNotSet(
            f"No password at {PASSWORD_PARAMETER_NAME}. Set one in the AWS console, "
            "or run scripts/deploy.py which creates it."
        ) from error

    _cached_password = answer["Parameter"]["Value"]
    _cached_at = now

    return _cached_password


def forget_cached_password() -> None:
    """Drop the cache. For tests, and for a future 'reload now' command."""
    global _cached_password, _cached_at

    _cached_password = None
    _cached_at = 0.0


def signing_secret() -> str:
    """The secret this file signs cookies with, and the edge verifies them with."""
    secret = os.environ.get(SIGNING_SECRET_VARIABLE, "")

    if secret.strip() == "":
        raise PasswordNotSet(
            f"{SIGNING_SECRET_VARIABLE} is not set, so sessions cannot be signed."
        )

    return secret


def sign(payload: str, secret: str) -> str:
    """The HMAC of a payload, as hex.

    HMAC rather than a plain hash of secret-plus-payload. The naive version is vulnerable
    to a length-extension attack, where someone who has a valid signature can produce a
    valid signature for a LONGER payload without knowing the secret. HMAC is the standard
    construction that does not have that flaw, and it is one line either way.
    """
    return hmac.new(
        key=secret.encode("utf-8"),
        msg=payload.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


def mint_cookie(secret: str, now: float | None = None) -> str:
    """A signed cookie value that expires `SESSION_LENGTH_SECONDS` from now."""
    if now is None:
        now = time.time()

    expires_at = int(now) + SESSION_LENGTH_SECONDS
    payload = str(expires_at)

    return f"{payload}.{sign(payload, secret)}"


def cookie_is_valid(value: str, secret: str, now: float | None = None) -> bool:
    """Whether a cookie was signed by us and has not expired.

    The signature is checked BEFORE the expiry is trusted, because the expiry is only
    meaningful once we know it has not been edited.
    """
    if now is None:
        now = time.time()

    parts = value.split(".")

    if len(parts) != 2:
        return False

    payload, offered_signature = parts

    # `compare_digest` rather than `==`: a plain comparison stops at the first differing
    # character, so how long it takes leaks how much of the signature was right.
    if not hmac.compare_digest(offered_signature, sign(payload, secret)):
        return False

    try:
        expires_at = int(payload)
    except ValueError:
        return False

    return now < expires_at


def password_matches(offered: str, expected: str) -> bool:
    """Whether the typed password is the right one, compared in constant time."""
    return hmac.compare_digest(offered.encode("utf-8"), expected.encode("utf-8"))


def looks_like_a_strong_password(password: str) -> str | None:
    """Say what is weak about a password, or None if it is fine.

    Used when setting one, never when checking one. Deliberately mild: this guards one
    personal dashboard behind a cookie that expires, not a bank. The only real rule is
    that it should not be guessable in a few thousand tries.
    """
    if len(password) < 12:
        return "Use at least 12 characters."

    if password.lower() in ("password", "changeme", "letmein"):
        return "That is one of the first passwords anybody tries."

    return None


def random_password() -> str:
    """A password to start with, if you do not supply one."""
    import secrets
    import string

    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(20))


def random_secret() -> str:
    """A signing secret. Longer than a password, and never typed by a human."""
    import secrets

    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")
