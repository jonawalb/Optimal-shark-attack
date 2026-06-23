"""Render the solo lineup txt into a clean printable PDF."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)


EVENT_LINE = re.compile(
    r"^\s*#\s*(\d+)\s+([A-Z0-9_\-]+)\s+(.*)$"
)
ENTRY_RE = re.compile(
    r"([ABC])\s+(\d{0,2}:?\d{2}\.\d{2})\s+([^A-Z]?[A-Z][^AB]*?)(?=\s+[ABC]\s+\d|$)"
)
RELAY_HEADER = re.compile(
    r"^\s*#\s*(\d+)\s+([A-Z0-9_\-]+)\s+total\s+(\S+)\s*$"
)
RELAY_LEG = re.compile(
    r"^\s+(\S+)\s+(\d{0,2}:?\d{2}\.\d{2})\s+(.+?)\s*$"
)


PRETTY = {
    "B": "Boys",
    "G": "Girls",
    "8U": "8 & Under",
    "9-10": "9-10",
    "11-12": "11-12",
    "13-14": "13-14",
    "15-18": "15-18",
    "FREE": "Free",
    "BACK": "Back",
    "BREAST": "Breast",
    "FLY": "Fly",
    "IM": "IM",
    "MEDLEY": "Medley",
}


def pretty_event(eid: str) -> str:
    parts = eid.split("_")
    if "MEDLEY" in parts and "RELAY" in parts:
        # B_8U_MEDLEY_RELAY
        gender, age, _, _ = parts
        return f"{PRETTY[gender]} {PRETTY[age]} Medley Relay"
    if "MIXED" in parts:
        gender = parts[0]
        return f"{PRETTY[gender]} Mixed-Age Free Relay"
    # individual: gender_age_dist_stroke
    gender, age, dist, stroke = parts
    return f"{PRETTY[gender]} {PRETTY[age]} {dist} {PRETTY[stroke]}"


def parse_individual(rest: str) -> list[tuple[str, str, str]]:
    """Pull (slot, time, name) triples out of an A/B/C line."""
    # Split on the slot-letter markers
    out = []
    # tokens: "A 21.52 Hudson Smith  B 24.39 Aiden DeMarco  C 25.22 Levi Bassler"
    chunks = re.split(r"\s{2,}(?=[ABC]\s)", rest.strip())
    for c in chunks:
        m = re.match(r"([ABC])\s+(\S+)\s+(.+)$", c.strip())
        if m:
            out.append((m.group(1), m.group(2), m.group(3).strip()))
    return out


def parse_lineup(path: Path):
    """Yield ('event', num, name, [(slot,time,swimmer),...]) and ('relay', num, name, total, [legs]) records."""
    lines = path.read_text().splitlines()
    records = []
    i = 0
    while i < len(lines):
        line = lines[i]
        rh = RELAY_HEADER.match(line)
        if rh:
            num = int(rh.group(1))
            eid = rh.group(2)
            total = rh.group(3)
            legs = []
            j = i + 1
            while j < len(lines):
                lm = RELAY_LEG.match(lines[j])
                if not lm:
                    break
                legs.append((lm.group(1), lm.group(2), lm.group(3).strip()))
                j += 1
            records.append(("relay", num, eid, total, legs))
            i = j
            continue
        em = EVENT_LINE.match(line)
        if em and "total" not in line and "MEDLEY" not in em.group(2) and "MIXED" not in em.group(2):
            num = int(em.group(1))
            eid = em.group(2)
            entries = parse_individual(em.group(3))
            records.append(("event", num, eid, None, entries))
        i += 1
    return records


def render(lineup_path: Path, pdf_path: Path) -> None:
    records = parse_lineup(lineup_path)
    individuals = [r for r in records if r[0] == "event"]
    relays = [r for r in records if r[0] == "relay"]

    # Reorganize: girls first by age (8U,9-10,11-12,13-14,15-18), then boys,
    # strokes within each group in FREE,BACK,BREAST,FLY order. Renumber 1..40.
    gender_order = {"G": 0, "B": 1}
    age_order = {"8U": 0, "9-10": 1, "11-12": 2, "13-14": 3, "15-18": 4}
    stroke_order = {"FREE": 0, "BACK": 1, "BREAST": 2, "FLY": 3}

    def ind_key(rec):
        eid = rec[2]
        g, age, _dist, stroke = eid.split("_")
        return (gender_order[g], age_order[age], stroke_order[stroke])

    individuals = sorted(individuals, key=ind_key)
    individuals = [("event", i + 1, r[2], r[3], r[4])
                   for i, r in enumerate(individuals)]

    # Relays: girls first by age (medley then mixed-age free), then boys.
    def relay_key(rec):
        eid = rec[2]
        parts = eid.split("_")
        if "MIXED" in parts:
            g = parts[0]
            return (gender_order[g], 99, 1)  # mixed-age last within gender
        g, age, _stroke, _relay = parts
        return (gender_order[g], age_order[age], 0)

    relays = sorted(relays, key=relay_key)
    relays = [("relay", 41 + i, r[2], r[3], r[4])
              for i, r in enumerate(relays)]

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=landscape(letter),
        leftMargin=0.4 * inch, rightMargin=0.4 * inch,
        topMargin=0.4 * inch, bottomMargin=0.4 * inch,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "title", parent=styles["Title"], fontSize=18, spaceAfter=4,
        alignment=1,
    )
    sub_style = ParagraphStyle(
        "sub", parent=styles["Normal"], fontSize=10, alignment=1,
        textColor=colors.grey, spaceAfter=10,
    )
    section_style = ParagraphStyle(
        "section", parent=styles["Heading2"], fontSize=13,
        textColor=colors.HexColor("#003f7f"),
        spaceBefore=10, spaceAfter=6,
    )

    story = []
    story.append(Paragraph("Orange Hunt Sharks — Optimal Lineup", title_style))
    story.append(Paragraph(
        "Opponent-agnostic best lineup &mdash; fastest season times (PR aggregation)",
        sub_style,
    ))

    # ---- Individual events table ----
    story.append(Paragraph("Individual Events", section_style))
    header = ["#", "Event", "A — fastest", "B — second", "C — third"]
    data = [header]
    for _kind, num, eid, _none, entries in individuals:
        ev_name = pretty_event(eid)
        cells = ["", "", ""]
        for slot, t, name in entries:
            idx = "ABC".index(slot)
            cells[idx] = f"{t}  {name}"
        data.append([str(num), ev_name] + cells)

    tbl = Table(
        data,
        colWidths=[0.35 * inch, 2.05 * inch, 2.55 * inch, 2.55 * inch, 2.55 * inch],
        repeatRows=1,
    )
    tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#003f7f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 8.5),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
            [colors.white, colors.HexColor("#f0f4fa")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story.append(tbl)

    story.append(PageBreak())

    # ---- Relays ----
    story.append(Paragraph("Relays", section_style))
    rheader = ["#", "Event", "Total", "Leg 1", "Leg 2", "Leg 3", "Leg 4"]
    rdata = [rheader]
    for _kind, num, eid, total, legs in relays:
        leg_cells = []
        for label, t, name in legs:
            leg_cells.append(f"{label}: {t}\n{name}")
        while len(leg_cells) < 4:
            leg_cells.append("")
        rdata.append([str(num), pretty_event(eid), total] + leg_cells)

    rtbl = Table(
        rdata,
        colWidths=[0.35 * inch, 2.1 * inch, 0.7 * inch,
                   1.8 * inch, 1.8 * inch, 1.8 * inch, 1.8 * inch],
        repeatRows=1,
    )
    rtbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7a1f1f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (2, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
            [colors.white, colors.HexColor("#fbeeee")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(rtbl)

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "Source: Optimal Shark Attack solo optimizer (PR-aggregation MILP). "
        "Constraints: 2-event cap, no stroke repeat, NVSL swim-up rules. "
        "Times in seconds; relay totals are seed sums (no exchange).",
        ParagraphStyle("foot", parent=styles["Normal"], fontSize=8,
                       textColor=colors.grey),
    ))

    doc.build(story)


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("lineup_06212026.txt")
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".pdf")
    render(src, out)
    print(f"wrote {out}")
