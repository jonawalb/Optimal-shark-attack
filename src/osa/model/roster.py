"""Team rosters built from parsed HY-TEK Top Times entries.

A Swimmer aggregates one person's best times across all events they've swum
this season. Eligibility flows from (a) having a recorded time and (b) the
NVSL swim-up rule -- swimmers may compete in their own or any higher age
group's individual events.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from osa.parsing.hytek_top_times import Entry
from osa.rules.events import AGE_GROUPS, AgeGroup, Gender, INDIVIDUAL_STROKES, Stroke


def _age_group_for_age(age: int) -> AgeGroup:
    """Map a swimmer's age to their *natural* NVSL age group (Rule 2b)."""
    if age <= 8:
        return "8U"
    if age <= 10:
        return "9-10"
    if age <= 12:
        return "11-12"
    if age <= 14:
        return "13-14"
    return "15-18"


_AGE_GROUP_ORDER = {ag: i for i, ag in enumerate(AGE_GROUPS)}


@dataclass(frozen=True)
class Swimmer:
    """One swimmer's best season-best time per event."""

    name: str
    age: int
    gender: Gender
    team: str
    # event_id -> best time in seconds (lower = faster). Only events they've actually swum.
    best_times: dict[str, float] = field(default_factory=dict)

    @property
    def natural_age_group(self) -> AgeGroup:
        return _age_group_for_age(self.age)

    def eligible_age_groups(self) -> list[AgeGroup]:
        """Own age group and any higher group (swim-up allowed; Rule 2c)."""
        start = _AGE_GROUP_ORDER[self.natural_age_group]
        return list(AGE_GROUPS[start:])

    def time_for(self, event_id: str) -> float | None:
        return self.best_times.get(event_id)


@dataclass
class Roster:
    """All swimmers belonging to one team."""

    team: str
    swimmers: list[Swimmer]

    def by_name(self, name: str) -> Swimmer | None:
        for s in self.swimmers:
            if s.name == name:
                return s
        return None

    def filter(self, gender: Gender | None = None) -> list[Swimmer]:
        if gender is None:
            return list(self.swimmers)
        return [s for s in self.swimmers if s.gender == gender]


def _swimmer_key(entry: Entry) -> tuple[str, int, str]:
    """Identity key: name + age + team. Catches one-off typos via age agreement."""
    return (entry.swimmer_name, entry.swimmer_age, entry.team)


def build_roster(entries: Iterable[Entry], team: str) -> Roster:
    """Build a Roster for one team from a stream of parsed entries.

    Aggregates each swimmer's best time per event. If the same (name, age, team)
    appears in multiple entries (one per event), all are merged. If a swimmer
    appears with multiple ages across different PDFs, they are treated as
    separate people (the season is short enough that age shouldn't change).
    """
    grouped: dict[tuple[str, int, str], dict] = defaultdict(
        lambda: {"gender": None, "times": {}}
    )
    for e in entries:
        if e.team != team:
            continue
        key = _swimmer_key(e)
        bucket = grouped[key]
        bucket["gender"] = e.gender
        existing = bucket["times"].get(e.event_id)
        if existing is None or e.time_seconds < existing:
            bucket["times"][e.event_id] = e.time_seconds

    swimmers: list[Swimmer] = []
    for (name, age, t), bucket in grouped.items():
        swimmers.append(Swimmer(
            name=name,
            age=age,
            gender=bucket["gender"],
            team=t,
            best_times=dict(bucket["times"]),
        ))

    return Roster(team=team, swimmers=swimmers)


def merge_rosters(*rosters: Roster) -> Roster:
    """Combine multiple Roster snapshots of the SAME team into one.

    Useful for synthesizing a season-long view from the 4 weekly Top Times PDFs:
    keeps each swimmer's best across all snapshots.
    """
    assert len(rosters) >= 1
    team = rosters[0].team
    assert all(r.team == team for r in rosters)

    merged: dict[tuple[str, int], Swimmer] = {}
    for r in rosters:
        for s in r.swimmers:
            key = (s.name, s.age)
            if key not in merged:
                merged[key] = s
                continue
            cur = merged[key]
            combined_times = dict(cur.best_times)
            for ev, t in s.best_times.items():
                if ev not in combined_times or t < combined_times[ev]:
                    combined_times[ev] = t
            merged[key] = Swimmer(
                name=s.name, age=s.age, gender=s.gender, team=team,
                best_times=combined_times,
            )
    return Roster(team=team, swimmers=list(merged.values()))
