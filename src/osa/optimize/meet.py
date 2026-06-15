"""End-to-end NVSL dual-meet solver: combines individuals + relays.

Two modes:
  * solve_solo(roster)      -> Problem 1: best self-consistent lineup
  * solve_vs(us, opp)       -> Problem 2: best-response vs opponent's optimum

Returns a MeetSolution with all 52 events filled (where possible) and the
projected final score.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from osa.model.roster import Roster
from osa.optimize.problem1 import LineupSolution, solve_problem1
from osa.optimize.problem2 import (
    HeadToHeadSolution, opponent_individual_lineup, solve_problem2_individuals,
)
from osa.optimize.relays import (
    RelaySolution, opponent_relay_times, solve_relays,
)


@dataclass
class MeetSolution:
    """Full dual-meet projection."""
    mode: str                              # "solo" or "vs"
    individuals: LineupSolution | HeadToHeadSolution
    relays: RelaySolution
    our_total_points: int | None           # only meaningful in "vs" mode
    opp_total_points: int | None           # only meaningful in "vs" mode
    notes: list[str] = field(default_factory=list)


def solve_solo(roster: Roster, *, verbose: bool = False) -> MeetSolution:
    """Problem 1: best self-consistent lineup, opponent-agnostic.

    Individuals: fastest legal lineup minimizing total time.
    Relays: jointly minimize total relay time, respecting per-swimmer caps.
    """
    ind = solve_problem1(roster, verbose=verbose)
    rel = solve_relays(roster, opp_relay_times=None, verbose=verbose)
    return MeetSolution(
        mode="solo",
        individuals=ind,
        relays=rel,
        our_total_points=None,
        opp_total_points=None,
    )


def solve_vs(
    our_roster: Roster, opp_roster: Roster, *,
    verbose: bool = False,
) -> MeetSolution:
    """Problem 2: assume opponent plays optimally; find OUR best response.

    Individuals: maximize expected points vs opp's P1 individual lineup.
    Relays: maximize relays-won vs opp's P1 relay times.
    """
    opp_ind_lineup = opponent_individual_lineup(opp_roster)
    opp_rel_times = opponent_relay_times(opp_roster)

    ind = solve_problem2_individuals(our_roster, opp_ind_lineup, verbose=verbose)
    rel = solve_relays(our_roster, opp_relay_times=opp_rel_times, verbose=verbose)

    # Compute opp points: total possible per event minus what we earned.
    # Individuals: 9 per event - our points (only when opp has entries)
    opp_ind_pts = 0
    our_per_event = ind.per_event()
    individuals_in_catalog = sorted({a.event for a in ind.our_assignments}, key=lambda e: e.number)
    # iterate all 40 individual events to count opp points correctly
    from osa.rules.events import EVENT_CATALOG
    for ev in EVENT_CATALOG:
        if ev.kind != "INDIVIDUAL":
            continue
        opp_count = len(opp_ind_lineup.get(ev.event_id, []))
        if opp_count == 0:
            continue
        our_pts = sum(a.points_earned for a in our_per_event.get(ev.event_id, []))
        # 9 total awarded per event when both teams have >=3 entries combined;
        # if fewer than 3 entries total in the event, fewer points are awarded
        from osa.optimize.problem2 import PointsByPlace
        our_count = len(our_per_event.get(ev.event_id, []))
        total_entries = our_count + opp_count
        max_places = min(3, total_entries)
        awarded = sum(PointsByPlace[i] for i in range(max_places))
        opp_pts = awarded - our_pts
        opp_ind_pts += opp_pts

    # Relays: each won by one side (5-0).
    opp_rel_pts = 0
    for ev_id, opp_t in opp_rel_times.items():
        # did WE win this relay?
        won_by_us = any(lu.relay.event_id == ev_id and lu.total_seconds < opp_t
                        for lu in rel.chosen)
        if not won_by_us:
            opp_rel_pts += 5

    our_total = ind.total_points + rel.total_points
    opp_total = opp_ind_pts + opp_rel_pts

    notes = []
    missing_relays = [ev.event_id for ev in EVENT_CATALOG if ev.is_relay
                      and not any(lu.relay.event_id == ev.event_id for lu in rel.chosen)
                      and ev.event_id in opp_rel_times]
    if missing_relays:
        notes.append(
            f"OUR side could not field {len(missing_relays)} relay(s): "
            f"{', '.join(missing_relays)}"
        )

    return MeetSolution(
        mode="vs", individuals=ind, relays=rel,
        our_total_points=our_total, opp_total_points=opp_total,
        notes=notes,
    )
