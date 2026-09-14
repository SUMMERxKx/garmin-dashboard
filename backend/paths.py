"""Where the project lives on disk.

Two modules need to know the project root: `login` keeps the token bundle underneath
it, and `raw_files` keeps the saved Garmin responses underneath it. Both used to work
it out for themselves, which meant the same four lines and the same explanation existed
twice and could quietly drift apart. Working it out once, here, means there is one
answer to "where is the project root?" and one place to read why.
"""

from __future__ import annotations

from pathlib import Path

# Working out the project root from this file's own location, one step at a time:
#
#   Path(__file__)   ".../Garmin Dashboard/backend/paths.py"
#   .resolve()       the same thing as a full absolute path, symlinks followed
#   .parent          ".../Garmin Dashboard/backend"
#   .parent.parent   ".../Garmin Dashboard"          <- the project root
#
# Doing it this way, rather than writing the path out as text, means the code still
# works if the project folder is renamed or moved to another machine.

THIS_FILE = Path(__file__).resolve()
BACKEND_DIRECTORY = THIS_FILE.parent
PROJECT_ROOT = BACKEND_DIRECTORY.parent
