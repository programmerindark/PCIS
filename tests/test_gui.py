"""Smoke tests for the PySide6 GUI (pcis.gui.main_window).

These tests do NOT re-verify any engineering formula -- that is the
job of tests/test_recommendation_engine.py and friends. Their only
purpose is to confirm the GUI wiring itself: that widgets produce the
dict `recommend()` expects, that a run populates the results widgets,
and that save-to-database / export-PDF actually complete.

Note on QMessageBox: `save_to_database` and `export_pdf` both show a
blocking `QMessageBox.information(...)` confirmation dialog after
finishing -- correct, desirable behaviour for an interactive user, but
a dialog with no user to click OK will hang forever under the
`offscreen` platform used for headless testing. Every test that
exercises those methods patches `QMessageBox.information` /
`QMessageBox.warning` to a no-op so the test can observe the return
value without blocking. This is a testability workaround, not a
production code change.
"""

from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QMessageBox
from sqlalchemy.orm import Session

from pcis.db.models import HouseConfig, RecommendationLog
from pcis.gui.main_window import EnvelopeSurfaceEditor, MainWindow


@pytest.fixture()
def window(qapp):
    return MainWindow(db_path=":memory:")


# ----------------------------------------------------------------------
# EnvelopeSurfaceEditor
# ----------------------------------------------------------------------


def test_envelope_editor_default_rows_round_trip(qapp):
    editor = EnvelopeSurfaceEditor()
    surfaces = editor.surfaces()
    assert [s.name for s in surfaces] == ["sidewalls", "ceiling"]
    assert surfaces[0].u_value == 0.6
    assert surfaces[1].area_m2 == 1500.0


def test_envelope_editor_add_and_remove_row(qapp):
    editor = EnvelopeSurfaceEditor()
    editor.add_row("endwalls", 0.5, 60.0)
    assert editor.table.rowCount() == 3
    assert editor.surfaces()[2].name == "endwalls"

    editor.table.selectRow(2)
    editor.remove_selected()
    assert editor.table.rowCount() == 2


def test_envelope_editor_non_numeric_cell_raises_value_error(qapp):
    editor = EnvelopeSurfaceEditor()
    editor.table.item(0, 1).setText("not-a-number")
    with pytest.raises(ValueError, match="must be numbers"):
        editor.surfaces()


# ----------------------------------------------------------------------
# MainWindow construction / input gathering
# ----------------------------------------------------------------------


def test_main_window_constructs_with_in_memory_db(window):
    assert window.windowTitle().startswith("PCIS")
    assert window.fan_combo.count() > 0
    assert window.pad_combo.itemText(0) == "(no cooling pad installed)"


def test_gather_inputs_returns_expected_keys_and_defaults(window):
    inputs = window.gather_inputs()
    expected_keys = {
        "house_name", "length_m", "width_m", "height_m", "surfaces",
        "breed", "bird_count", "body_weight_kg", "indoor_t_c",
        "indoor_rh_pct", "outdoor_t_c", "outdoor_rh_pct", "delta_t_c",
        "outdoor_co2_ppm", "fan", "design_static_pressure_pa", "cooling_pad",
    }
    assert expected_keys.issubset(inputs.keys())
    assert inputs["house_name"] == "House 1"
    assert inputs["bird_count"] == 20000
    assert inputs["fan"] is not None
    assert inputs["cooling_pad"] is None  # default combo entry


# ----------------------------------------------------------------------
# run_recommendation
# ----------------------------------------------------------------------


def test_run_recommendation_populates_results_widgets(window):
    result = window.run_recommendation()
    assert result is not None
    assert result.fans_on >= 1
    assert "Fans ON" in window.results_label.text()
    assert window.explanation_list.count() == len(result.explanation)
    assert window.save_db_btn.isEnabled()
    assert window.export_pdf_btn.isEnabled()


def test_run_recommendation_with_bad_surface_shows_warning_and_returns_none(window):
    window.envelope_editor.table.item(0, 1).setText("garbage")
    with patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok) as mock_warn:
        result = window.run_recommendation()
    assert result is None
    mock_warn.assert_called_once()
    assert "must be numbers" in mock_warn.call_args.args[2]


# ----------------------------------------------------------------------
# save_to_database
# ----------------------------------------------------------------------


def test_save_to_database_persists_house_and_recommendation(window):
    window.run_recommendation()
    with patch.object(QMessageBox, "information", return_value=QMessageBox.Ok) as mock_info:
        window.save_to_database()
    mock_info.assert_called_once()

    with Session(window._engine) as session:
        houses = session.query(HouseConfig).all()
        recs = session.query(RecommendationLog).all()
    assert len(houses) == 1
    assert houses[0].name == "House 1"
    assert len(recs) == 1


def test_save_to_database_noop_before_any_recommendation_run(window):
    # No run_recommendation() call yet -- should return quietly, no dialog.
    with patch.object(QMessageBox, "information", return_value=QMessageBox.Ok) as mock_info:
        window.save_to_database()
    mock_info.assert_not_called()
    with Session(window._engine) as session:
        assert session.query(HouseConfig).count() == 0


# ----------------------------------------------------------------------
# export_pdf
# ----------------------------------------------------------------------


def test_export_pdf_with_explicit_path_writes_real_file(window):
    window.run_recommendation()
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "report.pdf")
        with patch.object(QMessageBox, "information", return_value=QMessageBox.Ok) as mock_info:
            returned_path = window.export_pdf(path=out_path)
        mock_info.assert_called_once()
        assert returned_path == out_path
        assert os.path.exists(out_path)
        assert os.path.getsize(out_path) > 1000


def test_export_pdf_noop_before_any_recommendation_run(window):
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "report.pdf")
        with patch.object(QMessageBox, "information", return_value=QMessageBox.Ok) as mock_info:
            result = window.export_pdf(path=out_path)
    assert result is None
    mock_info.assert_not_called()
    assert not os.path.exists(out_path)
