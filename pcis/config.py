"""User configuration and first-run setup (Step 7).

Creates `settings.json` and the working directories on first launch,
under the per-user data directory (see `pcis.paths`) rather than beside
the executable -- an installed app under Program Files cannot write to
its own folder.

Settings are deliberately limited to presentation and file locations.
Nothing here can alter an engineering constant: those live in the cited
core modules and are not user-tunable, because a config file that can
silently change a published Aviagen figure would destroy the guarantee
that every number traces to a source.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from pcis import paths

LOG = logging.getLogger(__name__)

SETTINGS_FILENAME = "settings.json"

#: Directories created on first run.
SUBDIRECTORIES = ("logs", "reports", "exports", "backups")

DEFAULT_SETTINGS: dict[str, Any] = {
    "schema_version": 1,
    "unit_system": "metric",        # "metric" | "imperial"
    "theme": "system",              # "system" | "light" | "dark"
    "default_house_name": "House 1",
    "confirm_on_exit": False,
    "log_level": "INFO",
}


def settings_path() -> Path:
    return paths.user_data_dir() / SETTINGS_FILENAME


def ensure_directories() -> dict[str, Path]:
    """Create the working directories, returning their paths."""
    root = paths.user_data_dir()
    root.mkdir(parents=True, exist_ok=True)
    made = {}
    for name in SUBDIRECTORIES:
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        made[name] = d
    return made


def load_settings() -> dict[str, Any]:
    """Load settings, creating defaults on first run.

    A corrupt or unreadable file is backed up rather than deleted and
    replaced with defaults, so the app always starts. Silently losing a
    user's configuration is worse than starting fresh with a copy kept.
    """
    ensure_directories()
    path = settings_path()

    if not path.exists():
        save_settings(DEFAULT_SETTINGS)
        LOG.info("Created default settings at %s", path)
        return dict(DEFAULT_SETTINGS)

    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("settings file is not a JSON object")
    except Exception as exc:
        backup = path.with_suffix(".json.corrupt")
        try:
            path.replace(backup)
            LOG.warning("Unreadable settings (%s); kept a copy at %s", exc, backup)
        except OSError:
            LOG.warning("Unreadable settings (%s); could not back it up", exc)
        save_settings(DEFAULT_SETTINGS)
        return dict(DEFAULT_SETTINGS)

    # Merge forward so a settings file written by an older version gains
    # new keys instead of raising KeyError somewhere deep in the UI.
    merged = dict(DEFAULT_SETTINGS)
    merged.update(loaded)
    return merged


def save_settings(settings: dict[str, Any]) -> Path:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-replace: a crash mid-write must not leave a truncated
    # settings file that fails to parse on next launch.
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path
