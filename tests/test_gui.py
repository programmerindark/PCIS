"""Smoke tests for the PySide6 GUI (pcis.gui.main_window).

These tests do NOT re-verify any engineering formula -- that is the
job of tests/test_recommendation_engine.py and friends. Their only
purpose is to confirm the GUI wiring itself: that widgets produce the
dict `recommend()` expects, that a run populates the results widgets,
that every run is logged to the database automatically (no button
required -- see `MainWindow._record_to_database`), and that
export-PDF / export-training-data actually complete.

Note on QMessageBox: `export_pdf` and `export_training_data` both show
a blocking `QMessageBox.information(...)` confirmation dialog after
finishing -- correct, desirable behaviour for an interactive user, but
a dialog with no user to click OK will hang forever under the
`offscreen` platform used for headless testing. Every test that
exercises those methods patches `QMessageBox.information` /
`QMessageBox.warning` to a no-op so the test can observe the return
value without blocking. This is a testability workaround, not a
production code change. `_record_to_database` itself shows no dialog
(that's the point -- it's silent/automatic), so tests that only run a
recommendation don't need this patch.
"""

from __future__ import annotations

import csv
import os
import tempfile
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QMessageBox, QWidget
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
    from pcis.core import envelope_presets as ep

    editor = EnvelopeSurfaceEditor()
    surfaces = editor.surfaces()
    assert [s.name for s in surfaces] == ["sidewalls", "ceiling"]
    # Seeded from the cited preset catalogue, not uncited guesses.
    assert surfaces[0].u_value == ep.DEFAULT_WALL.u_value
    assert surfaces[1].u_value == ep.DEFAULT_CEILING.u_value
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
# age-based weight auto-fill (Ross 308 growth curve)
# ----------------------------------------------------------------------


def test_default_age_auto_fills_weight_from_growth_curve(window):
    from pcis.core.growth_curve import ross_308_body_weight_kg

    expected = ross_308_body_weight_kg(window.age_spin.value())
    assert window.body_weight_spin.value() == pytest.approx(expected, abs=0.01)
    assert "auto-filled" in window.growth_curve_status_label.text()


def test_changing_age_updates_weight(window):
    # body_weight_spin is a 2-decimal QDoubleSpinBox, so the exact
    # growth-curve value (e.g. 0.062 kg) rounds to its precision --
    # tolerance reflects that display rounding, not an engineering one.
    window.age_spin.setValue(1)
    assert window.body_weight_spin.value() == pytest.approx(0.062, abs=0.01)

    window.age_spin.setValue(42)
    assert window.body_weight_spin.value() == pytest.approx(2.998, abs=0.01)


def test_age_outside_table_range_leaves_weight_untouched_and_warns(window):
    window.age_spin.setValue(10)
    weight_at_10 = window.body_weight_spin.value()

    window.age_spin.setValue(90)
    assert window.body_weight_spin.value() == pytest.approx(weight_at_10)
    assert "outside the published Aviagen Ross 308 table" in window.growth_curve_status_label.text()


def test_manual_weight_override_survives_until_age_changes_again(window):
    window.age_spin.setValue(35)
    window.body_weight_spin.setValue(9.99)
    assert window.body_weight_spin.value() == pytest.approx(9.99)
    # Only a further age change re-triggers auto-fill -- the override
    # itself doesn't get silently clobbered.
    window.age_spin.setValue(35)
    # Setting the same value doesn't emit valueChanged, so it should
    # still hold the manual override:
    assert window.body_weight_spin.value() == pytest.approx(9.99)
    window.age_spin.setValue(36)
    assert window.body_weight_spin.value() != pytest.approx(9.99)


# ----------------------------------------------------------------------
# run_recommendation
# ----------------------------------------------------------------------


def test_run_recommendation_populates_results_widgets(window):
    result = window.run_recommendation()
    assert result is not None
    assert result.fans_on >= 1
    assert window._metric_labels["fans"].text() == str(result.fans_on)
    assert window.explanation_list.count() == len(result.explanation)
    assert window.export_pdf_btn.isEnabled()


def test_unreachable_target_warning_banner_is_shown(window):
    # The whole point of the engine flag is that the operator sees it.
    window.outdoor_t_spin.set_si_value(45.0)
    result = window.run_recommendation()
    assert result.target_unreachable is True

    assert not window.warning_label.isHidden()
    text = window.warning_label.text()
    assert "TARGET NOT REACHABLE" in text
    assert "More fans will" in text


