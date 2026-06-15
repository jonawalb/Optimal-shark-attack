"""Parser for NVSL "Virtual Meet" result PDFs (web pages from mynvsl.com).

These are HEAD-TO-HEAD pairings of two teams' performances from past meets,
useful as "game film" on a future opponent. Format differs from HY-TEK
Top Times -- it's an HTML table printed to PDF with one row per finisher
showing rank, points, time, team, and swimmer name.

Pool course is typically 25 METERS (some 25 yd); times are NOT directly
comparable to SCY data without conversion. Each PDF's `Course:` header
tells us which.

We extract INDIVIDUAL EVENT entries only (relays in this format wrap names
across multiple lines in a way that's hard to parse robustly, and individual
times are sufficient to drive relay-leg selection in the optimizer).
"""
from __future__ import annotations

import re
from pathlib import Path

import pdfplumber

from osa.parsing.hytek_top_times import Entry, parse_time

# Event header e.g. "Boys Free 25M 8&U" or "Girls Back 50M 13-14"
_AGE_OPTIONS = r"(8&U|9-10|11-12|13-14|15-18)"
_STROKES_VM = {"Free": "FREE", "Back": "BACK", "Breast": "BREAST",
               "Fly": "FLY", "IM": "IM"}
_AGE_VM = {"8&U": "8U", "9-10": "9-10", "11-12": "11-12",
           "13-14": "13-14", "15-18": "15-18"}
EVENT_RE = re.compile(
    rf"^(Boys|Girls)\s+(Free|Back|Breast|Fly|IM)\s+(\d+)M\s+{_AGE_OPTIONS}\s*$"
)

# Entry row e.g. "1. (5) 18.87 XX John Q Doe"  or
#                "4. 22.45 YY Jane K Roe"   (no points)
# Name may be empty (wrapped to adjacent line).
ENTRY_RE = re.compile(
    r"^\s*(\d+)\.\s+"
    r"(?:\((\d+)\)\s+)?"
    r"(\d{0,2}:?\d{1,2}\.\d{2})\s+"
    r"([A-Z]{1,5})"               # accept single-letter team codes (e.g. "B" for Brandywine)
    r"(?:\s+(.+))?\s*$"
)

# Relay headers we ignore here.
RELAY_HEADER_RE = re.compile(
    r"^(Boys|Girls)\s+(?:Free|Medley)\s+\d+M\s+Relay"
)


def _parse_iso_date(month_day_year: str) -> str:
    """Convert 'June 21, 2025' or '07/05/2025' to ISO 'YYYY-MM-DD'. Fallback ''."""
    import re as _re
    months = {
        "January": "01", "February": "02", "March": "03", "April": "04",
        "May": "05", "June": "06", "July": "07", "August": "08",
        "September": "09", "October": "10", "November": "11", "December": "12",
    }
    m = _re.match(r"^([A-Z][a-z]+)\s+(\d{1,2}),?\s+(\d{4})$", month_day_year.strip())
    if m:
        return f"{m.group(3)}-{months.get(m.group(1), '01')}-{int(m.group(2)):02d}"
    return ""


