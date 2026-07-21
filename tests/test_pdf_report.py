"""Unit tests for pcis.reports.pdf_report.

Verifies the PDF actually builds and that its extracted text contains
the key figures from the underlying Recommendation -- i.e. that the
report is a faithful rendering, not just "doesn't crash".
"""

import os
import tempfile

import pytest

from pcis.core import heat_moisture_balance as hmb
from pcis.core import recommendation_engine as re
from pcis.equipment.cooling_pad import CELDEK_7090_15_150MM
from pcis.equipment.fan_curve import FAN_CATALOG
from pcis.reports.pdf_report import generate_recommendation_report

SURFACES = [
    hmb.Surface("sidewalls", u_value=0.6, area_m2=350.0),
    hmb.Surface("ceiling", u_value=0.4, area_m2=1500.0),
]


@pytest.fixture()
def recommendation():
    return re.recommend(
        bird_count=20000,
        body_weight_kg=2.5,
        indoor_t_c=29.0,
        indoor_rh_pct=60.0,
        outdoor_t_c=38.0,
        outdoor_rh_pct=30.0,
        envelope_surfaces=SURFACES,
        fan=FAN_CATALOG[1],
        design_static_pressure_pa=30.0,
        delta_t_c=3.0,
        cooling_pad=CELDEK_7090_15_150MM,
    )


def _extract_text(pdf_path: str) -> str:
    import pypdf

    reader = pypdf.PdfReader(pdf_path)
    return "\n".join(page.extract_text() for page in reader.pages)


def test_report_generates_a_nonempty_pdf_file(recommendation):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "report.pdf")
        result_path = generate_recommendation_report(
            output_path=path,
            house_name="Farm A - House 3",
            recommendation=recommendation,
            bird_count=20000,
            body_weight_kg=2.5,
            indoor_t_c=29.0,
            indoor_rh_pct=60.0,
            outdoor_t_c=38.0,
            outdoor_rh_pct=30.0,
            breed="Ross 308",
        )
        assert result_path == path
        assert os.path.exists(path)
        assert os.path.getsize(path) > 1000  # a real PDF, not an empty stub


def test_report_text_contains_key_figures(recommendation):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "report.pdf")
        generate_recommendation_report(
            output_path=path,
            house_name="Farm A - House 3",
            recommendation=recommendation,
            bird_count=20000,
            body_weight_kg=2.5,
            indoor_t_c=29.0,
            indoor_rh_pct=60.0,
            outdoor_t_c=38.0,
            outdoor_rh_pct=30.0,
            breed="Ross 308",
        )
        text = _extract_text(path)

        assert "Farm A - House 3" in text
        assert "20,000" in text
        assert str(recommendation.fans_on) in text
        assert "Ross 308" in text
        assert f"{recommendation.confidence_score:.0f}" in text
        assert "Bird Comfort Index" in text
        # First explanation line should appear verbatim (spot check
        # that the explanation list actually rendered, not just a
        # placeholder).
        first_line_fragment = recommendation.explanation[0][:30]
        assert first_line_fragment in text


def test_report_reflects_pads_off_case():
    result = re.recommend(
        bird_count=20000,
        body_weight_kg=2.5,
        indoor_t_c=18.0,
        indoor_rh_pct=60.0,
        outdoor_t_c=15.0,
        outdoor_rh_pct=55.0,
        envelope_surfaces=SURFACES,
        fan=FAN_CATALOG[1],
        design_static_pressure_pa=30.0,
        delta_t_c=3.0,
        cooling_pad=CELDEK_7090_15_150MM,
    )
    assert result.pads_on is False

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "report.pdf")
        generate_recommendation_report(
            output_path=path,
            house_name="Mild Day House",
            recommendation=result,
            bird_count=20000,
            body_weight_kg=2.5,
            indoor_t_c=18.0,
            indoor_rh_pct=60.0,
            outdoor_t_c=15.0,
            outdoor_rh_pct=55.0,
        )
        text = _extract_text(path)
        # "No" should appear for the pads-on row; house name always present
        assert "Mild Day House" in text
        assert "No" in text


def test_report_without_breed_omits_breed_row(recommendation):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "report.pdf")
        generate_recommendation_report(
            output_path=path,
            house_name="No Breed House",
            recommendation=recommendation,
            bird_count=20000,
            body_weight_kg=2.5,
            indoor_t_c=29.0,
            indoor_rh_pct=60.0,
            outdoor_t_c=38.0,
            outdoor_rh_pct=30.0,
        )
        text = _extract_text(path)
        assert "informational only" not in text
