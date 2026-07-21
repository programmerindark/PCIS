"""Build the Python payload the web app loads into Pyodide.

Ships ONLY `pcis/core` and `pcis/equipment` -- the dependency-free
engineering layer. `pcis.gui` needs PySide6, `pcis.db` needs SQLAlchemy
and `pcis.reports` needs reportlab; none exist in a browser, and none
are needed to compute a recommendation.

This script is the mechanism that keeps ONE source of truth for the
physics: the browser runs the same .py files the desktop app and the
test suite run, not a reimplementation that could drift.

Run from the project root:  python tools/build_web_payload.py
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "pcis_core.zip"
INCLUDE = ["core", "equipment"]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    if OUT.exists():
        OUT.unlink()

    written = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(ROOT / "pcis" / "__init__.py", "pcis/__init__.py")
        written += 1
        for pkg in INCLUDE:
            for path in sorted((ROOT / "pcis" / pkg).rglob("*.py")):
                if "__pycache__" in path.parts:
                    continue
                zf.write(path, str(path.relative_to(ROOT)).replace("\\", "/"))
                written += 1

    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()[:12]
    print(f"wrote web/pcis_core.zip: {written} modules, {OUT.stat().st_size/1024:.0f} KB, sha256:{digest}")
    print("Bump CACHE_VERSION in web/sw.js so installed phones pick up the change.")


if __name__ == "__main__":
    main()
