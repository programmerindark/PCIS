"""Update-check interface (Step 10).

Deliberately an INTERFACE ONLY. No update mechanism is implemented, and
`NullUpdateService` -- which always reports "no update" -- is the
default so the application never contacts a network it was not asked to.

Why stop at the interface. A self-updating engineering tool that
silently replaces its own binaries is a liability: a bad update reaches
every house at once, and PCIS produces numbers people act on. When this
is implemented it should download, verify a signature, and require the
operator to confirm -- never swap code underneath a running app.

The three intended backends:

- `GitHubReleaseUpdateService`  -- poll the repository's Releases API
- `PrivateServerUpdateService`  -- poll a self-hosted manifest
- `ManualZipUpdateService`      -- inspect a zip the user supplies

Each only has to implement `check_for_update`; the UI depends on this
interface, not on any particular one.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from pcis import version

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class UpdateInfo:
    """An available update. `download_url` is never auto-fetched."""

    version: str
    release_notes: str
    download_url: str
    published: str = ""
    mandatory: bool = False


class UpdateService(ABC):
    """Interface every update backend implements."""

    @abstractmethod
    def check_for_update(self) -> UpdateInfo | None:
        """Return an UpdateInfo if a newer version exists, else None.

        Implementations MUST NOT download or install anything. They
        answer a question; acting on the answer is the user's call.
        """

    @staticmethod
    def is_newer(candidate: str, current: str | None = None) -> bool:
        """Compare dotted version strings numerically.

        String comparison gets this wrong in the obvious way: "1.10.0"
        sorts before "1.9.0" lexicographically.
        """
        current = current or version.VERSION

        def parts(v: str) -> tuple[int, ...]:
            out = []
            for chunk in v.strip().lstrip("vV").split("."):
                digits = "".join(c for c in chunk if c.isdigit())
                out.append(int(digits) if digits else 0)
            return tuple(out)

        a, b = parts(candidate), parts(current)
        length = max(len(a), len(b))
        return a + (0,) * (length - len(a)) > b + (0,) * (length - len(b))


class NullUpdateService(UpdateService):
    """Default backend: never reports an update, never uses the network."""

    def check_for_update(self) -> UpdateInfo | None:
        LOG.debug("Update check skipped: no update service is configured.")
        return None


def get_update_service() -> UpdateService:
    """The active backend. Returns `NullUpdateService` until one exists."""
    return NullUpdateService()