def test_no_unreachable_warning_when_target_is_reachable(window):
    window.indoor_t_spin.set_si_value(20.0)
    window.outdoor_t_spin.set_si_value(5.0)
    window.outdoor_rh_spin.setValue(70.0)
    result = window.run_recommendation()

    assert result.target_unreachable is False
    assert window.warning_label.isHidden()


def test_run_recommendation_with_bad_surface_shows_warning_and_returns_none(window):
    window.envelope_editor.table.item(0, 1).setText("garbage")
    with patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok) as mock_warn:
        result = window.run_recommendation()
    assert result is None
    mock_warn.assert_called_once()
    assert "must be numbers" in mock_warn.call_args.args[2]


def test_run_recommendation_with_bad_surface_does_not_record_anything(window):
    # A failed run has no valid outputs -- nothing should be logged.
    window.envelope_editor.table.item(0, 1).setText("garbage")
    with patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok):
        window.run_recommendation()
    with Session(window._engine) as session:
        assert session.query(HouseConfig).count() == 0
        assert session.query(RecommendationLog).count() == 0


# ----------------------------------------------------------------------
# automatic recording (no button -- every run_recommendation() call logs)
# ----------------------------------------------------------------------


def test_run_recommendation_automatically_persists_house_and_recommendation(window):
    # No QMessageBox patch needed: recording is silent, no dialog is shown.
    window.run_recommendation()

    with Session(window._engine) as session:
        houses = session.query(HouseConfig).all()
        recs = session.query(RecommendationLog).all()
    assert len(houses) == 1
    assert houses[0].name == "House 1"
    assert len(recs) == 1


def test_run_recommendation_updates_record_status_label(window):
    assert "Logged" not in window.record_status_label.text()
    window.run_recommendation()
    assert "Logged" in window.record_status_label.text()
    assert "House 1" in window.record_status_label.text()


def test_running_recommendation_twice_with_same_house_name_does_not_raise(window):
    # HouseConfig.name is unique -- a naive re-save on the second run
    # would raise an IntegrityError. get_or_create_house_config exists
    # precisely so the same house can be logged against repeatedly.
    window.run_recommendation()
    window.age_spin.setValue(21)
    window.run_recommendation()

    with Session(window._engine) as session:
        houses = session.query(HouseConfig).all()
        recs = session.query(RecommendationLog).all()
    assert len(houses) == 1  # still just one house, not two
    assert len(recs) == 2  # but two logged runs under it


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


# ----------------------------------------------------------------------
# ML data-logging: age_days wiring + export_training_data
# ----------------------------------------------------------------------


def test_gather_inputs_includes_age_days(window):
    window.age_spin.setValue(21)
    inputs = window.gather_inputs()
    assert inputs["age_days"] == 21


def test_run_recommendation_automatically_persists_age_days(window):
    window.age_spin.setValue(14)
    window.run_recommendation()

    with Session(window._engine) as session:
        log = session.query(RecommendationLog).one()
    assert log.age_days == 14