def parse_virtual_meet(pdf_path: str | Path, team: str) -> list[Entry]:
    """Parse an NVSL Virtual Meet PDF and return entries for the named team.

    `team` is the abbreviation as it appears in the PDF (e.g. "OH", "VW", "VAC").
    Only INDIVIDUAL event entries are returned; relays are skipped.
    """
    pdf_path = Path(pdf_path)
    entries: list[Entry] = []
    current_event: tuple[str, str, int, str] | None = None
    in_relay = False

    with pdfplumber.open(pdf_path) as pdf:
        all_lines: list[str] = []
        for page in pdf.pages:
            text = page.extract_text() or ""
            all_lines.extend(text.splitlines())

    # Extract the source meet date for THIS team. Each PDF has two "Team: NAME"
    # blocks each followed by a "Meet Date:" line. We derive an abbreviation
    # from each team name (first letter of each word, or first two letters for
    # single-word teams) and match against the requested abbreviation.
    def _team_abbrev(name: str) -> str:
        words = name.split()
        if len(words) >= 2:
            return "".join(w[0].upper() for w in words)
        # single-word team: try first letter (e.g. Brandywine -> "B")
        return name[0].upper()

    meet_date_iso = ""
    for i, raw in enumerate(all_lines):
        line = raw.strip()
        if line.startswith("Team:"):
            team_name = line.split(":", 1)[1].strip()
            if not team_name:
                continue
            abbrev = _team_abbrev(team_name)
            # exact match OR first-2-letters match for single-word teams
            if abbrev != team and not (
                len(team_name.split()) == 1 and team_name.upper().startswith(team)
            ):
                continue
            for j in range(i, min(len(all_lines), i + 8)):
                if all_lines[j].strip().startswith("Meet Date:"):
                    meet_date_iso = _parse_iso_date(
                        all_lines[j].split(":", 1)[1].strip())
                    break
            if meet_date_iso:
                break

    # Pre-pass: when an entry line has no name (wrapped name), merge from
    # adjacent lines. We look at the previous and next lines and join any
    # text that doesn't look like an event header, entry, page chrome.
    for i, raw in enumerate(all_lines):
        line = raw.strip()
        if not line:
            continue
        # Skip page chrome
        if any(s in line for s in (
            "Welcome to the Northern Virginia", "SIGN IN", "SWIMMING DIVING",
            "© 2023 Northern Virginia", "VIRTUAL MEET:", "Competitor 1",
            "Competitor 2", "Team:", "Original Meet:", "Meet Date:",
            "Location:", "Course:", "Scores:", "askNVSL", "https://",
            "2026 UPDATED", "(pdf)",
        )):
            continue

        # Switch out of relay block when we hit an individual event header
        ev = EVENT_RE.match(line)
        if ev:
            gender_word, stroke_word, dist_s, age_s = ev.groups()
            current_event = (
                "G" if gender_word == "Girls" else "B",
                _AGE_VM[age_s],
                int(dist_s),
                _STROKES_VM[stroke_word],
            )
            in_relay = False
            continue

        if RELAY_HEADER_RE.match(line):
            in_relay = True
            current_event = None
            continue

        if in_relay or current_event is None:
            continue

        m = ENTRY_RE.match(line)
        if not m:
            continue
        rank_s, _pts, time_s, team_abbrev, name = m.groups()
        if team_abbrev != team:
            continue
        # Merge wrapped name if needed
        if not name or len(name.strip()) < 3:
            # search prev and next non-empty lines for the name parts
            name_parts: list[str] = []
            # previous non-empty line
            for j in range(i - 1, max(-1, i - 4), -1):
                cand = all_lines[j].strip()
                if cand and not EVENT_RE.match(cand) and not ENTRY_RE.match(cand):
                    name_parts.append(cand)
                    break
            # next non-empty line
            for j in range(i + 1, min(len(all_lines), i + 4)):
                cand = all_lines[j].strip()
                if cand and not EVENT_RE.match(cand) and not ENTRY_RE.match(cand) \
                   and not RELAY_HEADER_RE.match(cand):
                    name_parts.append(cand)
                    break
            name = " ".join(name_parts).strip()
        if not name:
            continue
        # Clean wrapping artifacts: "Foo-\nBar" became "Foo- Bar" -> "Foo-Bar"
        name = re.sub(r"-\s+", "-", name).strip()

        # Estimate swimmer age from the age group (we don't have exact age)
        # Use the upper bound so eligibility checks work conservatively.
        ag = current_event[1]
        est_age = {"8U": 8, "9-10": 10, "11-12": 12, "13-14": 14, "15-18": 17}[ag]
        gender, age_group, distance, stroke = current_event
        entries.append(Entry(
            gender=gender,
            age_group=age_group,
            distance=distance,
            stroke=stroke,
            rank=int(rank_s),
            exhibition=False,
            time_seconds=parse_time(time_s),
            swimmer_name=name,
            swimmer_age=est_age,
            team=team_abbrev,
            meet_date=meet_date_iso,
            course="M",  # all NVSL Virtual Meet PDFs we've seen are 25-meter course
        ))

    return entries
