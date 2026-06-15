"""Demo: SHK (us) vs DOL (opp). Compute SHK's best-response lineup and report
projected score in individual events only (relays not yet wired)."""
from pathlib import Path

from osa.data.synthetic import roster_from_csv
from osa.optimize.problem1 import solve_problem1
from osa.optimize.problem2 import (
    opponent_individual_lineup, solve_problem2_individuals,
)
from osa.rules.events import EVENT_CATALOG

SYNTH = Path(__file__).parent.parent / "data" / "synthetic"


def fmt(t):
    if t >= 60:
        return f"{int(t//60)}:{t-int(t//60)*60:05.2f}"
    return f"{t:5.2f}"


def main():
    us = roster_from_csv(SYNTH / "SHK.csv")
    opp = roster_from_csv(SYNTH / "DOL.csv")
    print(f"US (SHK): {len(us.swimmers)} swimmers")
    print(f"OPP (DOL): {len(opp.swimmers)} swimmers")

    print("\n[1] Computing opponent's optimal individual lineup (their Problem 1)...")
    opp_lineup = opponent_individual_lineup(opp)
    opp_events = sum(1 for ev in EVENT_CATALOG if ev.kind == "INDIVIDUAL"
                     and opp_lineup.get(ev.event_id))
    print(f"     opp staffs {opp_events}/40 individual events")

    print("\n[2] Solving Problem 2: SHK's best-response lineup...")
    sol = solve_problem2_individuals(us, opp_lineup, verbose=False)
    print(f"     status: {sol.solver_status}")
    print(f"     projected individual-event points (SHK): "
          f"{sol.total_points} / {40 * 9} possible")

    # Per-event breakdown
    print(f"\n{'#':3} {'event':30s}  our lineup -> places                    opp lineup")
    print("-" * 100)
    per = sol.per_event()
    individual_events = [e for e in EVENT_CATALOG if e.kind == "INDIVIDUAL"]
    event_pts_breakdown = {"wins": 0, "losses": 0, "shutouts": 0, "swept_by_us": 0}
    for ev in individual_events:
        our_asg = per.get(ev.event_id, [])
        opp_times = opp_lineup.get(ev.event_id, [])
        our_pts = sum(a.points_earned for a in our_asg)
        opp_pts = 9 - our_pts if opp_times else 0
        if our_pts > opp_pts:
            event_pts_breakdown["wins"] += 1
        elif opp_pts > our_pts:
            event_pts_breakdown["losses"] += 1
        if our_pts == 9:
            event_pts_breakdown["swept_by_us"] += 1
        elif our_pts == 0 and opp_times:
            event_pts_breakdown["shutouts"] += 1

        our_str = " | ".join(f"{fmt(a.time_seconds)}@{a.predicted_place}({a.points_earned})"
                              for a in our_asg) or "(none)"
        opp_str = " | ".join(fmt(t) for t in opp_times) or "(none)"
        marker = "★" if our_pts >= opp_pts else " "
        print(f"{ev.number:3d} {ev.event_id:30s}  {marker} {our_str:42s}  vs  {opp_str}")

    # Score summary
    opp_total = sum(
        9 - sum(a.points_earned for a in per.get(ev.event_id, []))
        for ev in individual_events
        if opp_lineup.get(ev.event_id)
    )
    print("\n" + "=" * 100)
    print(f"INDIVIDUAL-EVENT SCORE (SHK vs DOL):  {sol.total_points} - {opp_total}")
    print(f"  events won by SHK: {event_pts_breakdown['wins']}")
    print(f"  events won by DOL: {event_pts_breakdown['losses']}")
    print(f"  events SHK swept 9-0: {event_pts_breakdown['swept_by_us']}")
    print(f"  events DOL shut out SHK: {event_pts_breakdown['shutouts']}")
    print(f"  (relays not yet included; +60 pts available across 12 relays)")
    print("=" * 100)


if __name__ == "__main__":
    main()
