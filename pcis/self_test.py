"""Self-verification for a packaged build.

Why this exists
---------------
A PyInstaller build can succeed and still produce an application that
dies on launch. It happened twice in this project:

  * `reportlab` imports `PIL` unconditionally -- excluding PIL built
    cleanly and crashed at start-up with ModuleNotFoundError.
  * Listing Qt submodules in `excludes` made PyInstaller's PySide6 hook
    drop `shiboken6`, the binding layer PySide6 cannot start without.

Neither appeared as a build error. Both were found only by running the
frozen binary and watching it fail. That is a terrible thing to rely on
a human remembering to do, and impossible for whoever builds this next.

So the executable can check itself:

    PCIS.exe --self-test

It exercises every subsystem that has ever broken under freezing --
imports, bundled assets, writable data directory, database, settings,
PDF generation, Qt widget construction -- and exits non-zero with a
readable report if anything fails. `build.bat` runs it automatically
after freezing, so a broken bundle cannot reach a release.

This deliberately does NOT re-test the engineering. That is what the
344-test suite is for, and it runs before the build. This answers a
different question: "did the packaging survive?"
"""

from __future__ import annotations

import tempfile
import traceback
from pathlib import Path

Check = tuple[str, bool, str]


def _run(name: str, fn) -> Check:
    try:
        detail = fn() or "ok"
        return (name, True, str(detail))
    except Exception as exc:  # noqa: BLE001 - report everything, never raise
        return (name, False, f"{type(exc).__name__}: {exc}")


# --- individual checks -----------------------------------------------------


def _check_qt() -> str:
    """PySide6 + shiboken6 + QtCharts all importable and usable."""
    import shiboken6  # noqa: F401  - the binding layer that went missing
    from PySide6 import QtCharts, QtCore, QtGui, QtWidgets  # noqa: F401

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = QtWidgets.QWidget()
    w.setWindowTitle("probe")
    chart = QtCharts.QChart()
    chart.setTitle("probe")
    return f"Qt {QtCore.qVersion()}"


def _check_reportlab() -> str:
    """reportlab AND its PIL dependency -- the first freezing bug."""
    import PIL  # noqa: F401
    import reportlab
    from reportlab.lib.pagesizes import A4  # noqa: F401

    return f"reportlab {reportlab.Version}"


def _check_engineering_core() -> str:
    """The cited core computes a real recommendation."""
    from pcis.core import heat_moisture_balance as hmb
    from pcis.core import recommendation_engine as re
    from pcis.equipment.fan_curve import FAN_CATALOG

    surfaces = [
        hmb.Surface("sidewalls", u_value=0.6, area_m2=350.0),
        hmb.Surface("ceiling", u_value=0.4, area_m2=1500.0),
    ]
    result = re.recommend(
        bird_count=20000, body_weight_kg=2.296,
        indoor_t_c=29.0, indoor_rh_pct=60.0,
        outdoor_t_c=35.0, outdoor_rh_pct=40.0,
        envelope_surfaces=surfaces, fan=FAN_CATALOG[0],
        design_static_pressure_pa=30.0, delta_t_c=3.0,
    )
    if result.fans_on < 1:
        raise AssertionError(f"implausible fan count {result.fans_on}")
    return f"{result.fans_on} fans, {result.governing_constraint}"


def _check_assets() -> str:
    """Bundled data resolves through sys._MEIPASS, not a source path."""
    from pcis import paths

    icon = paths.resource_path("assets/pcis.ico")
    if not icon.exists():
        raise FileNotFoundError(f"icon not bundled: {icon}")
    return f"icon {icon.stat().st_size} bytes"


def _check_data_dir() -> str:
    """The per-user data directory exists and is actually writable."""
    from pcis import paths

    d = paths.user_data_dir()
    d.mkdir(parents=True, exist_ok=True)
    probe = d / ".write-probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()
    return str(d)


def _check_settings() -> str:
    """First-run config creates settings and the working folders."""
    from pcis import config

    settings = config.load_settings()
    config.save_settings(settings)
    missing = [n for n in config.SUBDIRECTORIES
               if not (config.paths.user_data_dir() / n).is_dir()]
    if missing:
        raise AssertionError(f"missing folders: {missing}")
    return f"{len(settings)} keys"