def test_export_training_data_with_explicit_path_writes_real_csv(window):
    window.age_spin.setValue(35)
    window.run_recommendation()  # logs automatically -- no save step needed
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "training_data.csv")
        with patch.object(QMessageBox, "information", return_value=QMessageBox.Ok) as mock_info:
            returned_path = window.export_training_data(path=out_path)
        mock_info.assert_called_once()

        assert returned_path == out_path
        assert os.path.exists(out_path)
        with open(out_path, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            rows = list(reader)
    assert rows[0][0] == "id"
    assert "age_days" in rows[0]
    assert len(rows) == 2  # header + 1 auto-logged recommendation


def test_export_training_data_noop_returns_none_without_explicit_path_and_no_dialog(window):
    # Simulates the user cancelling the QFileDialog: getSaveFileName returns
    # ("", "") so export_training_data should bail out without touching the DB.
    with patch("pcis.gui.main_window.QFileDialog.getSaveFileName", return_value=("", "")):
        result = window.export_training_data()
    assert result is None


# ----------------------------------------------------------------------
# Unit selector
#
# The contract that matters: switching units changes what is DISPLAYED
# and nothing else. The engineering core and the database must only
# ever see SI, or a unit bug becomes a wrong fan count.
# ----------------------------------------------------------------------


def _select_imperial(window):
    from pcis.gui import units as u

    idx = next(i for i in range(window.unit_combo.count())
               if window.unit_combo.itemData(i) is u.IMPERIAL)
    window.unit_combo.setCurrentIndex(idx)


def test_default_unit_system_is_metric(window):
    from pcis.gui import units as u

    assert window.unit_combo.currentData() is u.METRIC


def test_switching_to_imperial_changes_display_but_not_si_value(window):
    si_before = window.length_spin.si_value()
    displayed_before = window.length_spin.value()

    _select_imperial(window)

    assert window.length_spin.si_value() == pytest.approx(si_before)
    # 150 m displays as ~492 ft -- the number on screen must change.
    assert window.length_spin.value() != pytest.approx(displayed_before)
    # The box shows 2 decimals, so 492.1259... renders as 492.13. That
    # rounding is display-only -- si_value() above is still exact.
    assert window.length_spin.value() == pytest.approx(si_before / 0.3048, abs=0.01)


def test_toggling_units_twice_returns_the_exact_original_value(window):
    # The reason UnitAwareSpinBox stores exact SI rather than
    # converting the rounded display value back: without it, every
    # round trip nudges the number (150 -> 492.13 ft -> 150.0012 m)
    # and the drift compounds.
    si_before = window.length_spin.si_value()
    _select_imperial(window)
    window.unit_combo.setCurrentIndex(0)
    assert window.length_spin.si_value() == pytest.approx(si_before, rel=1e-12)


def test_gather_inputs_returns_si_regardless_of_selected_units(window):
    metric_inputs = window.gather_inputs()
    _select_imperial(window)
    imperial_inputs = window.gather_inputs()

    for key in ("length_m", "width_m", "height_m", "body_weight_kg",
                "indoor_t_c", "outdoor_t_c", "delta_t_c",
                "design_static_pressure_pa"):
        assert imperial_inputs[key] == pytest.approx(metric_inputs[key], rel=1e-9), key


def test_recommendation_is_identical_in_both_unit_systems(window):
    metric_result = window.run_recommendation()
    _select_imperial(window)
    imperial_result = window.run_recommendation()

    assert imperial_result.fans_on == metric_result.fans_on
    assert imperial_result.pads_on == metric_result.pads_on
    assert imperial_result.required_airflow_m3_per_h == pytest.approx(
        metric_result.required_airflow_m3_per_h
    )


def test_envelope_surfaces_stay_si_after_unit_switch(window):
    before = window.envelope_editor.surfaces()
    _select_imperial(window)
    after = window.envelope_editor.surfaces()

    assert len(before) == len(after)
    for b, a in zip(before, after):
        assert a.u_value == pytest.approx(b.u_value, rel=1e-6)
        assert a.area_m2 == pytest.approx(b.area_m2, rel=1e-6)


def test_temperature_difference_uses_delta_conversion_not_absolute(window):
    # 3 degC allowed rise must display as 5.4 degF, NOT 37.4 degF.
    _select_imperial(window)
    assert window.delta_t_spin.value() == pytest.approx(5.4, abs=0.01)


def test_unit_switch_redraws_the_last_result(window):
    window.run_recommendation()
    metric_airflow_text = window._metric_labels["airflow"].text()
    _select_imperial(window)
    assert window._metric_labels["airflow"].text() != metric_airflow_text
    assert "CFM" in window._metric_labels["airflow"].text()


# ----------------------------------------------------------------------
# Guided schedule tab (digital twin) -- replaced the old Schedule tab.
# The single-page flow lives on `window.guided`; its own logic is
# covered in depth in tests/test_guided.py. These tests check that it is
# wired into the main window and behaves through it.
# ----------------------------------------------------------------------


def test_guided_tab_seeds_a_default_profile(window):
    assert window.guided.profile_table.rowCount() > 0


def test_guided_build_produces_a_result_and_populates_blocks(window):
    result = window.guided.build_schedule()
    assert result is not None
    assert len(result.steps) == window.guided.profile_table.rowCount()
    assert window.guided.blocks_list.count() == len(result.blocks)
    assert not window.guided.blocks_list.isHidden()


def test_guided_build_reads_profile_in_si(window):
    _select_imperial(window)
    result = window.guided.build_schedule()
    # Row 0 seeded at 24 degC; must still be 24 degC after display
    # conversion round-trips through the table.
    assert result.steps[0].outdoor_t_c == pytest.approx(24.0, abs=0.05)


def test_guided_build_with_bad_cell_warns_and_returns_none(window):
    window.guided.profile_table.item(0, 1).setText("garbage")
    with patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok) as mock_warn:
        result = window.guided.build_schedule()
    assert result is None
    mock_warn.assert_called_once()


def test_guided_build_with_empty_profile_warns(window):
    window.guided.profile_table.setRowCount(0)
    with patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok) as mock_warn:
        result = window.guided.build_schedule()
    assert result is None
    mock_warn.assert_called_once()


