"""NVSL dual-meet event catalog (per 2026 Handbook Rule 23, p. 83).

52 events total: 40 individual + 12 relays.
Pools are nominally 25 yd or 25 m; this catalog uses distance in pool lengths
which holds across both. The Top Times PDFs are short-course-yards (SCY).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Gender = Literal["G", "B"]
AgeGroup = Literal["8U", "9-10", "11-12", "13-14", "15-18"]
Stroke = Literal["FREE", "BACK", "BREAST", "FLY", "IM"]
EventKind = Literal["INDIVIDUAL", "MEDLEY_RELAY", "FREE_RELAY", "MIXED_AGE_FREE_RELAY"]

AGE_GROUPS: tuple[AgeGroup, ...] = ("8U", "9-10", "11-12", "13-14", "15-18")
INDIVIDUAL_STROKES: tuple[Stroke, ...] = ("FREE", "BACK", "BREAST", "FLY")
GENDERS: tuple[Gender, ...] = ("G", "B")

# Distance in pool lengths per (age_group, stroke) for individual events.
# 8&U: 1 length. 9-10 fly: 1 length. Everything else: 2 lengths.
INDIVIDUAL_LENGTHS: dict[tuple[AgeGroup, Stroke], int] = {}
for ag in AGE_GROUPS:
    for st in INDIVIDUAL_STROKES:
        if ag == "8U":
            INDIVIDUAL_LENGTHS[(ag, st)] = 1
        elif ag == "9-10" and st == "FLY":
            INDIVIDUAL_LENGTHS[(ag, st)] = 1
        else:
            INDIVIDUAL_LENGTHS[(ag, st)] = 2


@dataclass(frozen=True)
class Event:
    """One scoring event in an NVSL dual meet."""

    number: int                      # 1..52 in handbook order
    kind: EventKind
    gender: Gender
    age_group: AgeGroup | None       # None for mixed-age relays
    stroke: Stroke | None            # None for relays where multiple strokes
    lengths: int                     # pool lengths swum total

    @property
    def event_id(self) -> str:
        if self.kind == "INDIVIDUAL":
            return f"{self.gender}_{self.age_group}_{self.lengths * 25}_{self.stroke}"
        if self.kind == "MEDLEY_RELAY":
            return f"{self.gender}_{self.age_group}_MEDLEY_RELAY"
        if self.kind == "FREE_RELAY":
            return f"{self.gender}_{self.age_group}_FREE_RELAY"
        return f"{self.gender}_MIXED_AGE_FREE_RELAY"

    @property
    def is_relay(self) -> bool:
        return self.kind != "INDIVIDUAL"


def _build_catalog() -> list[Event]:
    events: list[Event] = []
    num = 1

    # Individual events: handbook orders all FREE first (by age, B then G alternating
    # per Rule 23 -- B is odd, G is even), then BACK, BREAST, FLY.
    for st in INDIVIDUAL_STROKES:
        for ag in AGE_GROUPS:
            for gen in ("B", "G"):
                events.append(Event(
                    number=num,
                    kind="INDIVIDUAL",
                    gender=gen,
                    age_group=ag,
                    stroke=st,
                    lengths=INDIVIDUAL_LENGTHS[(ag, st)],
                ))
                num += 1

    # Same-age, same-gender relays.
    # 8U: 4x25 FREESTYLE (100 total). No stroke legs - everyone swims free.
    # 9-10 / 11-12 / 13-14: 4x25 MEDLEY (back, breast, fly, free; 100 total).
    # 15-18: 4x50 MEDLEY (back, breast, fly, free; 200 total).
    for ag in AGE_GROUPS:
        for gen in ("B", "G"):
            lengths = 8 if ag == "15-18" else 4
            kind: EventKind = "FREE_RELAY" if ag == "8U" else "MEDLEY_RELAY"
            events.append(Event(
                number=num,
                kind=kind,
                gender=gen,
                age_group=ag,
                stroke=None,
                lengths=lengths,
            ))
            num += 1

    # Mixed-age freestyle relays: one swimmer per age band, 8 lengths total
    # (4 swimmers x 50 = 200 yards / meters). Order is 11-12 -> 10&U -> 13-14
    # -> 15-18 per Rule 12c(3).
    for gen in ("B", "G"):
        events.append(Event(
            number=num,
            kind="MIXED_AGE_FREE_RELAY",
            gender=gen,
            age_group=None,
            stroke=None,
            lengths=8,
        ))
        num += 1

    return events


EVENT_CATALOG: list[Event] = _build_catalog()
EVENT_BY_ID: dict[str, Event] = {e.event_id: e for e in EVENT_CATALOG}

# Medley relay leg order (USA Swimming): back, breast, fly, free.
MEDLEY_LEG_ORDER: tuple[Stroke, ...] = ("BACK", "BREAST", "FLY", "FREE")
# Free relay leg labels (8U same-age free relay): no stroke ordering, just slot.
FREE_RELAY_LEG_ORDER: tuple[str, ...] = ("LEG1", "LEG2", "LEG3", "LEG4")
# Mixed-age free relay age order (Rule 12c(3)).
MIXED_AGE_RELAY_ORDER: tuple[AgeGroup, ...] = ("11-12", "9-10", "13-14", "15-18")


# Scoring constants (Rule 15b).
INDIVIDUAL_PLACE_POINTS: tuple[int, int, int] = (5, 3, 1)
RELAY_PLACE_POINTS: tuple[int, int] = (5, 0)
TOTAL_MEET_POINTS = 420
CLINCH_POINTS = 211


# Per-swimmer caps (Rule 2c).
MAX_INDIVIDUAL_EVENTS_PER_SWIMMER = 2
MAX_AGE_GROUP_RELAYS_PER_SWIMMER = 1
# Mixed-age relay is in addition to the age-group relay slot.

# Per-team entry caps per event (Rule 3a).
MAX_ENTRIES_PER_INDIVIDUAL_EVENT = 3   # A / B / C
MAX_OFFICIAL_RELAYS_PER_EVENT = 1