def _check_database() -> str:
    """SQLAlchemy + its sqlite dialect (a hidden import) work."""
    from sqlalchemy.orm import Session

    from pcis.db.session import init_db, save_house_config
    from pcis.core import heat_moisture_balance as hmb

    engine = init_db(":memory:")
    with Session(engine) as s:
        save_house_config(s, "self-test", length_m=10.0, width_m=5.0, height_m=3.0,
                          surfaces=[hmb.Surface("wall", u_value=0.5, area_m2=10.0)])
        s.commit()
    return "sqlite dialect ok"


def _check_pdf_report() -> str:
    """A real PDF is produced, not merely imported."""
    from pcis.core import heat_moisture_balance as hmb
    from pcis.core import recommendation_engine as re
    from pcis.equipment.fan_curve import FAN_CATALOG
    from pcis.reports.pdf_report import generate_recommendation_report

    surfaces = [hmb.Surface("wall", u_value=0.6, area_m2=350.0)]
    result = re.recommend(
        bird_count=1000, body_weight_kg=2.0,
        indoor_t_c=25.0, indoor_rh_pct=60.0,
        outdoor_t_c=20.0, outdoor_rh_pct=50.0,
        envelope_surfaces=surfaces, fan=FAN_CATALOG[0],
        design_static_pressure_pa=30.0, delta_t_c=3.0,
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "probe.pdf"
        generate_recommendation_report(
            output_path=str(out), house_name="self-test", recommendation=result,
            bird_count=1000, body_weight_kg=2.0, indoor_t_c=25.0,
            indoor_rh_pct=60.0, outdoor_t_c=20.0, outdoor_rh_pct=50.0,
            breed="Ross 308",
        )
        size = out.stat().st_size
        if size < 1000:
            raise AssertionError(f"PDF suspiciously small ({size} bytes)")
    return f"{size} bytes"


def _check_main_window() -> str:
    """The real window constructs -- catches missing Qt plugins."""
    from PySide6.QtWidgets import QApplication

    from pcis.gui import style
    from pcis.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    style.apply_theme(app)
    w = MainWindow(db_path=":memory:")
    result = w.run_recommendation()
    if result is None:
        raise AssertionError("run_recommendation returned nothing")
    tabs = w.tabs.count()
    w.close()
    return f"{tabs} tabs, {result.fans_on} fans"


CHECKS = [
    ("Qt / PySide6 / shiboken6", _check_qt),
    ("ReportLab + PIL", _check_reportlab),
    ("Bundled assets", _check_assets),
    ("User data directory", _check_data_dir),
    ("Settings / first run", _check_settings),
    ("Database (sqlite dialect)", _check_database),
    ("Engineering core", _check_engineering_core),
    ("PDF report generation", _check_pdf_report),
    ("Main window", _check_main_window),
]


def run_self_test(verbose: bool = True) -> int:
    """Run every check. Returns 0 if all passed, 1 otherwise."""
    from pcis import version

    lines = [
        "=" * 62,
        f"PCIS self-test - {version.version_string()}",
        "=" * 62,
    ]
    results = [_run(name, fn) for name, fn in CHECKS]

    for name, ok, detail in results:
        lines.append(f"  [{'PASS' if ok else 'FAIL'}] {name:28} {detail}")

    failed = [r for r in results if not r[1]]
    lines.append("-" * 62)
    if failed:
        lines.append(f"RESULT: {len(failed)} of {len(results)} checks FAILED")
        lines.append("")
        lines.append("This build is not fit to ship. A PyInstaller build can")
        lines.append("succeed and still produce an application that cannot start;")
        lines.append("that is what these checks exist to catch.")
    else:
        lines.append(f"RESULT: all {len(results)} checks passed")
    lines.append("=" * 62)

    report = "\n".join(lines)
    if verbose:
        print(report, flush=True)
    try:
        import logging
        logging.getLogger(__name__).info("Self-test:\n%s", report)
    except Exception:
        pass
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run_self_test())
