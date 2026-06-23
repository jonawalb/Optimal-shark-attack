"""Problem 2: best-response lineup given the opponent's expected lineup.

Game-theoretic setup: lineups are submitted simultaneously (Rule 4a),
so neither side observes the other before committing. We assume the opponent
plays their *own* Problem-1 optimum and find OUR lineup that maximizes
expected points against that fixed reference.

Deterministic seed-time model: faster seed wins. (A stochastic variant can
be layered on top by replacing compute_points with an expected-points
function over a noise distribution.)
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import pulp

from osa.model.roster import Roster, Swimmer
from osa.optimize.problem1 import solve_problem1
from osa.rules.events import (
    EVENT_CATALOG,
    INDIVIDUAL_STROKES,
    MAX_ENTRIES_PER_INDIVIDUAL_EVENT,
    MAX_INDIVIDUAL_EVENTS_PER_SWIMMER,
    INDIVIDUAL_PLACE_POINTS,
    Event,
)


PointsByPlace = (*INDIVIDUAL_PLACE_POINTS, 0, 0, 0)  # places 1..6 -> points


@dataclass(frozen=True)
class HeadToHeadAssignment:
    """One swimmer placed in one event slot, with predicted place + points."""
    event: Event
    swimmer: Swimmer
    time_seconds: float
    predicted_place: int       # 1-6
    points_earned: float        # 0, 1, 3, 5 normally; halves possible on ties


@dataclass
class HeadToHeadSolution:
    our_assignments: list[HeadToHeadAssignment]
    opp_lineup: dict[str, list[float]]   # event_id -> sorted list of opp times
    total_points: float
    solver_status: str

    def per_event(self) -> dict[str, list[HeadToHeadAssignment]]:
        out: dict[str, list[HeadToHeadAssignment]] = {}
        for a in self.our_assignments:
            out.setdefault(a.event.event_id, []).append(a)
        for k in out:
            out[k].sort(key=lambda a: a.time_seconds)
        return out


def opponent_individual_lineup(opp_roster: Roster) -> dict[str, list[float]]:
    """Compute the opponent's best self-consistent individual lineup.

    Returns {event_id: [time_A, time_B, time_C]} for every event they staff.
    """
    sol = solve_problem1(opp_roster)
    out: dict[str, list[float]] = {}
    for a in sol.assignments:
        if a.event.kind == "INDIVIDUAL":
            out.setdefault(a.event.event_id, []).append(a.time_seconds)
    for k in out:
        out[k].sort()
    return out


def _eligible(swimmer: Swimmer, event: Event) -> bool:
    if event.kind != "INDIVIDUAL":
        return False
    if swimmer.gender != event.gender:
        return False
    if event.age_group not in swimmer.eligible_age_groups():
        return False
    return swimmer.time_for(event.event_id) is not None


# Race-day variance threshold (seconds). Times within this margin are treated
# as ties; conservative-mode planning credits the opponent for the slower-half
# of a coin-flip race. Set to 0 to use deterministic seed-wins-everything.
INDIVIDUAL_TIE_THRESHOLD = 0.30


def _points_for_subset(our_times: list[float], opp_times: list[float],
                        *, tie_threshold: float = INDIVIDUAL_TIE_THRESHOLD,
                        conservative: bool = True) -> float:
    """Award points to top 3 places when our and opp times are merged.

    Tie handling (handbook Rule 15c): swimmers whose times are within
    `tie_threshold` of each other tie. Tied positions split the sum of their
    points equally; the next-place position is skipped only when the tie spans
    that position.

    Conservative mode (default True): when our swimmer ties an opponent within
    threshold, the OPPONENT takes the higher place (we plan for the bad
    outcome). Set conservative=False to give ties a true split.
    """
    tagged = ([(t, "us") for t in our_times] + [(t, "opp") for t in opp_times])
    tagged.sort()
    n = min(3, len(tagged))
    if n == 0:
        return 0.0

    # Group tied positions (within threshold of each other).
    groups: list[list[tuple[float, str]]] = []
    for entry in tagged:
        if not groups or entry[0] - groups[-1][-1][0] > tie_threshold:
            groups.append([entry])
        else:
            groups[-1].append(entry)

    pts = 0.0
    place_idx = 0  # 0-based index into PointsByPlace (place 1 -> idx 0)
    for grp in groups:
        if place_idx >= n:
            break
        # places this group spans:
        span = min(len(grp), n - place_idx)
        total_pts_for_group = sum(PointsByPlace[place_idx + i] for i in range(span))
        if conservative and len(grp) > 1 and any(w == "us" for _, w in grp) \
           and any(w == "opp" for _, w in grp):
            # mixed tie: give all the points in this group to OPP
            our_share = 0.0
        else:
            us_count = sum(1 for _, w in grp if w == "us")
            our_share = total_pts_for_group * (us_count / len(grp))
        pts += our_share
        place_idx += len(grp)
    return pts


def _predict_place(t: float, our_other_times: list[float], opp_times: list[float]) -> int:
    """Predict the 1-based place of time t given all 6 times in the event."""
    all_times = [t] + list(our_other_times) + list(opp_times)
    all_times.sort()
    return all_times.index(t) + 1


def _per_swimmer_points(our_times: list[float], opp_times: list[float],
                         *, tie_threshold: float = INDIVIDUAL_TIE_THRESHOLD,
                         conservative: bool = True) -> dict[float, float]:
    """Return {our_time: points_share} for each of our swimmers in this event,
    applying the same tie + conservative-variance rules as _points_for_subset.
    Times must be unique (caller should disambiguate via swimmer object)."""
    tagged = ([(t, "us", i) for i, t in enumerate(our_times)]
              + [(t, "opp", i) for i, t in enumerate(opp_times)])
    tagged.sort()
    n = min(3, len(tagged))
    result: dict[float, float] = {t: 0.0 for t in our_times}

    groups: list[list[tuple[float, str, int]]] = []
    for entry in tagged:
        if not groups or entry[0] - groups[-1][-1][0] > tie_threshold:
            groups.append([entry])
        else:
            groups[-1].append(entry)

    place_idx = 0
    for grp in groups:
        if place_idx >= n:
            break
        span = min(len(grp), n - place_idx)
        total_pts = sum(PointsByPlace[place_idx + i] for i in range(span))
        if conservative and len(grp) > 1 and any(w == "us" for _, w, _ in grp) \
           and any(w == "opp" for _, w, _ in grp):
            # mixed tie: opponents take all points within this group
            pass  # leaves our shares at 0
        else:
            per_member = total_pts / len(grp)
            for t, who, _ in grp:
                if who == "us":
                    # account for duplicate identical our_times by indexing once
                    if t in result:
                        result[t] += per_member
        place_idx += len(grp)
    return result


def solve_problem2_individuals(
    our_roster: Roster,
    opp_lineup: dict[str, list[float]],
    *,
    candidates_per_event: int = 10,
    max_seconds: int = 15,
    verbose: bool = False,
) -> HeadToHeadSolution:
    """Find OUR lineup maximizing expected points vs the opp's fixed lineup.

    Uses a set-packing MILP: per event, enumerate all 1/2/3-subsets of the top
    `candidates_per_event` of our eligible swimmers, score each, then pick at
    most one subset per event subject to per-swimmer caps.
    """
    individual_events = [e for e in EVENT_CATALOG if e.kind == "INDIVIDUAL"]
    swimmers = our_roster.swimmers

    # Build candidate options.
    # options[i] = (event, tuple_of_swimmer_indices, points)
    options: list[tuple[Event, tuple[int, ...], int]] = []
    for ev in individual_events:
        eligible = [(i, swimmers[i]) for i in range(len(swimmers))
                    if _eligible(swimmers[i], ev)]
        # Top-N by time to keep enumeration tractable.
        eligible.sort(key=lambda p: p[1].time_for(ev.event_id))
        eligible = eligible[:candidates_per_event]
        opp_times = opp_lineup.get(ev.event_id, [])
        for size in (1, 2, 3):
            for combo in combinations(eligible, size):
                indices = tuple(i for i, _ in combo)
                our_times = [s.time_for(ev.event_id) for _, s in combo]
                pts = _points_for_subset(our_times, opp_times)
                options.append((ev, indices, pts))

    # MILP
    prob = pulp.LpProblem("nvsl_problem2", pulp.LpMaximize)
    z = [pulp.LpVariable(f"z_{i}", cat="Binary") for i in range(len(options))]
    prob += pulp.lpSum(z[i] * options[i][2] for i in range(len(options)))

    # EXACTLY one subset per event if any eligible swimmer exists.
    # Rule: never leave an individual lane event empty if anyone can swim it.
    # If `idxs` is empty, no swimmer is eligible -- leave it unfielded.
    for ev in individual_events:
        idxs = [i for i, opt in enumerate(options) if opt[0] is ev]
        if idxs:
            prob += pulp.lpSum(z[i] for i in idxs) == 1, f"one_subset_{ev.event_id}"

    # Per swimmer: at most 2 individual events.
    for s_idx in range(len(swimmers)):
        relevant = [i for i, opt in enumerate(options) if s_idx in opt[1]]
        if relevant:
            prob += pulp.lpSum(z[i] for i in relevant) <= MAX_INDIVIDUAL_EVENTS_PER_SWIMMER, \
                f"swimmer_cap_{s_idx}"

    # Per swimmer: at most 1 entry per stroke.
    for s_idx in range(len(swimmers)):
        for stroke in INDIVIDUAL_STROKES:
            relevant = [i for i, opt in enumerate(options)
                        if s_idx in opt[1] and opt[0].stroke == stroke]
            if len(relevant) > 1:
                prob += pulp.lpSum(z[i] for i in relevant) <= 1, \
                    f"stroke_cap_{s_idx}_{stroke}"

    solver = pulp.PULP_CBC_CMD(msg=verbose, timeLimit=max_seconds)
    status = prob.solve(solver)

    # Extract assignments.
    assignments: list[HeadToHeadAssignment] = []
    for i, var in enumerate(z):
        if var.value() and var.value() > 0.5:
            ev, indices, _ = options[i]
            picks = [swimmers[s_idx] for s_idx in indices]
            our_times = [s.time_for(ev.event_id) for s in picks]
            opp_times = opp_lineup.get(ev.event_id, [])
            shares = _per_swimmer_points(our_times, opp_times)
            for s in picks:
                t = s.time_for(ev.event_id)
                others = [x for x in our_times if x != t]
                place = _predict_place(t, others, opp_times)
                assignments.append(HeadToHeadAssignment(
                    event=ev, swimmer=s, time_seconds=t,
                    predicted_place=place,
                    points_earned=shares.get(t, 0.0),
                ))

    total = sum(a.points_earned for a in assignments)
    return HeadToHeadSolution(
        our_assignments=assignments,
        opp_lineup=opp_lineup,
        total_points=total,
        solver_status=pulp.LpStatus[status],
    )
