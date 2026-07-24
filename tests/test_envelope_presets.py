"""Tests for the cited envelope U-value preset catalogue.

Pure logic -- no Qt. Verifies the R-value -> U-value conversion is
correct and that the catalogue is internally consistent (more
insulation => lower U), so the "defensible defaults" really are
defensible.
"""

import pytest

from pcis.core import envelope_presets as ep


def test_u_from_r_matches_hand_calc():
    # R-13 insulation + 0.85 film = 13.85 IP; * 0.176110 = 2.4391 m2K/W;
    # U = 1/2.4391 = 0.410.
    assert ep.u_from_r_ip(13.0) == pytest.approx(0.410, abs=0.001)
    assert ep.u_from_r_ip(21.0) == pytest.approx(0.260, abs=0.001)
    # Zero nominal insulation is just the surface films (a real, high U).
    assert ep.u_from_r_ip(0.0) == pytest.approx(6.68, abs=0.02)


def test_more_insulation_gives_lower_u():
    for r in (7.0, 13.0, 19.0, 30.0):
        assert ep.u_from_r_ip(r) < ep.u_from_r_ip(0.0)
    assert ep.u_from_r_ip(30.0) < ep.u_from_r_ip(13.0) < ep.u_from_r_ip(7.0)


def test_catalogue_is_non_empty_and_well_formed():
    assert ep.ENVELOPE_PRESETS
    for p in ep.ENVELOPE_PRESETS:
        assert p.label and p.default_name
        assert 0.0 < p.u_value < 10.0
        assert p.source  # every value is traceable


def test_lookup_by_label_round_trips():
    p = ep.ENVELOPE_PRESETS[2]
    assert ep.by_label(p.label) is p
    with pytest.raises(KeyError):
        ep.by_label("no such construction")


def test_defaults_come_from_the_catalogue():
    assert ep.DEFAULT_WALL in ep.ENVELOPE_PRESETS
    assert ep.DEFAULT_CEILING in ep.ENVELOPE_PRESETS
    assert ep.DEFAULT_WALL.default_name == "sidewalls"
    assert ep.DEFAULT_CEILING.default_name == "ceiling"
