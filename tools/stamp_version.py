"""Stamp build date and git commit into pcis/version.py (Step 9).

Called by build.bat before freezing, and again with --reset afterwards
so the working copy is not left with a modified file. Frozen builds
therefore report a real date and commit, while source runs correctly
report themselves as development builds.
"""

from __future__ import annotations

import re
import subprocess
import sys
from datetime import date
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parent.parent / "pcis" / "version.py"


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=5, check=True)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def main() -> int:
    reset = "--reset" in sys.argv
    text = VERSION_FILE.read_text(encoding="utf-8")

    build_date = "dev" if reset else date.today().isoformat()
    commit = "dev" if reset else _git_commit()

    text = re.sub(r'^BUILD_DATE = ".*"$', f'BUILD_DATE = "{build_date}"',
                  text, flags=re.M)
    text = re.sub(r'^GIT_COMMIT = ".*"$', f'GIT_COMMIT = "{commit}"',
                  text, flags=re.M)
    VERSION_FILE.write_text(text, encoding="utf-8")
    print(f"version.py: BUILD_DATE={build_date} GIT_COMMIT={commit}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
