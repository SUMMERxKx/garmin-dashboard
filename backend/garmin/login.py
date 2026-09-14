"""Logging in to Garmin.

This module does exactly one thing: hand back a logged-in Garmin client object that the
rest of the code can call methods on. It does not fetch anything and it does not save
anything except the token bundle.

Why this is its own file
------------------------
Logging in is the only part of talking to Garmin that needs a human being present,
because of two-factor authentication. Everything else -- fetching, parsing, storing --
can run unattended on a server. Keeping the human-in-the-loop part in its own small
file makes that boundary obvious, and it is the boundary that later lets the cloud run
without ever holding your password.

There is no official Garmin API for this data. We use the `garminconnect` library,
which logs in the same way the Garmin Connect website does. That is why the login flow
looks like a browser's rather than like an API key.
"""

from __future__ import annotations

import getpass
import os
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Where the token bundle is kept
# ---------------------------------------------------------------------------
#
# Working out the project root from this file's own location, one step at a time:
#
#   Path(__file__)          ".../Garmin Dashboard/backend/garmin/login.py"
#   .resolve()              the same thing as a full absolute path, symlinks followed
#   .parent                 ".../Garmin Dashboard/backend/garmin"
#   .parent.parent          ".../Garmin Dashboard/backend"
#   .parent.parent.parent   ".../Garmin Dashboard"          <- the project root
#
# Doing it this way, rather than writing the path out as text, means the code still
# works if the project folder is renamed or moved to another machine.

THIS_FILE = Path(__file__).resolve()
GARMIN_PACKAGE_DIRECTORY = THIS_FILE.parent
BACKEND_DIRECTORY = GARMIN_PACKAGE_DIRECTORY.parent
PROJECT_ROOT = BACKEND_DIRECTORY.parent

#: The folder the `garminconnect` library saves its login tokens into. A token is like
#: the cookie a website gives your browser after you sign in: proof that you already
#: logged in, so you do not have to type a password again. This folder is gitignored,
#: because anyone holding these tokens can read your Garmin data.
TOKEN_DIRECTORY = PROJECT_ROOT / ".garmin_tokens"


def ask_for_mfa_code() -> str:
    """Ask the person at the keyboard for their two-factor code.

    The `garminconnect` library calls this function itself, but only when Garmin asks
    for a second factor. We never call it directly. Handing a function to a library so
    the library can call us back is a common pattern, usually called a *callback*.

    It has to be interactive. There is no way to guess or store a code that changes
    every thirty seconds, which is the entire point of two-factor authentication.
    """
    print()
    print("  Garmin is asking for a two-factor code.")
    print("  Check your email or your authenticator app.")

    typed_code = input("  Code: ")

    # `.strip()` removes spaces and the newline from either end. People often paste a
    # code with a trailing space, and Garmin would reject it as wrong.
    return typed_code.strip()


def a_saved_token_bundle_exists() -> bool:
    """True if a previous login already left tokens on this machine.

    This is what decides whether we need a password at all. If tokens are already
    there, we deliberately do not ask for one.
    """
    if not TOKEN_DIRECTORY.exists():
        return False

    # `iterdir()` lists what is inside a folder. The folder can exist but be empty --
    # for example if a previous login failed halfway -- and an empty folder is no use
    # to us, so check for actual contents rather than just existence.
    everything_in_the_folder = list(TOKEN_DIRECTORY.iterdir())

    if len(everything_in_the_folder) == 0:
        return False
    else:
        return True


def find_the_email_address() -> str:
    """Get the Garmin account email, from the environment or by asking.

    Checking the environment variable first means you can set it once in your shell and
    stop retyping it, while still having the prompt as a fallback so the code works on
    a machine where nothing is set up.
    """
    email_from_the_environment = os.environ.get("GARMIN_EMAIL")

    if email_from_the_environment:
        return email_from_the_environment
    else:
        typed_email = input("  Garmin email: ")
        return typed_email.strip()


def find_the_password() -> str:
    """Get the Garmin account password, from the environment or by asking.

    `getpass.getpass` prompts exactly like `input` does, except it does not echo what
    you type to the screen. That matters more than it looks: without it the password
    would sit in your terminal's scrollback, and quite possibly in your shell history.

    The password is used once, to create the token bundle, and is never written to
    disk by us.
    """
    password_from_the_environment = os.environ.get("GARMIN_PASSWORD")

    if password_from_the_environment:
        return password_from_the_environment
    else:
        return getpass.getpass("  Garmin password (not shown as you type): ")


def log_in() -> Any:
    """Return a logged-in Garmin client, asking for a password only if it has to.

    The return type is `Any` because the `garminconnect` library does not publish type
    information for its client class, so there is no more specific type to promise.

    What the library's own `login()` does when we call it, in order:

      1. looks in the token folder for a saved bundle
      2. if there is one, refreshes it when it is close to expiring, and stops there
      3. if there is not one, logs in with the email and password we gave it, calling
         `ask_for_mfa_code` if Garmin wants a second factor
      4. saves the resulting bundle into the token folder for next time

    So the first run is interactive and every run after it is not. That property is the
    reason the eventual cloud version can hold tokens instead of a password.
    """
    # Imported here, inside the function, rather than at the top of the file. The
    # reason is that `garminconnect` is an optional dependency: someone should be able
    # to import this module -- to read `TOKEN_DIRECTORY`, say -- on a machine where the
    # library is not installed, and only hit the missing-library error if they actually
    # try to log in.
    import garminconnect

    # `mode=0o700` means "only the user who owns this folder may read, write, or look
    # inside it". Other accounts on the machine are locked out. The `0o` prefix marks
    # the number as octal, which is how Unix file permissions have always been written.
    TOKEN_DIRECTORY.mkdir(mode=0o700, exist_ok=True)

    tokens_are_already_saved = a_saved_token_bundle_exists()

    # These two stay as None when tokens exist. Passing None is how we make sure the
    # library uses the saved tokens and is never even given a credential to try.
    email: str | None = None
    password: str | None = None

    if tokens_are_already_saved:
        print(f"  Using the saved tokens in {TOKEN_DIRECTORY.name}/ -- no password needed.")
    else:
        print("  No saved tokens yet. This one login will create them.")
        email = find_the_email_address()
        password = find_the_password()

    client = garminconnect.Garmin(
        email=email,
        password=password,
        prompt_mfa=ask_for_mfa_code,
    )

    # `login()` needs the folder as a plain string rather than a Path object, because
    # that is the argument type the library was written to accept.
    client.login(str(TOKEN_DIRECTORY))

    # Stop holding the plaintext password now that it has been used. This is tidiness
    # rather than real security -- the string may still exist in memory until Python
    # reuses that space -- but there is no reason to keep it around for the whole run.
    del password

    if not tokens_are_already_saved:
        print(f"  Logged in. Tokens saved to {TOKEN_DIRECTORY.name}/.")
        print("  Later runs will reuse them, so you will not be asked again.")

    return client
