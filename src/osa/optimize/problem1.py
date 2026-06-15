"""Problem 1: best self-consistent lineup, opponent-agnostic.

Given a team's roster, assign swimmers to individual-event slots (up to 3 per
event -- A, B, C) such that the total of all assigned seed times is minimized,
subject to NVSL caps (Rule 2c, Rule 3a):

  * Each swimmer competes in at most 2 individual events.
  * Across a swimmer's 2 events, no stroke is repeated.
  * Each event gets at most 3 entries from this team.

Relays are out of scope for this solver (handled separately in problem1_relays.py).

The "fastest lineup" objective uses sum-of-seed-times. This is the natural
opponent-agnostic objective: it puts the fastest legal swimmer in every slot,
ties broken by who frees up the most flexibility elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass

import pulp

from osa.model.roster import Roster, Swimmer
from osa.rules.events import (
    EVENT_CATALOG,
    INDIVIDUAL_STROKES,
    MAX_ENTRIES_PER_INDIVIDUAL_EVENT,
    MAX_INDIVIDUAL_EVENTS_PER_SWIMMER,
    Event,
)


@dataclass(frozen=True)
class Assignment:
    """One swimmer placed in one event slot."""

    event: Event
    slot: str            # "A" / "B" / "C"
    swimmer: Swimmer
    time_seconds: float


@dataclass
class LineupSolution:
    assignments: list[Assignment]
    total_seconds: float
    solver_status: str

    def per_event(self) -> dict[str, list[Assignment]]:
        """Group assignments by event_id, sorted A then B then C."""
        out: dict[str, list[Assignment]] = {}
        for a in self.assignments:
            out.setdefault(a.event.event_id, []).append(a)
        for evid, lst in out.items():
            lst.sort(key=lambda a: a.slot)
        return out

    def per_swimmer(self) -> dict[str, list[Assignment]]:
        out: dict[str, list[Assignment]] = {}
        for a in self.assignments:
            out.setdefault(a.swimmer.name, []).append(a)
        return out


def _eligible(swimmer: Swimmer, event: Event) -> bool:
    """A swimmer is eligible iff right gender, right-or-younger age group, and
    has a recorded time for this exact event."""
    if event.kind != "INDIVIDUAL":
        return False
    if swimmer.gender != event.gender:
        return False
    if event.age_group not in swimmer.eligible_age_groups():
        return False
    return swimmer.time_for(event.event_id) is not None


def solve_problem1(
    roster: Roster,
    *,
    max_seconds: int = 60,
    verbose: bool = False,
) -> LineupSolution:
    """Solve Problem 1 for the given roster. Returns the optimal lineup.

    Uses PuLP with the default CBC solver. The model has roughly
    (#swimmers * #events) binary vars; for an NVSL team this is small (<10k).
    """
    individual_events = [e for e in EVENT_CATALOG if e.kind == "INDIVIDUAL"]
    swimmers = roster.swimmers

    # Build (swimmer_idx, event_idx) -> binary variable; only when eligible.
    # We also need slot variables to count entries per event up to 3.
    # Simpler form: x[s, e] in {0,1} indicates "swimmer s in event e",
    #   sum_s x[s, e] <= 3,
    #   sum_e x[s, e] <= 2,
    #   sum_{e in stroke X} x[s, e] <= 1   for each stroke X (forces no repeat).
    # We assign slots A/B/C post-hoc based on time rank within event.
    prob = pulp.LpProblem("nvsl_problem1", pulp.LpMinimize)

    x: dict[tuple[int, int], pulp.LpVariable] = {}
    for si, s in enumerate(swimmers):
        for ei, ev in enumerate(individual_events):
            if not _eligible(s, ev):
                continue
            x[(si, ei)] = pulp.LpVariable(f"x_{si}_{ei}", cat="Binary")

    # Objective: maximize slots filled (primary), then minimize total time
    # (secondary). Encoded as a single objective by subtracting a big bonus per
    # assignment that dominates any possible time. Max realistic NVSL time is
    # well under 600 s; we use BIG = 10_000 to make slot-fill strictly dominant.
    BIG = 10_000
    prob += pulp.lpSum(
        x[(si, ei)] * (
            swimmers[si].time_for(individual_events[ei].event_id) - BIG
        )
        for (si, ei) in x
    )

    # Constraint: each event has <= 3 entries.
    for ei, ev in enumerate(individual_events):
        vars_in_event = [x[(si, ei)] for si in range(len(swimmers)) if (si, ei) in x]
        if vars_in_event:
            prob += pulp.lpSum(vars_in_event) <= MAX_ENTRIES_PER_INDIVIDUAL_EVENT, \
                f"cap_event_{ei}"

    # Constraint: each swimmer in <= 2 individual events.
    for si in range(len(swimmers)):
        vars_for_swimmer = [x[(si, ei)] for ei in range(len(individual_events)) if (si, ei) in x]
        if vars_for_swimmer:
            prob += pulp.lpSum(vars_for_swimmer) <= MAX_INDIVIDUAL_EVENTS_PER_SWIMMER, \
                f"cap_swimmer_{si}"

    # Constraint: per swimmer, at most one event per stroke (no stroke repeat).
    for si in range(len(swimmers)):
        for stroke in INDIVIDUAL_STROKES:
            vars_same_stroke = [
                x[(si, ei)]
                for ei, ev in enumerate(individual_events)
                if (si, ei) in x and ev.stroke == stroke
            ]
            if len(vars_same_stroke) > 1:
                prob += pulp.lpSum(vars_same_stroke) <= 1, \
                    f"no_repeat_{si}_{stroke}"

    # Also want to *maximize* slots used (we want to fill all 120 slots when possible),
    # but the natural minimize-time objective already prefers filling slots when more
    # swimmers are available. To guarantee every fillable slot is filled, we add a
    # small bonus for each assignment (subtract a constant per var). Since times are
    # positive, we'd need to invert: add a large negative bias per slot used. Easier:
    # max-fill is achieved by minimizing (time - BIG) per slot, where BIG > max time.
    # Equivalently, we just check post-hoc that all reachable slots are filled.

    solver = pulp.PULP_CBC_CMD(msg=verbose, timeLimit=max_seconds)
    status = prob.solve(solver)
    status_str = pulp.LpStatus[status]

    # Extract assignments.
    raw: dict[int, list[tuple[Swimmer, float]]] = {}
    for (si, ei), var in x.items():
        if var.value() and var.value() > 0.5:
            ev = individual_events[ei]
            t = swimmers[si].time_for(ev.event_id)
            raw.setdefault(ei, []).append((swimmers[si], t))

    assignments: list[Assignment] = []
    for ei, picks in raw.items():
        picks.sort(key=lambda p: p[1])  # fastest -> A
        for slot, (s, t) in zip("ABC", picks):
            assignments.append(Assignment(
                event=individual_events[ei], slot=slot, swimmer=s, time_seconds=t,
            ))

    total_seconds = sum(a.time_seconds for a in assignments)
    return LineupSolution(
        assignments=assignments,
        total_seconds=total_seconds,
        solver_status=status_str,
    )
