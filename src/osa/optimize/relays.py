"""Joint solver for all 12 NVSL relays (10 medley + 2 mixed-age free).

Approach: per relay, enumerate the top-K fastest candidate 4-swimmer lineups
via brute force on top-N per leg. Then run a set-packing MILP that picks at
most one lineup per relay subject to per-swimmer caps:
  * each swimmer in <=1 age-group relay (Rule 2c)
  * each swimmer in <=1 mixed-age relay (separate cap; can also do 1 age-group)

For Problem 1 (no opponent data) the objective is to minimize total time
across all relays. For Problem 2 (vs known opponent times) the objective is
to maximize the number of relays we win at 5-0.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product

import pulp

from osa.model.roster import Roster, Swimmer
from osa.rules.events import (
    AGE_GROUPS, EVENT_CATALOG, FREE_RELAY_LEG_ORDER, MEDLEY_LEG_ORDER,
    MIXED_AGE_RELAY_ORDER, Event,
)


@dataclass(frozen=True)
class RelayLeg:
    """One swimmer's assignment within a relay lineup."""
    label: str           # leg stroke (medley) or age-band (mixed-age)
    swimmer: Swimmer
    time_seconds: float  # the time used for ordering / total


@dataclass(frozen=True)
class RelayLineup:
    """One candidate 4-swimmer lineup for a relay."""
    relay: Event
    legs: tuple[RelayLeg, ...]
    total_seconds: float

    @property
    def swimmer_names(self) -> tuple[str, ...]:
        return tuple(l.swimmer.name for l in self.legs)


@dataclass
class RelaySolution:
    chosen: list[RelayLineup]            # one per scored relay
    total_points: float                  # only meaningful in Problem-2 mode
    total_seconds: float                 # sum across all chosen relays
    solver_status: str


# Race-day variance threshold for relays (4 swimmers' noise stacks): default 1.0s.
# Lineups within this margin of the opponent's total are treated as a tie.
RELAY_TIE_THRESHOLD = 1.0


def _eligible_for_medley_leg(s: Swimmer, relay: Event, leg_stroke: str) -> float | None:
    """Return the swimmer's best time for this medley leg, or None if ineligible.

    Swim-ups allowed (any older age group OK). We look up the swimmer's time
    at the same distance as the legs of this relay.
    """
    if s.gender != relay.gender:
        return None
    if relay.age_group not in s.eligible_age_groups():
        return None
    # Leg distance for medley: 8U/9-10/11-12/13-14 -> 25 each leg; 15-18 -> 50 each leg
    leg_yards = 50 if relay.age_group == "15-18" else 25
    # 8U leg = 25, but we record 8U times as 25. For 9-10/11-12 the leg is also
    # 25 yards but the swimmers' normal individual events are at 50. Per the
    # user's call: use the swimmer's 50 time directly for ranking — it
    # preserves the right ordering.
    if relay.age_group == "8U":
        return s.best_times.get(f"{s.gender}_8U_25_{leg_stroke}")
    if relay.age_group == "15-18":
        # check direct 15-18 50 time; also accept swim-up from 13-14 50
        for ag in s.eligible_age_groups():
            t = s.best_times.get(f"{s.gender}_{ag}_50_{leg_stroke}")
            if t is not None:
                return t
        return None
    # 9-10 / 11-12 / 13-14 medley legs: swimmers' 50-stroke time is the ranking signal
    for ag in s.eligible_age_groups():
        t = s.best_times.get(f"{s.gender}_{ag}_50_{leg_stroke}")
        if t is not None:
            return t
    # fall back to 25 time if 50 not available (rare)
    for ag in s.eligible_age_groups():
        t = s.best_times.get(f"{s.gender}_{ag}_25_{leg_stroke}")
        if t is not None:
            return t * 2  # rough scale to 50-equivalent
    return None


def _eligible_for_mixed_age_band(s: Swimmer, relay: Event, band: str) -> float | None:
    """Return swimmer's freestyle time for their mixed-age relay slot.

    Mixed-age has NO swim-ups (Rule 2c): each band slot must be filled by a
    swimmer of that natural age group. For 10&U (band "9-10") we accept either
    a 9-10 or 8U swimmer.

    Mixed-age relay is 4 x 50 (200 total), so EVERY leg is a 50. For an 8U
    swimmer slotted into the 10&U leg, we estimate their 50 free as 2.05 x
    their 25 free time (a slight discount for the dive on leg 1) when no
    actual 50 is recorded.
    """
    if s.gender != relay.gender:
        return None
    nat = s.natural_age_group
    if band == "9-10":
        if nat not in ("8U", "9-10"):
            return None
    else:
        if nat != band:
            return None
    # Prefer an actual 50 free time at the swimmer's natural age group.
    direct = s.best_times.get(f"{s.gender}_{nat}_50_FREE")
    if direct is not None:
        return direct
    # 8U fallback: estimate 50 from their 25 (~2.05x, accounting for one dive).
    if nat == "8U":
        t25 = s.best_times.get(f"{s.gender}_8U_25_FREE")
        if t25 is not None:
            return t25 * 2.05
    return None


