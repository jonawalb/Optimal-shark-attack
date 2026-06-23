"""Parser for HY-TEK Team Manager 'Individual Top Times' PDF reports.

Each report is a 2-column PDF listing every eligible swimmer for the meet,
grouped by event and ranked fastest-to-slowest. We crack the page in half by
x-coordinate, walk the columns top-to-bottom, and yield Entry records.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pdfplumber

# --- event normalization ---

AGE_GROUPS = {
    "8 & Under": "8U",
    "9-10": "9-10",
    "11-12": "11-12",
    "13-14": "13-14",
    None: "15-18",  # "Open" -- events with no age range printed
}

STROKES = {
    "Free": "FREE",
    "Back": "BACK",
    "Breast": "BREAST",
    "Fly": "FLY",
    "IM": "IM",
}

# Event header e.g. "Girls 8 & Under 25 Free" or "Boys 100 IM"
_AGE = r"(?:(8 & Under|9-10|11-12|13-14)\s+)?"
_DIST = r"(\d{2,3})"
_STROKE = r"(Free|Back|Breast|Fly|IM)"
EVENT_RE = re.compile(rf"^(Girls|Boys)\s+{_AGE}{_DIST}\s+{_STROKE}\s*$")

# Entry line e.g. "12* 1:02.38 S F  Lydia Marposon 9 OH"
ENTRY_RE = re.compile(
    r"^\s*(\d+)\*?\s+"                # rank (optional tie marker *)
    r"(x?)"                            # optional 'x' exhibition prefix
    r"(\d{0,2}:?\d{2}\.\d{2})\s+"     # time (M:SS.hh or SS.hh)
    r"[SLY]\s+[FPS]\s+"               # course (S/L/Y) and round (F/P/S) -- accept any
    r"(.+?)\s+"                        # name (greedy non-greedy to age)
    r"(\d{1,2})\s+"                   # age
    r"([A-Z]{1,5})\s*$"               # team abbrev
)

# Single-column "ladder" variant: no per-row team abbrev; trailing date+meet name.
# e.g. "1 21.24 S F Bella Dunn 8 6/13/2026 2026 OH Time Trials"
ENTRY_RE_LADDER = re.compile(
    r"^\s*(\d+)\*?\s+"                # rank
    r"(x?)"                            # optional 'x'
    r"(\d{0,2}:?\d{2}\.\d{2})\s+"     # time
    r"[SLY]\s+[FPS]\s+"               # course + round
    r"(.+?)\s+"                        # name
    r"(\d{1,2})\s+"                   # age
    r"(\d{1,2}/\d{1,2}/\d{2,4})\s+"   # date m/d/yyyy
    r".+$"                             # meet name (discarded)
)

# Team-header line "Orange Hunt Sharks [OH]" or similar.
TEAM_HEADER_RE = re.compile(r"\[([A-Z]{1,5})\]\s*$")

# Lines we know to skip (page headers, banners)
SKIP_PREFIXES = (
    "Licensed To:",
    "HY-TEK",
    "Individual T",   # title splits across columns: "Individual T" / "op Times"
    "op Times",
    "Number of Top Times",
)


@dataclass(frozen=True)
class Entry:
    """One swimmer's seed time for one event in one team's top-times report."""

    gender: str          # "G" or "B"
    age_group: str       # "8U", "9-10", "11-12", "13-14", "15-18"
    distance: int        # pool lengths × pool length (25 yd assumed; raw distance here)
    stroke: str          # "FREE", "BACK", "BREAST", "FLY", "IM"
    rank: int            # rank within event (1 = fastest)
    exhibition: bool     # True iff entry was 'x'-flagged
    time_seconds: float
    swimmer_name: str
    swimmer_age: int
    team: str            # "OH", "VAC", "M", "LG", "CH", ...
    meet_date: str = ""  # ISO date "YYYY-MM-DD" when known; "" if unknown
    course: str = "Y"    # "Y" for yards (HY-TEK default), "M" for meters

    @property
    def event_id(self) -> str:
        return f"{self.gender}_{self.age_group}_{self.distance}_{self.stroke}"


def parse_time(text: str) -> float:
    """Convert HY-TEK time string ('1:02.38' or '34.67') to seconds."""
    if ":" in text:
        mins, secs = text.split(":")
        return int(mins) * 60 + float(secs)
    return float(text)


def _parse_event_header(line: str) -> tuple[str, str, int, str] | None:
    """Parse 'Girls 9-10 50 Back' -> ('G', '9-10', 50, 'BACK')."""
    m = EVENT_RE.match(line.strip())
    if not m:
        return None
    gender_word, age_word, dist_word, stroke_word = m.groups()
    gender = "G" if gender_word == "Girls" else "B"
    age_group = AGE_GROUPS[age_word]
    return gender, age_group, int(dist_word), STROKES[stroke_word]


def _parse_entry(line: str, current_event: tuple[str, str, int, str],
                  default_team: str = "") -> Entry | None:
    """Parse one entry row using the regex; returns None if no match."""
    m = ENTRY_RE.match(line)
    if m:
        rank_s, x_flag, time_s, name, age_s, team = m.groups()
        meet_date = ""
    else:
        m = ENTRY_RE_LADDER.match(line)
        if not m:
            return None
        rank_s, x_flag, time_s, name, age_s, date_s = m.groups()
        team = default_team
        # convert m/d/yyyy -> yyyy-mm-dd
        try:
            mo, da, yr = date_s.split("/")
            if len(yr) == 2:
                yr = "20" + yr
            meet_date = f"{int(yr):04d}-{int(mo):02d}-{int(da):02d}"
        except Exception:
            meet_date = ""
    gender, age_group, distance, stroke = current_event
    return Entry(
        gender=gender,
        age_group=age_group,
        distance=distance,
        stroke=stroke,
        rank=int(rank_s),
        exhibition=(x_flag == "x"),
        time_seconds=parse_time(time_s),
        swimmer_name=name.strip(),
        swimmer_age=int(age_s),
        team=team,
        meet_date=meet_date,
    )


def _iter_column_lines(pdf_path: Path) -> Iterator[str]:
    """Yield text lines in column-major order across the whole PDF.

    Each page is split L/R at x = width/2; left column lines first, then right.
    """
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            mid = page.width / 2
            left = page.crop((0, 0, mid, page.height))
            right = page.crop((mid, 0, page.width, page.height))
            for col in (left, right):
                text = col.extract_text() or ""
                for raw in text.splitlines():
                    line = raw.strip()
                    if not line:
                        continue
                    if any(line.startswith(p) for p in SKIP_PREFIXES):
                        continue
                    yield line


def _iter_fullpage_lines(pdf_path: Path) -> Iterator[str]:
    """Yield text lines in natural order across the whole PDF (no column split).

    For single-column 'ladder' reports where ages/dates land in the right half
    of each text row.
    """
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            for raw in text.splitlines():
                line = raw.strip()
                if not line:
                    continue
                if any(line.startswith(p) for p in SKIP_PREFIXES):
                    continue
                yield line


def parse_top_times(pdf_path: str | Path) -> list[Entry]:
    """Parse a HY-TEK Individual Top Times PDF and return all entries.

    First tries the 2-column layout. If that yields no entries (single-column
    'ladder' report), falls back to full-page extraction and pulls the team
    abbreviation from a header line like "Orange Hunt Sharks [OH]".
    """
    pdf_path = Path(pdf_path)

    # First pass: 2-column layout
    entries: list[Entry] = []
    current_event: tuple[str, str, int, str] | None = None
    for line in _iter_column_lines(pdf_path):
        header = _parse_event_header(line)
        if header is not None:
            current_event = header
            continue
        if current_event is None:
            continue
        entry = _parse_entry(line, current_event)
        if entry is not None:
            entries.append(entry)
    if entries:
        return entries

    # Fallback: single-column ladder report. Pull team from header line.
    default_team = ""
    current_event = None
    for line in _iter_fullpage_lines(pdf_path):
        if not default_team:
            tm = TEAM_HEADER_RE.search(line)
            if tm:
                default_team = tm.group(1)
        header = _parse_event_header(line)
        if header is not None:
            current_event = header
            continue
        if current_event is None:
            continue
        entry = _parse_entry(line, current_event, default_team=default_team)
        if entry is not None:
            entries.append(entry)
    return entries
