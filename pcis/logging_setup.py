"""Application logging and crash handling (Step 8).

Two jobs:

1. Write a rotating log to `<user data>/logs/application.log`.
2. Install a `sys.excepthook` so an unhandled exception is recorded and
   shown to the user, instead of a frozen GUI app vanishing with no
   window, no message and no trace of why.

That second point is the whole reason this module exists. Running from
source, an uncaught exception prints a traceback to the console. In a
windowed PyInstaller build there is no console: the process simply
disappears. From the operator's side the application "just closed", and
there is nothing to report or diagnose.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
import traceback
from pathlib import Path

from pcis import config, paths, version

LOG_FILENAME = "application.log"
MAX_BYTES = 2 * 1024 * 1024
BACKUP_COUNT = 5

_configured = False


def log_file_path() -> Path:
    return paths.user_data_dir() / "logs" / LOG_FILENAME


def configure(level: str | int = "INFO") -> Path:
    """Set up file + console logging. Safe to call more than once."""
    global _configured
    path = log_file_path()
    if _configured:
        return path

    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    ))

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)

    # Only add a console handler when there is a console to write to.
    # A windowed frozen build has sys.stderr set to None, and logging to
    # it would raise inside the logging machinery itself.
    if sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(logging.Formatter("%(levelname)-8s %(name)s: %(message)s"))
        root.addHandler(console)

    _configured = True
    info = version.full_version_info()
    logging.getLogger(__name__).info(
        "PCIS %s starting (build %s, commit %s, frozen=%s)",
        info["version"], info["build_date"], info["git_commit"], paths.is_frozen(),
    )
    return path


def _show_error_dialog(summary: str, detail: str) -> None:
    """Best-effort user-facing crash dialog.

    Wrapped defensively: if Qt is the thing that failed, trying to show
    a Qt dialog can fail too, and an exception raised inside the
    excepthook replaces a useful message with a worse one.
    """
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox

        if QApplication.instance() is None:
            return
        box = QMessageBox()
        box.setIcon(QMessageBox.Critical)
        box.setWindowTitle("PCIS - Unexpected Error")
        box.setText(
            "PCIS hit an unexpected problem.\n\n"
            f"{summary}\n\n"
            "Your saved data has not been affected. Details have been written "
            "to the log file below -- please include it if you report this."
        )
        box.setInformativeText(str(log_file_path()))
        box.setDetailedText(detail)
        box.exec()
    except Exception:
        pass


def install_exception_hook() -> None:
    """Route unhandled exceptions to the log and a dialog."""
    previous = sys.excepthook

    def hook(exc_type, exc_value, exc_tb):
        # Ctrl+C should still behave normally rather than popping a dialog.
        if issubclass(exc_type, KeyboardInterrupt):
            previous(exc_type, exc_value, exc_tb)
            return
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logging.getLogger("pcis").critical("Unhandled exception:\n%s", detail)
        _show_error_dialog(f"{exc_type.__name__}: {exc_value}", detail)
        previous(exc_type, exc_value, exc_tb)

    sys.excepthook = hook


def initialise() -> Path:
    """Configure logging from settings and install the crash hook."""
    try:
        level = config.load_settings().get("log_level", "INFO")
    except Exception:
        level = "INFO"
    path = configure(level)
    install_exception_hook()
    return path
