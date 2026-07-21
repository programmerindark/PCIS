"""Shared pytest fixtures.

Sets Qt to the offscreen platform plugin *before* PySide6 is imported
anywhere, so the GUI test suite runs headlessly in CI/sandboxes with
no physical or virtual display attached. If a real display is already
configured (QT_QPA_PLATFORM set by the environment), that choice is
left alone.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """A single QApplication instance shared across the whole test
    session (Qt does not support more than one per process).
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
