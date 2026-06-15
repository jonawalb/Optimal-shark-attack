"""Unified roster loader: auto-detects HY-TEK PDF vs CSV input.

CSV schema (long-form): team,name,age,gender,event_id,time_seconds
where event_id is e.g. "G_9-10_50_FREE", "B_15-18_50_BACK", etc.
"""
from __future__ import annotations

from pathlib import Path

from osa.model.roster import Roster, build_roster
from osa.parsing.hytek_top_times import parse_top_times
from osa.data.synthetic import roster_from_csv


def load_roster(path: str | Path, team: str | None = None) -> Roster:
    """Load a roster from PDF (HY-TEK Top Times) or CSV.

    For PDF input, `team` is required (which team's swimmers to extract, since
    a Top Times PDF contains both teams).
    For CSV input, `team` is inferred from the file unless overridden.
    """
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        if team is None:
            raise ValueError("`team` is required for PDF input (e.g. 'OH')")
        entries = parse_top_times(p)
        return build_roster(entries, team=team)
    if p.suffix.lower() == ".csv":
        roster = roster_from_csv(p)
        if team is not None and roster.team != team:
            # filter to subset
            roster = Roster(team=team, swimmers=[s for s in roster.swimmers if s.team == team])
        return roster
    raise ValueError(f"unrecognized input format: {p.suffix} (expected .pdf or .csv)")


def filter_available(roster: Roster, available_names: set[str]) -> Roster:
    """Restrict roster to swimmers whose names appear in `available_names`.

    Name matching is case-insensitive and whitespace-tolerant.
    Returns a new Roster (does not mutate input).
    """
    norm = {n.strip().lower() for n in available_names}
    kept = [s for s in roster.swimmers if s.name.strip().lower() in norm]
    return Roster(team=roster.team, swimmers=kept)


def read_available_names(path: str | Path) -> set[str]:
    """Read a plain-text file of swimmer names, one per line."""
    return {
        line.strip()
        for line in Path(path).read_text().splitlines()
        if line.strip() and not line.startswith("#")
    }
