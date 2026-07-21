"""Tests for packaging-support modules: paths, config, version, updates.

These guard behaviour that only manifests in a FROZEN build, where it
is hardest to debug -- a windowed executable that writes to the wrong
place, or dies silently, gives the user nothing to report.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcis import config, logging_setup, paths, update_service, version


# --- paths -----------------------------------------------------------------


def test_source_runs_keep_the_old_database_location():
    # Development and the test suite must be unaffected by the frozen-build
    # relocation.
    assert paths.default_database_path() == "pcis.db"
    assert paths.is_frozen() is False


def test_frozen_builds_use_the_user_data_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "is_frozen", lambda: True)
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path / "PCIS")
    db = Path(paths.default_database_path())
    assert db.parent == tmp_path / "PCIS"
    assert db.parent.is_dir(), "the directory must be created, not just named"


def test_user_data_dir_is_absolute():
    assert paths.user_data_dir().is_absolute()


def test_resource_path_resolves_bundled_assets():
    # The icon must be findable from source; in a frozen build the same
    # call resolves against sys._MEIPASS.
    assert paths.resource_path("assets/pcis.ico").exists()


# --- version ---------------------------------------------------------------


def test_version_string_is_dotted_numeric():
    parts = version.VERSION.split(".")
    assert len(parts) == 3 and all(p.isdigit() for p in parts)


def test_development_builds_are_labelled_as_such():
    # An About dialog that cannot distinguish a dev build from a release
    # makes bug reports ambiguous.
    assert "development build" in version.version_string()


def test_full_version_info_has_every_field():
    info = version.full_version_info()
    assert set(info) == {"version", "build_date", "git_commit"}
    assert all(info.values())


# --- config ----------------------------------------------------------------


@pytest.fixture()
def isolated_config(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path / "PCIS")
    return tmp_path / "PCIS"


def test_first_run_creates_settings_and_directories(isolated_config):
    settings = config.load_settings()
    assert settings == config.DEFAULT_SETTINGS
    assert (isolated_config / config.SETTINGS_FILENAME).exists()
    for name in config.SUBDIRECTORIES:
        assert (isolated_config / name).is_dir(), name


def test_settings_round_trip(isolated_config):
    settings = config.load_settings()
    settings["unit_system"] = "imperial"
    config.save_settings(settings)
    assert config.load_settings()["unit_system"] == "imperial"


def test_corrupt_settings_are_backed_up_not_lost(isolated_config):
    config.load_settings()
    config.settings_path().write_text("{ this is not json", encoding="utf-8")

    settings = config.load_settings()
    assert settings == config.DEFAULT_SETTINGS, "must fall back to defaults"
    assert config.settings_path().with_suffix(".json.corrupt").exists(), (
        "the unreadable file must be kept, not silently deleted"
    )


def test_settings_from_an_older_version_gain_new_keys(isolated_config):
    # Simulate a file written before a key existed.
    config.ensure_directories()
    config.settings_path().write_text(json.dumps({"unit_system": "imperial"}), encoding="utf-8")
    settings = config.load_settings()
    assert settings["unit_system"] == "imperial"      # preserved
    assert "theme" in settings                        # merged forward


def test_settings_cannot_override_engineering_constants():
    # Config is presentation and file locations only. A settings file
    # that could change a published Aviagen figure would break the
    # guarantee that every number traces to a cited source.
    forbidden = {"target_temp", "efficiency", "airflow", "u_value",
                 "co2", "thi", "confidence", "fan"}
    for key in config.DEFAULT_SETTINGS:
        assert not any(f in key.lower() for f in forbidden), key


# --- logging ---------------------------------------------------------------


def test_log_path_is_under_the_logs_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, "user_data_dir", lambda: tmp_path / "PCIS")
    assert logging_setup.log_file_path().parent.name == "logs"


def test_exception_hook_installs_and_delegates(monkeypatch):
    import sys

    original = sys.excepthook
    try:
        logging_setup.install_exception_hook()
        assert sys.excepthook is not original
        # KeyboardInterrupt must pass through unchanged, not raise a dialog.
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
    finally:
        sys.excepthook = original


# --- update service --------------------------------------------------------


def test_default_update_service_never_reports_an_update():
    service = update_service.get_update_service()
    assert isinstance(service, update_service.NullUpdateService)
    assert service.check_for_update() is None


@pytest.mark.parametrize("candidate, current, expected", [
    ("1.10.0", "1.9.0", True),    # numeric, not lexicographic
    ("1.0.1", "1.0.0", True),
    ("2.0.0", "1.9.9", True),
    ("v1.2.0", "1.1.0", True),    # tolerates a leading v
    ("1.0.0", "1.0.0", False),
    ("0.9.0", "1.0.0", False),
    ("1.0", "1.0.0", False),      # shorter form, equal value
])
def test_version_comparison_is_numeric(candidate, current, expected):
    assert update_service.UpdateService.is_newer(candidate, current) is expected


def test_update_service_is_abstract():
    with pytest.raises(TypeError):
        update_service.UpdateService()


# --- self-test -------------------------------------------------------------


def test_self_test_passes_from_source(qapp):
    # If this fails from source it will certainly fail when frozen.
    from pcis import self_test

    assert self_test.run_self_test(verbose=False) == 0


def test_self_test_covers_every_subsystem_that_has_broken_when_frozen():
    from pcis import self_test

    names = " ".join(n for n, _ in self_test.CHECKS).lower()
    # reportlab->PIL and PySide6->shiboken6 are the two real bugs found
    # by launching a frozen build; both must stay covered.
    assert "reportlab" in names and "pil" in names
    assert "shiboken6" in names
    for expected in ("asset", "data directory", "settings", "database", "pdf", "window"):
        assert expected in names, expected


def test_self_test_reports_failures_rather_than_raising(monkeypatch):
    from pcis import self_test

    def boom():
        raise RuntimeError("simulated packaging failure")

    monkeypatch.setattr(self_test, "CHECKS", [("Deliberate failure", boom)])
    # Must return non-zero, not propagate -- build.bat reads the exit code.
    assert self_test.run_self_test(verbose=False) == 1