def test_installed_fan_shortfall_surfaces_in_the_notes(window):
    window.guided.installed_fans_spin.setValue(1)
    window.guided.build_schedule()
    assert "WARNING" in window.guided.notes_label.text()


def test_recommendation_tab_day_schedule_populates_blocks(window):
    result = window.run_day_schedule()
    assert result is not None
    assert len(result.steps) == window.rec_profile.table.rowCount()
    assert window.rec_schedule_blocks.count() == len(result.blocks)
    assert not window.rec_schedule_blocks.isHidden()
    assert not window.rec_schedule_summary.isHidden()


def test_recommendation_tab_day_schedule_empty_warns(window):
    window.rec_profile.table.setRowCount(0)
    with patch.object(QMessageBox, "warning", return_value=QMessageBox.Ok) as mock_warn:
        result = window.run_day_schedule()
    assert result is None
    mock_warn.assert_called_once()


def test_comfort_chart_follows_the_unit_selector(window):
    # The chart showing Celsius while the header showed Fahrenheit was
    # worse than no chart: both numbers look authoritative.
    window.run_recommendation()
    metric_axis = window.comfort_chart.chart.axes()[1].titleText()
    _select_imperial(window)
    imperial_axis = window.comfort_chart.chart.axes()[1].titleText()
    assert "°C" in metric_axis
    assert "°F" in imperial_axis


def test_explanation_is_labelled_as_si(window):
    # The explanation text is intentionally NOT unit-converted, so it
    # must say so rather than silently disagreeing with the header.
    assert "SI" in window.explanation_units_hint.text()


# ----------------------------------------------------------------------
# Launchability
#
# These guard a failure mode unit tests otherwise miss entirely: the
# app can be 100% "passing" and still never open a window, because
# nothing in the test suite launches it the way a user does.
# ----------------------------------------------------------------------


def test_module_has_a_main_entry_point():
    from pcis.gui import main_window

    assert callable(main_window.main)


def test_module_calls_main_when_run_as_a_script():
    # `python -m pcis.gui.main_window` only opens a window if the
    # module actually invokes main() under a __main__ guard. Dropping
    # that block makes the app exit silently with no error to debug.
    import inspect

    from pcis.gui import main_window

    source = inspect.getsource(main_window)
    assert '__name__ == "__main__"' in source
    assert source.rstrip().endswith("main()")


# ----------------------------------------------------------------------
# UI audit regressions
#
# Each of these encodes a defect found by inspecting rendered output at
# the window's minimum size. They are cheap to run and guard failures
# that are invisible to functional tests -- the app worked correctly in
# every one of these cases, it just could not be read.
# ----------------------------------------------------------------------


def test_metrics_reflow_to_fewer_columns_when_narrow(window):
    # Equal columns at a narrow width crowded long captions ("GOVERNING
    # CONSTRAINT"/"CONFIDENCE") together; the panel must instead reflow.
    # Count-agnostic so adding metrics (air speed, heating, ...) can't
    # silently break this — given enough room every metric fits on one
    # row; squeezed, it wraps to fewer but never zero.
    panel = window.metrics_panel
    n = len(panel._cells)
    plenty = n * (panel.MIN_COLUMN_PX + panel._grid.horizontalSpacing()) + 50
    wide = panel.columns_for_width(plenty)
    narrow = panel.columns_for_width(panel.MIN_COLUMN_PX * 2)
    assert wide == n, "every metric should sit on one row when there is room"
    assert narrow < wide, "must reflow to fewer columns when the window is narrow"
    assert narrow >= 1

    # And the wiring actually applies it.
    panel.apply_width(600)
    assert panel._columns == panel.columns_for_width(600)


def test_every_metric_cell_meets_its_minimum_width(window):
    for cell in window.metrics_panel._cells:
        assert cell.minimumWidth() >= window.metrics_panel.MIN_COLUMN_PX


def test_chart_is_hidden_until_there_is_something_to_plot(window):
    # An empty chart frame with only a title reads as broken, and it ate
    # ~190px above the fold before the user had run anything.
    assert window.comfort_chart.isHidden()
    assert not window.empty_state_label.isHidden()
    window.run_recommendation()
    assert not window.comfort_chart.isHidden()
    assert window.empty_state_label.isHidden()


def test_guided_blocks_hidden_until_built(window):
    assert window.guided.blocks_list.isHidden()
    assert not window.guided.empty_label.isHidden()
    window.guided.build_schedule()
    assert not window.guided.blocks_list.isHidden()
    assert window.guided.empty_label.isHidden()


