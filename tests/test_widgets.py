"""Tests for shared Qt widgets that don't require QtCharts.

Run headlessly via the offscreen platform (conftest.qapp). These cover
the reusable `WeatherProfileTable` used by both the guided page and the
Recommendation tab's day schedule.
"""

import pytest

from pcis.gui import units
from pcis.gui.widgets import WeatherProfileTable


def test_seeds_a_default_day(qapp):
    t = WeatherProfileTable()
    rows = t.rows()
    assert len(rows) == len(WeatherProfileTable.DEFAULT_ROWS)
    label, t_c, rh = rows[0]
    assert label == "00:00"
    assert t_c == pytest.approx(24.0)
    assert rh == pytest.approx(80.0)


def test_add_and_remove_rows(qapp):
    t = WeatherProfileTable()
    n = t.table.rowCount()
    t.add_row("13:30", 31.0, 52.0)
    assert t.table.rowCount() == n + 1
    assert t.rows()[-1] == ("13:30", pytest.approx(31.0), pytest.approx(52.0))
    t.table.selectRow(t.table.rowCount() - 1)
    t._remove_selected()
    assert t.table.rowCount() == n


def test_unit_switch_round_trips_temperature_in_si(qapp):
    t = WeatherProfileTable()
    t.set_unit_system(units.IMPERIAL)   # display now Fahrenheit
    t.set_unit_system(units.METRIC)     # back to Celsius
    assert t.rows()[0][1] == pytest.approx(24.0, abs=0.05)


def test_bad_cell_raises_value_error(qapp):
    t = WeatherProfileTable()
    t.table.item(0, 1).setText("not-a-number")
    with pytest.raises(ValueError, match="must be numbers"):
        t.rows()
