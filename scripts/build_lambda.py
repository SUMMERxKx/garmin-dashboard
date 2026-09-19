"""Build the zip that becomes the API Lambda, without Docker.

    .venv/bin/python -m scripts.build_lambda

Lambda wants a directory containing the application and every library it imports, laid
out as if it were already unpacked. This assembles that under `build/api/`, and the CDK
uploads the directory as the function's code.

Why not Docker
--------------
The usual CDK approach bundles Python dependencies inside a Linux container so the
compiled parts match Lambda's machine. Docker is not installed here, and requiring it to
deploy would be a bad trade for one function. Instead `pip` is told to fetch the *Linux*
wheels explicitly rather than the macOS ones it would pick by default:

    --platform manylinux2014_x86_64 --only-binary=:all:

That only works when every dependency publishes a pre-built Linux wheel, which these do.
If one ever does not, pip fails loudly here rather than producing a package that imports
fine on this laptop and dies in AWS with a linker error -- which is the failure this flag
exists to prevent.

What goes in, and what deliberately does not
--------------------------------------------
IN:  the backend package, the runtime libraries, and the two personal data files the API
     reads for the macro target and the DEXA scan.
OUT: `boto3`, which the Lambda runtime already provides (adding it would be 15 MB for
     nothing); `uvicorn`, which mangum replaces; the tests; the dashboard; and anything
     under `docs/` that is not one of the two files named below.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from backend import paths

#: Where packages are assembled. Gitignored -- build output, rebuilt every time.
BUILD_ROOT = paths.PROJECT_ROOT / "build"

#: The two functions, and what each one imports at runtime.
#:
#: They are built separately rather than as one package that does both jobs. The API is
#: called on every page load and wants the smallest possible cold start; the fetcher runs
#: four times a day and drags in a compiled HTTP library that the API has no use for.
#: Sharing one package would put that cost on every dashboard open.
PACKAGES = {
    "api": ["fastapi", "mangum", "pyyaml"],
    "fetcher": ["garminconnect", "pyyaml"],
}

#: Lambda's Python. Must match the runtime declared in `infra/stacks/app_stack.py`, or
#: the compiled parts of pydantic will be built for the wrong interpreter.
PYTHON_VERSION = "3.12"

#: x86_64 rather than arm64. ARM is marginally cheaper, but every library publishes an
#: x86_64 wheel and not all publish ARM ones, and at this scale the saving is a fraction
#: of a cent. Must match the architecture in the stack.
LAMBDA_PLATFORM = "manylinux2014_x86_64"

#: Copied into the package as well as the code. Both are gitignored personal files, and
#: both are read by `api/payload.read_fixed_facts`: without them the deployed dashboard
#: would lose the macro target, the height and birth date, and the DEXA panel. The
#: function is private and the bucket is private, so they are no more exposed there than
#: they are here.
PERSONAL_FILES = [
    Path("seed") / "food-library.yaml",
    Path("docs") / "personal" / "dexa-scans.yaml",
]

#: Removed after the install. Test suites and compiled caches inside site-packages add
#: megabytes and are never imported at runtime.
JUNK_PATTERNS = ["__pycache__", "*.dist-info", "*.pyc", "tests"]


def empty_the_build_directory(where: Path) -> None:
    """Start from nothing, so a removed dependency actually disappears.

    Building on top of a previous run would leave an old library in place after it was
    taken out of the list, and the package would keep working locally for reasons nobody
    could find.
    """
    if where.exists():
        shutil.rmtree(where)

    where.mkdir(parents=True)


def install_the_libraries(where: Path, libraries: list[str]) -> None:
    """Fetch Linux wheels for every runtime library into the build directory."""
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--quiet",
        "--target",
        str(where),
        "--platform",
        LAMBDA_PLATFORM,
        "--python-version",
        PYTHON_VERSION,
        # Refuse to build anything from source. Building would produce macOS binaries,
        # which is exactly the silent failure this whole approach avoids.
        "--only-binary=:all:",
        *libraries,
    ]

    print("  installing:", ", ".join(libraries))

    subprocess.run(command, check=True)


def copy_the_application(where: Path) -> None:
    """Copy the backend package in, minus the tests."""
    destination = where / "backend"

    shutil.copytree(
        paths.PROJECT_ROOT / "backend",
        destination,
        ignore=shutil.ignore_patterns("__pycache__", "tests"),
    )

    print("  copied: backend/")


def copy_the_personal_files(where: Path) -> None:
    """Copy the food library and the DEXA scans, if they exist on this machine.

    Missing is not an error. `read_fixed_facts` already handles their absence -- the
    dashboard simply shows no target and no scan -- so a fresh clone can still deploy.
    """
    for relative_path in PERSONAL_FILES:
        source = paths.PROJECT_ROOT / relative_path

        if not source.exists():
            print(f"  skipped (not on this machine): {relative_path}")
            continue

        destination = where / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)

        print(f"  copied: {relative_path}")


def remove_the_junk(where: Path) -> None:
    """Delete what will never be imported, to keep the upload small."""
    for pattern in JUNK_PATTERNS:
        for found in where.rglob(pattern):
            if found.is_dir():
                shutil.rmtree(found, ignore_errors=True)
            else:
                found.unlink(missing_ok=True)


def measure(where: Path) -> tuple[int, float]:
    """How many files the package holds, and how many megabytes."""
    total_files = 0
    total_bytes = 0

    for one_file in where.rglob("*"):
        if one_file.is_file():
            total_files = total_files + 1
            total_bytes = total_bytes + one_file.stat().st_size

    return (total_files, total_bytes / (1024 * 1024))


def build_one(name: str, libraries: list[str]) -> None:
    """Assemble one package end to end."""
    where = BUILD_ROOT / name

    print()
    print(f"Building the {name} package in {where}")

    empty_the_build_directory(where)
    install_the_libraries(where, libraries)
    copy_the_application(where)
    copy_the_personal_files(where)
    remove_the_junk(where)

    how_many_files, megabytes = measure(where)

    print(f"  built: {how_many_files} files, {megabytes:.1f} MB unpacked")


def main() -> int:
    """Entry point. 0 if both packages were built."""
    for name, libraries in PACKAGES.items():
        build_one(name, libraries)

    print()
    print("Deploy them with:  .venv/bin/python -m scripts.deploy")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
