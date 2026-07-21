"""PDF report generation for a recommendation_engine.recommend() result.

Uses ReportLab (platypus flowables) to produce a formatted engineering
summary: flock/house context, environmental conditions, the comfort
assessment, the ventilation/equipment recommendation, and the full
transparent engineering explanation (including confidence-score
deductions) -- nothing in the report is summarized away or hidden;
the PDF is a direct rendering of the same `Recommendation` object
produced by `pcis.core.recommendation_engine.recommend`.
"""

from __future__ import annotations

import datetime as dt

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from pcis.core.recommendation_engine import Recommendation

_STYLES = getSampleStyleSheet()
_TITLE_STYLE = ParagraphStyle(
    "PCISTitle", parent=_STYLES["Title"], fontSize=18, spaceAfter=4
)
_SUBTITLE_STYLE = ParagraphStyle(
    "PCISSubtitle", parent=_STYLES["Normal"], fontSize=10, textColor=colors.grey, spaceAfter=18
)
_SECTION_STYLE = ParagraphStyle(
    "PCISSection", parent=_STYLES["Heading2"], spaceBefore=14, spaceAfter=6
)
_BODY_STYLE = _STYLES["BodyText"]
_EXPLANATION_STYLE = ParagraphStyle(
    "PCISExplanation", parent=_STYLES["BodyText"], fontSize=9, leading=12
)
_DISCLAIMER_STYLE = ParagraphStyle(
    "PCISDisclaimer", parent=_STYLES["Normal"], fontSize=8, textColor=colors.grey, spaceBefore=18
)

_TABLE_STYLE = TableStyle(
    [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f6f7")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
)


def _kv_table(rows: list[tuple[str, str]]) -> Table:
    t = Table([("Parameter", "Value")] + rows, colWidths=[2.6 * inch, 3.6 * inch])
    t.setStyle(_TABLE_STYLE)
    return t


def generate_recommendation_report(
    output_path: str,
    house_name: str,
    recommendation: Recommendation,
    bird_count: int,
    body_weight_kg: float,
    indoor_t_c: float,
    indoor_rh_pct: float,
    outdoor_t_c: float,
    outdoor_rh_pct: float,
    breed: str | None = None,
) -> str:
    """Render a `Recommendation` (from `recommendation_engine.recommend`)
    to a formatted PDF report.

    Parameters
    ----------
    output_path : str
        Filesystem path to write the PDF to.
    house_name : str
        Label for the house/report header.
    recommendation : Recommendation
        The result of a `recommendation_engine.recommend(...)` call.
    bird_count, body_weight_kg : int, float
        Flock context (echoed for the report; must match what was
        passed into `recommend()` for the report to be accurate).
    indoor_t_c, indoor_rh_pct, outdoor_t_c, outdoor_rh_pct : float
        Environmental conditions used for the recommendation.
    breed : str, optional
        Informational breed label (see `pcis.db.models` note on breed
        not currently affecting the underlying engineering model).

    Returns
    -------
    str
        The output_path, for convenience/chaining.
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=LETTER,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        title=f"PCIS Report - {house_name}",
    )

    story = []

    story.append(Paragraph("PCIS Environmental &amp; Ventilation Report", _TITLE_STYLE))
    generated_at = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    story.append(Paragraph(f"House: {house_name}  |  Generated: {generated_at}", _SUBTITLE_STYLE))

    # --- Flock & house summary ---
    story.append(Paragraph("Flock Summary", _SECTION_STYLE))
    flock_rows = [
        ("Bird count", f"{bird_count:,}"),
        ("Body weight", f"{body_weight_kg:.2f} kg"),
    ]
    if breed:
        flock_rows.insert(0, ("Breed (informational only)", breed))
    story.append(_kv_table(flock_rows))

    # --- Environmental conditions ---
    story.append(Paragraph("Environmental Conditions", _SECTION_STYLE))
    story.append(
        _kv_table(
            [
                ("Indoor temperature", f"{indoor_t_c:.1f} °C"),
                ("Indoor relative humidity", f"{indoor_rh_pct:.0f} %"),
                ("Outdoor temperature", f"{outdoor_t_c:.1f} °C"),
                ("Outdoor relative humidity", f"{outdoor_rh_pct:.0f} %"),
                ("Supply air (post-pad if pads ON)", f"{recommendation.supply_air_t_c:.1f} °C / {recommendation.supply_air_rh_pct:.0f} %"),
            ]
        )
    )

    # --- Comfort assessment ---
    c = recommendation.comfort
    story.append(Paragraph("Comfort Assessment", _SECTION_STYLE))
    story.append(
        _kv_table(
            [
                ("Target temperature (Aviagen table)", f"{c.target_temp_c:.1f} °C"),
                ("Deviation from target", f"{c.deviation_c:+.1f} °C"),
                ("Temperature-humidity index (THI)", f"{c.thi:.1f} ({c.thi_class})"),
                ("Bird Comfort Index (0-100)", f"{c.comfort_index:.0f}"),
            ]
        )
    )
    story.append(
        Paragraph(
            "Note: the Bird Comfort Index is PCIS's own composite synthesis of the "
            "target-temperature deviation and THI metrics above, not a published/"
            "validated instrument. See comfort_engine.py for the individually-cited "
            "sources of its component metrics.",
            _EXPLANATION_STYLE,
        )
    )

    # --- Recommendation ---
    story.append(Paragraph("Recommendation", _SECTION_STYLE))
    story.append(
        _kv_table(
            [
                ("Fans ON", str(recommendation.fans_on)),
                ("Cooling pads ON", "Yes" if recommendation.pads_on else "No"),
                ("Required airflow", f"{recommendation.required_airflow_m3_per_h:,.0f} m³/h"),
                ("Governing constraint", recommendation.governing_constraint.replace("_", " ").title()),
                ("Confidence score", f"{recommendation.confidence_score:.0f} / 100"),
            ]
        )
    )

    # --- Engineering explanation ---
    story.append(Paragraph("Engineering Explanation", _SECTION_STYLE))
    story.append(
        ListFlowable(
            [ListItem(Paragraph(line, _EXPLANATION_STYLE)) for line in recommendation.explanation],
            bulletType="bullet",
        )
    )

    story.append(Spacer(1, 0.3 * inch))
    story.append(
        Paragraph(
            "Generated by PCIS (Poultry Climate Intelligence System). Figures marked "
            "as assumptions or design-point estimates in the explanation above should "
            "be verified against site-specific data before being relied on for "
            "critical decisions. See PROGRESS.md in the project repository for full "
            "source citations and known limitations of each underlying model.",
            _DISCLAIMER_STYLE,
        )
    )

    doc.build(story)
    return output_path