def _eligible_for_8u_free_relay(s: Swimmer, relay: Event) -> float | None:
    """Return 8U swimmer's 25 free time, or None if ineligible.

    8U same-age free relay is 4x25. Only 8U swimmers (no swim-downs allowed),
    same gender. Each leg uses the swimmer's 25 free time.
    """
    if s.gender != relay.gender:
        return None
    if s.natural_age_group != "8U":
        return None
    return s.best_times.get(f"{s.gender}_8U_25_FREE")


def enumerate_lineups(
    roster: Roster, relay: Event,
    *, top_per_leg: int = 6, top_k: int = 30,
) -> list[RelayLineup]:
    """Enumerate the top-K fastest candidate lineups for one relay."""
    if relay.kind == "FREE_RELAY":
        # 8U 4x25 free: all 4 legs identical. Enumerate combinations of 4
        # distinct swimmers from the top-N fastest 8U free-timers.
        cands: list[tuple[float, Swimmer]] = []
        for s in roster.swimmers:
            t = _eligible_for_8u_free_relay(s, relay)
            if t is not None:
                cands.append((t, s))
        cands.sort(key=lambda p: p[0])
        # Pool size for combinations: cap at top_per_leg+3 to keep C(n,4) tractable
        # while still allowing variety. For 8U with ~10 swimmers, this covers all.
        pool = cands[: top_per_leg + 3]
        if len(pool) < 4:
            return []
        candidates: list[RelayLineup] = []
        leg_labels = list(FREE_RELAY_LEG_ORDER)
        for combo in combinations(pool, 4):
            # Order legs fastest-to-slowest (anchor strategy is irrelevant for
            # total time; consistent ordering helps readability of output).
            ordered = sorted(combo, key=lambda p: p[0])
            total = sum(t for t, _ in ordered)
            legs = tuple(
                RelayLeg(label=label, swimmer=s, time_seconds=t)
                for label, (t, s) in zip(leg_labels, ordered)
            )
            candidates.append(RelayLineup(relay=relay, legs=legs, total_seconds=total))
        candidates.sort(key=lambda c: c.total_seconds)
        return candidates[:top_k]

    if relay.kind == "MEDLEY_RELAY":
        leg_labels = list(MEDLEY_LEG_ORDER)
        cand_fn = _eligible_for_medley_leg
    elif relay.kind == "MIXED_AGE_FREE_RELAY":
        leg_labels = list(MIXED_AGE_RELAY_ORDER)
        cand_fn = _eligible_for_mixed_age_band
    else:
        return []

    # Per leg, candidates = [(time, swimmer)] sorted fastest first, top_per_leg
    per_leg: dict[str, list[tuple[float, Swimmer]]] = {}
    for leg in leg_labels:
        cands = []
        for s in roster.swimmers:
            t = cand_fn(s, relay, leg)
            if t is not None:
                cands.append((t, s))
        cands.sort(key=lambda p: p[0])
        per_leg[leg] = cands[:top_per_leg]

    # Cartesian product, filter to distinct swimmers, take top_k by total time
    candidates = []
    for combo in product(*(per_leg[l] for l in leg_labels)):
        names = tuple(s.name for _, s in combo)
        if len(set(names)) != len(combo):
            continue
        total = sum(t for t, _ in combo)
        legs = tuple(
            RelayLeg(label=leg, swimmer=s, time_seconds=t)
            for leg, (t, s) in zip(leg_labels, combo)
        )
        candidates.append(RelayLineup(relay=relay, legs=legs, total_seconds=total))

    candidates.sort(key=lambda c: c.total_seconds)
    return candidates[:top_k]


