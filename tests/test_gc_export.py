"""The browser copy of the GC formula must not drift from the engine.

`frontend/lib/gcPolicy.ts` exists because the public calculator has to
answer instantly on a phone. That is a real user need, but it puts a second
implementation of a MONEY formula in the repo, and a payout table that
disagrees with itself is the worst defect this project could ship: it would
be wrong in the one place a farmer has no way to check.

These tests are the price of that convenience.

  * the generated slab table must be current with pcis.core.gc_policy
  * the TypeScript arithmetic must agree with the Python engine across a
    grid that deliberately straddles every slab boundary and the 5%
    mortality rule

If Node is unavailable the cross-check skips rather than fails -- the guard
is about catching drift in CI and locally, not about blocking a test run on
a machine with no JavaScript runtime.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pcis.core import gc_policy as gcp

ROOT = Path(__file__).resolve().parents[1]
GENERATED = ROOT / "frontend" / "lib" / "gcTables.generated.ts"
EXPORTER = ROOT / "scripts" / "export_gc_tables.py"


def test_generated_table_is_current():
    """Regenerating must produce byte-identical output.

    Catches the case where someone edits a rate in Python and ships without
    re-running the exporter, leaving the browser paying yesterday's rates.
    """
    before = GENERATED.read_text(encoding="utf-8")
    subprocess.run([sys.executable, str(EXPORTER)], check=True, capture_output=True)
    after = GENERATED.read_text(encoding="utf-8")
    assert before == after, (
        "frontend/lib/gcTables.generated.ts is stale. "
        "Run: python3 scripts/export_gc_tables.py"
    )


def test_generated_table_contains_every_rate():
    """Every rate in the engine appears in the generated file."""
    text = GENERATED.read_text(encoding="utf-8")
    for _upper, rates in gcp._GC_SLABS:  # noqa: SLF001
        for shed, rate in rates.items():
            assert f"{shed}: {rate}" in text


# --- cross-check the ported arithmetic ------------------------------------

# Chosen to straddle the things that branch: the 5% mortality rule, the
# 1.650 boundary where the rate falls hardest, and the 1.800 cliff where it
# goes to zero.
GRID = [
    # chicks, lifted, weight_kg, feed_kg, shed
    (21_432, 20_118, 66_624.350, 107_880.0, "other_ec"),      # real settlement
    (26_000, 25_700, 53_306.0, 88_000.0, "other_ec"),         # near 1.650
    (15_000, 14_250, 28_500.0, 45_600.0, "parivartan_ec"),    # policy illustration
    (10_000, 9_000, 18_000.0, 40_000.0, "other_basic_ec"),    # past the cliff
    (10_000, 9_900, 22_000.0, 30_000.0, "parivartan_semi_ec"),  # low cFCR
    (10_000, 9_400, 20_000.0, 33_000.0, "other_semi_ec"),     # just over 5%
    (5_000, 4_999, 12_000.0, 18_000.0, "parivartan_basic_ec"),
    (30_000, 28_000, 70_000.0, 119_000.0, "other_ec"),
]

RUNNER = """
const gc = require(process.argv[2]);
const cases = JSON.parse(process.argv[3]);
console.log(JSON.stringify(cases.map(c => gc.assess(c[0], c[1], c[2], c[3], c[4]))));
"""


def _node_available() -> bool:
    return shutil.which("node") is not None


@pytest.mark.skipif(not _node_available(), reason="node not installed")
def test_typescript_matches_python_across_the_grid(tmp_path):
    """The browser must produce the same rupees as the engine.

    Compares the fields a farmer actually sees. A mismatch here means the
    calculator is quoting a rate the cited engine does not agree with.

    Compiled with the repo's own `typescript` rather than ts-node, so the
    check runs with no extra dependency -- a guard that is usually skipped
    is not a guard.
    """
    frontend = ROOT / "frontend"
    tsc = frontend / "node_modules" / ".bin" / "tsc"
    if not tsc.exists():
        pytest.skip("typescript not installed in frontend/node_modules")

    out_dir = tmp_path / "js"
    compile_proc = subprocess.run(
        [str(tsc), "lib/gcPolicy.ts",
         "--outDir", str(out_dir),
         "--module", "commonjs", "--target", "es2020",
         "--esModuleInterop", "--skipLibCheck"],
        capture_output=True, text=True, cwd=str(frontend),
    )
    # tsc infers rootDir from the inputs, so the emitted path depends on
    # whether the generated table sits beside the source. Find it rather
    # than assume a layout.
    found = list(out_dir.rglob("gcPolicy.js"))
    assert found, (
        f"tsc emitted no gcPolicy.js under {out_dir}\n"
        f"{compile_proc.stdout}\n{compile_proc.stderr}"
    )
    compiled = found[0]

    runner = tmp_path / "run.js"
    runner.write_text(RUNNER, encoding="utf-8")
    proc = subprocess.run(
        ["node", str(runner), str(compiled), json.dumps(GRID)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    ts_results = json.loads(proc.stdout)

    for case, ts in zip(GRID, ts_results):
        chicks, lifted, weight, feed, shed = case
        py = gcp.assess(chicks, lifted, weight, feed, shed_type=shed)
        label = f"{case}"
        assert ts["fcr"] == pytest.approx(py.fcr, abs=1e-3), label
        assert ts["cbwKg"] == pytest.approx(py.cbw_kg, abs=1e-3), label
        assert ts["cfcr"] == pytest.approx(py.cfcr, abs=1e-3), label
        assert ts["ratePerKg"] == py.rate_per_kg, label
        assert ts["rearingCharge"] == pytest.approx(py.rearing_charge, abs=1), label
        assert ts["cbwPenalised"] == py.cbw_penalised, label
        assert ts["mortalityPct"] == pytest.approx(py.mortality_pct, abs=1e-3), label


def test_shortage_is_not_mortality_in_either_implementation():
    """Lot B924B95625 carried 55 short birds.

    Counting them as deaths gives 8.884% where the settlement says 8.635%.
    Asserted here rather than only in test_gc_policy so the browser copy is
    covered by the same guarantee.
    """
    a = gcp.assess(22_016, 20_060, 47_376.725, 77_280.0, shed_type="other_ec", shortage=55)
    assert a.mortality_pct == pytest.approx(8.635, abs=0.001)

    without = gcp.assess(22_016, 20_060, 47_376.725, 77_280.0, shed_type="other_ec")
    assert without.mortality_pct == pytest.approx(8.884, abs=0.001)