def test_every_user_facing_input_has_a_tooltip(window):
    from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QLineEdit, QSpinBox

    missing = []
    for cls in (QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox):
        for x in window.findChildren(cls):
            # A spinbox's internal QLineEdit is Qt plumbing, not a field.
            if isinstance(x, QLineEdit) and isinstance(x.parentWidget(), (QSpinBox, QDoubleSpinBox)):
                continue
            if not x.toolTip() and not x.accessibleName():
                missing.append(f"{cls.__name__}/{x.objectName() or 'unnamed'}")
    assert not missing, f"inputs with no tooltip or accessible name: {missing}"


def test_tables_allow_the_user_to_resize_columns(window):
    from PySide6.QtWidgets import QHeaderView

    for table in (
        window.envelope_editor.table,
        window.guided.envelope_editor.table,
        window.guided.profile_table,
    ):
        header = table.horizontalHeader()
        assert header.sectionResizeMode(0) == QHeaderView.Interactive
        assert header.stretchLastSection()


def test_no_widget_overflows_its_parent_at_minimum_size(window):
    from PySide6.QtWidgets import QAbstractScrollArea

    window.resize(window.minimumWidth(), window.minimumHeight())
    window.show()
    window.run_recommendation()
    window.guided.build_schedule()

    offenders = []
    for i in range(window.tabs.count()):
        window.tabs.setCurrentIndex(i)
        for child in window.findChildren(QWidget):
            parent = child.parentWidget()
            if parent is None or not child.isVisibleTo(window):
                continue
            anc, in_scroll = child, False
            while anc is not None:
                if isinstance(anc, QAbstractScrollArea):
                    in_scroll = True
                    break
                anc = anc.parentWidget()
            if in_scroll or parent.width() <= 0:
                continue
            g = child.geometry()
            if g.right() > parent.width() + 2 or g.bottom() > parent.height() + 2:
                offenders.append(f"{child.__class__.__name__} in {parent.__class__.__name__}")
    assert not offenders, f"widgets overflowing their parent: {offenders[:5]}"


# ----------------------------------------------------------------------
# History tab: review, tag and delete logged runs
# ----------------------------------------------------------------------


def _count_logs(window):
    from pcis.db.session import count_recommendation_logs
    with Session(window._engine) as s:
        return count_recommendation_logs(s)


def test_history_tab_lists_logged_runs(window):
    window.run_recommendation()
    window.run_recommendation()
    window._refresh_history()
    assert window.history_table.rowCount() == 2


def test_test_checkbox_excludes_run_from_real_dataset(window):
    window.test_run_checkbox.setChecked(True)
    window.run_recommendation()
    assert _count_logs(window) == (0, 1)


def test_untick_checkbox_logs_a_real_run(window):
    window.test_run_checkbox.setChecked(False)
    window.run_recommendation()
    assert _count_logs(window) == (1, 0)


def test_mark_selected_as_test_then_real(window):
    window.run_recommendation()
    window._refresh_history()
    window.history_table.selectRow(0)
    window._flag_selected_history(True)
    assert _count_logs(window) == (0, 1)
    window.history_table.selectRow(0)
    window._flag_selected_history(False)
    assert _count_logs(window) == (1, 0)


def test_delete_selected_removes_the_row(window):
    window.run_recommendation()
    window.run_recommendation()
    window._refresh_history()
    window.history_table.selectRow(0)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.Yes):
        window._delete_selected_history()
    assert window.history_table.rowCount() == 1
    assert sum(_count_logs(window)) == 1


def test_delete_is_cancellable(window):
    window.run_recommendation()
    window._refresh_history()
    window.history_table.selectRow(0)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.No):
        window._delete_selected_history()
    assert sum(_count_logs(window)) == 1


def test_export_real_data_excludes_test_rows(window):
    window.test_run_checkbox.setChecked(True)
    window.run_recommendation()
    window.test_run_checkbox.setChecked(False)
    window.run_recommendation()
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "real.csv")
        with patch.object(QMessageBox, "information", return_value=QMessageBox.Ok):
            window.export_training_data(path=out, exclude_test=True)
        with open(out, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))
    assert len(rows) == 2


def test_history_summary_counts_real_and_test(window):
    window.test_run_checkbox.setChecked(False)
    window.run_recommendation()
    window.test_run_checkbox.setChecked(True)
    window.run_recommendation()
    window._refresh_history()
    text = window.history_summary.text()
    assert "1 real" in text and "1 test" in text
