"""Tests for signing in.

This is the code that decides whether a stranger can read a month of your heart rate, so
the tests are about what must NOT work as much as what must. Everything here is pure
arithmetic over strings -- no AWS, no clock, no network -- because the functions were
written to take `now` and the secret as arguments rather than reaching for them.
"""

from __future__ import annotations

import pytest

from backend.api import auth

SECRET = "a-secret-for-testing-only"
NOW = 1_700_000_000.0


# ---------------------------------------------------------------------------
# The cookie
# ---------------------------------------------------------------------------


def test_a_freshly_minted_cookie_is_valid() -> None:
    cookie = auth.mint_cookie(SECRET, now=NOW)

    assert auth.cookie_is_valid(cookie, SECRET, now=NOW)


def test_a_cookie_expires() -> None:
    """Thirty days, and then it does not work. A cookie copied off an old phone stops."""
    cookie = auth.mint_cookie(SECRET, now=NOW)

    just_before = NOW + auth.SESSION_LENGTH_SECONDS - 1
    just_after = NOW + auth.SESSION_LENGTH_SECONDS + 1

    assert auth.cookie_is_valid(cookie, SECRET, now=just_before)
    assert not auth.cookie_is_valid(cookie, SECRET, now=just_after)


def test_a_cookie_signed_with_another_secret_is_refused() -> None:
    """Rotating the signing secret signs everybody out. That is the emergency lever."""
    cookie = auth.mint_cookie(SECRET, now=NOW)

    assert not auth.cookie_is_valid(cookie, "a-different-secret", now=NOW)


def test_extending_the_expiry_by_hand_is_refused() -> None:
    """The attack this exists to stop: read your own cookie, change the date, stay in."""
    cookie = auth.mint_cookie(SECRET, now=NOW)
    signature = cookie.split(".")[1]

    forged = f"{int(NOW) + 10_000_000}.{signature}"

    assert not auth.cookie_is_valid(forged, SECRET, now=NOW)


@pytest.mark.parametrize(
    "rubbish",
    [
        "",
        "nonsense",
        "no-dot-here",
        "too.many.dots",
        ".",
        "notanumber.abc123",
        "9999999999.",
    ],
)
def test_malformed_cookies_are_refused_rather_than_raising(rubbish: str) -> None:
    """Anything can arrive in a cookie header. None of it may produce a stack trace."""
    assert not auth.cookie_is_valid(rubbish, SECRET, now=NOW)


def test_the_signature_is_an_hmac_not_a_plain_hash() -> None:
    """A plain hash of secret-plus-payload allows a length-extension attack, where
    someone holding one valid signature can forge another without the secret. This pins
    the construction so a future 'simplification' has to fail a test first."""
    import hashlib
    import hmac as hmac_module

    payload = "1700000000"
    expected = hmac_module.new(
        SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()

    assert auth.sign(payload, SECRET) == expected
    assert auth.sign(payload, SECRET) != hashlib.sha256((SECRET + payload).encode()).hexdigest()


def test_two_secrets_give_two_different_signatures() -> None:
    assert auth.sign("same-payload", "one") != auth.sign("same-payload", "two")


# ---------------------------------------------------------------------------
# The password
# ---------------------------------------------------------------------------


def test_the_right_password_matches_and_a_wrong_one_does_not() -> None:
    assert auth.password_matches("correct horse", "correct horse")
    assert not auth.password_matches("Correct horse", "correct horse")
    assert not auth.password_matches("", "correct horse")
    assert not auth.password_matches("correct horse ", "correct horse")


def test_a_generated_password_is_long_and_different_every_time() -> None:
    first = auth.random_password()
    second = auth.random_password()

    assert first != second
    assert auth.looks_like_a_strong_password(first) is None


def test_a_generated_secret_is_different_every_time() -> None:
    assert auth.random_secret() != auth.random_secret()


@pytest.mark.parametrize("weak", ["short", "password", "letmein", "changeme"])
def test_obviously_weak_passwords_are_named_as_such(weak: str) -> None:
    assert auth.looks_like_a_strong_password(weak) is not None


# ---------------------------------------------------------------------------
# The cache in front of Parameter Store
# ---------------------------------------------------------------------------


def test_the_password_is_cached_briefly_and_then_read_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """One read per minute rather than one per sign-in, so a password changed in the
    console takes effect within a minute rather than instantly. That trade is only
    acceptable if the cache really does expire, which is what this pins."""
    reads = {"count": 0}

    class FakeParameterStore:
        class exceptions:
            ParameterNotFound = RuntimeError

        def get_parameter(self, Name, WithDecryption):
            reads["count"] = reads["count"] + 1
            return {"Parameter": {"Value": "from-the-store"}}

    monkeypatch.setattr("boto3.client", lambda service: FakeParameterStore())
    auth.forget_cached_password()

    assert auth.read_password(now=1000.0) == "from-the-store"
    assert reads["count"] == 1

    # Within the cache window: no second read.
    auth.read_password(now=1000.0 + auth.PASSWORD_CACHE_SECONDS - 1)
    assert reads["count"] == 1

    # Past it: read again.
    auth.read_password(now=1000.0 + auth.PASSWORD_CACHE_SECONDS + 1)
    assert reads["count"] == 2

    auth.forget_cached_password()


def test_no_password_in_the_store_is_its_own_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Distinct from 'wrong password', because the fix is completely different: one means
    try again, the other means the deployment is unfinished."""

    class Missing(Exception):
        pass

    class FakeParameterStore:
        class exceptions:
            ParameterNotFound = Missing

        def get_parameter(self, Name, WithDecryption):
            raise Missing()

    monkeypatch.setattr("boto3.client", lambda service: FakeParameterStore())
    auth.forget_cached_password()

    with pytest.raises(auth.PasswordNotSet):
        auth.read_password(now=2000.0)

    auth.forget_cached_password()


def test_no_signing_secret_is_refused_rather_than_signing_with_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Signing with an empty secret would produce cookies anybody could forge."""
    monkeypatch.delenv(auth.SIGNING_SECRET_VARIABLE, raising=False)

    with pytest.raises(auth.PasswordNotSet):
        auth.signing_secret()

    monkeypatch.setenv(auth.SIGNING_SECRET_VARIABLE, "   ")

    with pytest.raises(auth.PasswordNotSet):
        auth.signing_secret()
