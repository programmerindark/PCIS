"""Version information for PCIS (Step 9).

Kept as a plain module rather than read from package metadata so it
works identically from source and inside a frozen bundle, where
`importlib.metadata` may not find a dist-info directory.

BUILD_DATE and GIT_COMMIT are stamped by the build script. They stay
at their placeholder values when running from a working copy, which is
itself useful information: an About dialog showing "development build"
tells you this is not a release.
"""

from __future__ import annotations

import subprocess
from datetime import date

MAJOR = 1
MINOR = 0
PATCH = 0

#: Stamped by build.bat at release time. "dev" when run from source.
BUILD_DATE = "dev"
GIT_COMMIT = "dev"

VERSION = f"{MAJOR}.{MINOR}.{PATCH}"


def git_commit() -> str:
    """Short commit hash, resolved live when running from a checkout.

    Falls back to the stamped value (or "unknown") inside a frozen
    build, where there is no .git directory to interrogate.
    """
    if GIT_COMMIT != "dev":
        return GIT_COMMIT
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=2, check=True,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def build_date() -> str:
    return BUILD_DATE if BUILD_DATE != "dev" else date.today().isoformat()


def version_string() -> str:
    """Single line for the title bar and About dialog."""
    suffix = "" if BUILD_DATE != "dev" else " (development build)"
    return f"PCIS {VERSION}{suffix}"


def full_version_info() -> dict[str, str]:
    return {
        "version": VERSION,
        "build_date": build_date(),
        "git_commit": git_commit(),
    }