def solve_relays(
    roster: Roster,
    *,
    opp_relay_times: dict[str, float] | None = None,
    top_per_leg: int = 12,
    top_k: int = 60,
    max_seconds: int = 15,
    verbose: bool = False,
) -> RelaySolution:
    """Solve all 12 relays jointly.

    If `opp_relay_times` is provided (Problem 2), objective is to maximize
    relays-won. If None (Problem 1), objective is to minimize total time
    across all selected relays.
    """
    relays = [e for e in EVENT_CATALOG if e.is_relay]
    # Build candidate sets per relay
    all_options: list[tuple[Event, RelayLineup, float]] = []  # (relay, lineup, points)
    for relay in relays:
        lineups = enumerate_lineups(roster, relay, top_per_leg=top_per_leg, top_k=top_k)
        for lu in lineups:
            if opp_relay_times is not None:
                opp_t = opp_relay_times.get(relay.event_id)
                if opp_t is None:
                    pts = 5.0  # opp has nothing -> we win automatically
                elif lu.total_seconds + RELAY_TIE_THRESHOLD < opp_t:
                    # clear win: beat opp by more than tie threshold
                    pts = 5.0
                elif lu.total_seconds > opp_t + RELAY_TIE_THRESHOLD:
                    # clear loss: opp beat us by more than tie threshold
                    pts = 0.0
                else:
                    # within tie threshold -- handbook says ties split 5-0 -> 2.5/2.5.
                    # In conservative mode we credit OPP with the 5 and award 0
                    # for projection purposes; the lineup is still fielded.
                    pts = 0.0
            else:
                pts = 0.0  # not used in P1 objective
            all_options.append((relay, lu, pts))

    # MILP
    prob = pulp.LpProblem("nvsl_relays", pulp.LpMaximize if opp_relay_times is not None
                          else pulp.LpMinimize)
    z = [pulp.LpVariable(f"z_{i}", cat="Binary") for i in range(len(all_options))]

    if opp_relay_times is not None:
        # Maximize total relay points + strong fielding bonus + time tiebreak.
        # FILL_BONUS=100 makes fielding any relay strictly better than not
        # fielding (gain 100 per fielded relay always > losing potential
        # 5pt elsewhere from cap conflict). The optimizer will jointly choose
        # the largest set of fieldable relays subject to per-swimmer caps.
        FILL_BONUS = 100.0
        TIME_PENALTY = 0.0001
        prob += pulp.lpSum(
            z[i] * (all_options[i][2] + FILL_BONUS - TIME_PENALTY * all_options[i][1].total_seconds)
            for i in range(len(all_options))
        )
    else:
        # Minimize total time across chosen relays, but reward filling slots
        # (a relay with no chosen lineup contributes 0 time but also 0 value).
        # We want to fill every fillable relay; use a fill bonus that dominates time.
        BIG = 10_000
        prob += pulp.lpSum(
            z[i] * (all_options[i][1].total_seconds - BIG)
            for i in range(len(all_options))
        )

    # At most one lineup per relay. Combined with a large FILL_BONUS in the
    # objective, this acts as "field if at all possible" -- the optimizer
    # always prefers fielding to not-fielding when no per-swimmer cap conflict
    # forbids it. (Hard `== 1` would make the joint MILP infeasible whenever
    # per-swimmer caps create unavoidable conflicts across relays.)
    for relay in relays:
        idxs = [i for i, (r, _, _) in enumerate(all_options) if r is relay]
        if idxs:
            prob += pulp.lpSum(z[i] for i in idxs) <= 1, f"one_per_{relay.event_id}"

    # Per-swimmer cap: <=1 age-group relay. Both same-age MEDLEY (9-10..15-18)
    # and same-age FREE (8U) relays count against this single slot.
    swimmer_names = {s.name for s in roster.swimmers}
    for name in swimmer_names:
        ag_idxs = [
            i for i, (r, lu, _) in enumerate(all_options)
            if r.kind in ("MEDLEY_RELAY", "FREE_RELAY") and name in lu.swimmer_names
        ]
        if ag_idxs:
            prob += pulp.lpSum(z[i] for i in ag_idxs) <= 1, f"ag_cap_{name}"
        ma_idxs = [
            i for i, (r, lu, _) in enumerate(all_options)
            if r.kind == "MIXED_AGE_FREE_RELAY" and name in lu.swimmer_names
        ]
        if ma_idxs:
            prob += pulp.lpSum(z[i] for i in ma_idxs) <= 1, f"ma_cap_{name}"

    solver = pulp.PULP_CBC_CMD(msg=verbose, timeLimit=max_seconds)
    status = prob.solve(solver)

    chosen: list[RelayLineup] = []
    total_pts: float = 0.0
    total_sec = 0.0
    for i, var in enumerate(z):
        if var.value() and var.value() > 0.5:
            relay, lu, pts = all_options[i]
            chosen.append(lu)
            total_pts += pts
            total_sec += lu.total_seconds

    return RelaySolution(
        chosen=chosen, total_points=total_pts, total_seconds=total_sec,
        solver_status=pulp.LpStatus[status],
    )


def opponent_relay_times(opp_roster: Roster, **kwargs) -> dict[str, float]:
    """Compute opponent's best total time per relay (their P1 relay solution)."""
    sol = solve_relays(opp_roster, opp_relay_times=None, **kwargs)
    return {lu.relay.event_id: lu.total_seconds for lu in sol.chosen}
