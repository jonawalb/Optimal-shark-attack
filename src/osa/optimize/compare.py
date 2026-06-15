"""Run the head-to-head optimizer under all three aggregations (A/B/D) and
surface events where the chosen swimmer set differs across aggregations.

This is the engine behind the user's spec:
  * Recommend the lineup based on A (PR / season best).
  * For each event, also compute what B (recent) and D (weighted) would pick.
  * If A vs B or A vs D would have chosen a DIFFERENT set of swimmers,
    emit a per-event narrative sentence.
"""
from __future__ import annotations

from dataclasses import dataclass

from osa.multi_meet import RichRoster, roster_view
from osa.optimize.meet import solve_vs


@dataclass
class EventComparison:
    """Per-event side-by-side of which swimmers each aggregation would pick."""
    event_id: str
    picks_A: list[str]           # swimmer names chosen under aggregation A
    picks_B: list[str]
    picks_D: list[str]
    times_A: dict[str, float]    # swimmer_name -> time used (A)
    times_B: dict[str, float]
    times_D: dict[str, float]

    @property
    def differs_B(self) -> bool:
        return set(self.picks_A) != set(self.picks_B)

    @property
    def differs_D(self) -> bool:
        return set(self.picks_A) != set(self.picks_D)


@dataclass
class ComparisonReport:
    """Bundled result of running the optimizer on all three aggregations."""
    solution_A: "MeetSolution"   # the recommended lineup (from A)
    solution_B: "MeetSolution"
    solution_D: "MeetSolution"
    per_event: dict[str, EventComparison]


def _extract_picks(sol, event_id: str) -> tuple[list[str], dict[str, float]]:
    """Pull the names + times the optimizer chose for one event."""
    names = []
    times = {}
    for a in sol.individuals.our_assignments:
        if a.event.event_id == event_id:
            names.append(a.swimmer.name)
            times[a.swimmer.name] = a.time_seconds
    return names, times


def compare_aggregations(our: RichRoster, opp: RichRoster) -> ComparisonReport:
    """Solve OH-best-response under A, B, D. Compare event-by-event.

    We apply the SAME aggregation symmetrically: in the A run, opp also uses
    PR; in the B run, opp uses recent; in the D run, opp uses weighted recent.
    This makes each shadow score a coherent counterfactual ("if both teams
    swam at PR" vs "if both teams swam at recent form").
    """
    us_A, us_B, us_D = (roster_view(our, m) for m in ("A", "B", "D"))
    opp_A, opp_B, opp_D = (roster_view(opp, m) for m in ("A", "B", "D"))

    sol_A = solve_vs(us_A, opp_A)
    sol_B = solve_vs(us_B, opp_B)
    sol_D = solve_vs(us_D, opp_D)

    per_event: dict[str, EventComparison] = {}
    from osa.rules.events import EVENT_CATALOG
    for ev in EVENT_CATALOG:
        if ev.kind != "INDIVIDUAL":
            continue
        pa, ta = _extract_picks(sol_A, ev.event_id)
        pb, tb = _extract_picks(sol_B, ev.event_id)
        pd_, td = _extract_picks(sol_D, ev.event_id)
        per_event[ev.event_id] = EventComparison(
            event_id=ev.event_id,
            picks_A=pa, picks_B=pb, picks_D=pd_,
            times_A=ta, times_B=tb, times_D=td,
        )

    return ComparisonReport(
        solution_A=sol_A, solution_B=sol_B, solution_D=sol_D,
        per_event=per_event,
    )


def narrative(ev_comp: EventComparison) -> str | None:
    """Produce a one-sentence explanation for any swap implied by B or D."""
    if not ev_comp.differs_B and not ev_comp.differs_D:
        return None
    sa, sb, sd = set(ev_comp.picks_A), set(ev_comp.picks_B), set(ev_comp.picks_D)
    msgs = []
    if sb != sa:
        added = sb - sa
        dropped = sa - sb
        if added and dropped:
            msgs.append(
                f"Recent times suggest {', '.join(added)} in for "
                f"{', '.join(dropped)} (rotation under aggregation B)"
            )
        elif added:
            msgs.append(f"Recent form would add {', '.join(added)}")
        elif dropped:
            msgs.append(f"Recent form would drop {', '.join(dropped)}")
    if sd != sa and sd != sb:
        added = sd - sa
        dropped = sa - sd
        if added and dropped:
            msgs.append(
                f"Weighted average suggests {', '.join(added)} for "
                f"{', '.join(dropped)} (rotation under aggregation D)"
            )
        elif added:
            msgs.append(f"Weighted average would add {', '.join(added)}")
        elif dropped:
            msgs.append(f"Weighted average would drop {', '.join(dropped)}")
    return " | ".join(msgs) if msgs else None
