"""Where PCIS keeps user data.

Why this module exists
----------------------
Running from source, writing `pcis.db` into the current directory is
fine -- the project folder is writable and the file sits next to the
code you are working on.

Frozen into a Windows executable, that same behaviour is a bug:

- If the app is installed under `C:\\Program Files\\`, the directory is
  read-only for a standard user and the write fails outright.
- If it is launched from Explorer, the working directory can be
  `C:\\Windows\\System32` -- so on a machine where it *does* have
  permission, the operator's logged recommendations end up somewhere
  they will never find them.
- Two shortcuts launched from different folders would silently use two
  different databases, splitting the history the ML export depends on.

So a frozen build stores data in the per-user application data
directory instead, which is writable, stable across launches, and
survives reinstalling the app.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "PCIS"


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS")


def user_data_dir() -> Path:
    """Per-user, writable directory for PCIS data.

    Windows:  %LOCALAPPDATA%\\PCIS
    macOS:    ~/Library/Application Support/PCIS
    Linux:    $XDG_DATA_HOME/PCIS  (or ~/.local/share/PCIS)
    """
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_DATA_HOME")
        root = Path(base) if base else Path.home() / ".local" / "share"
    return root / APP_NAME


def default_database_path() -> str:
    """Where the app should keep its SQLite database.

    Frozen builds use the per-user data directory. Running from source
    keeps the old behaviour (`pcis.db` beside the working directory),
    so development and the test suite are unaffected.
    """
    if not is_frozen():
        return "pcis.db"
    directory = user_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return str(directory / "pcis.db")


def default_export_dir() -> Path:
    """Sensible starting folder for the CSV/PDF save dialogs.

    A frozen app's working directory is not somewhere a user wants a
    report saved; their Documents folder is.
    """
    documents = Path.home() / "Documents"
    return documents if documents.is_dir() else Path.home()


def resource_path(relative: str) -> Path:
    """Locate a bundled read-only asset (icons, templates).

    PyInstaller unpacks bundled data to `sys._MEIPASS`, which is NOT the
    directory containing the executable. Hardcoding a path relative to
    the exe finds nothing in a frozen build; hardcoding one relative to
    the source tree finds nothing once installed. This resolves both.
    """
    if is_frozen():
        return Path(sys._MEIPASS) / relative
    return Path(__file__).resolve().parent.parent / relative
