"""End-to-end demo: parse all 4 OH Top Times PDFs, merge into one season roster,
solve Problem 1, and print the recommended A/B/C lineup grouped by event."""
from pathlib import Path

from osa.parsing.hytek_top_times import parse_top_times
from osa.model.roster import build_roster, merge_rosters
from osa.optimize.problem1 import solve_problem1
from osa.rules.events import EVENT_CATALOG


RAW = Path(__file__).parent.parent / "data" / "raw"


def fmt_time(seconds: float) -> str:
    if seconds >= 60:
        m = int(seconds // 60)
        s = seconds - m * 60
        return f"{m}:{s:05.2f}"
    return f"{seconds:5.2f}"


def main() -> None:
    pdfs = sorted(RAW.glob("oh_vs_*.pdf"))
    rosters = []
    for pdf in pdfs:
        entries = parse_top_times(pdf)
        rosters.append(build_roster(entries, team="OH"))
    season = merge_rosters(*rosters)
    print(f"OH season roster: {len(season.swimmers)} swimmers, "
          f"{sum(len(s.best_times) for s in season.swimmers)} swimmer-event times")

    print("\nSolving Problem 1 (best self-consistent lineup)...")
    sol = solve_problem1(season)
    print(f"  solver status: {sol.solver_status}")
    print(f"  total seconds: {sol.total_seconds:.2f}")
    print(f"  total slots filled: {len(sol.assignments)} / "
          f"{sum(1 for e in EVENT_CATALOG if e.kind == 'INDIVIDUAL') * 3}")

    print("\n" + "=" * 78)
    print("RECOMMENDED A/B/C LINEUP")
    print("=" * 78)

    per_event = sol.per_event()
    individual_events = [e for e in EVENT_CATALOG if e.kind == "INDIVIDUAL"]
    for ev in individual_events:
        picks = per_event.get(ev.event_id, [])
        if not picks:
            print(f"\n#{ev.number:2d}  {ev.event_id:30s}  -- no entries --")
            continue
        print(f"\n#{ev.number:2d}  {ev.event_id}")
        for a in picks:
            up_mark = "" if a.swimmer.natural_age_group == ev.age_group else \
                     f"  (swim-up from {a.swimmer.natural_age_group})"
            print(f"     {a.slot}  {fmt_time(a.time_seconds)}  "
                  f"{a.swimmer.name:25s} age {a.swimmer.age}{up_mark}")

    print("\n" + "=" * 78)
    print("BUSIEST SWIMMERS (most events)")
    print("=" * 78)
    per_sw = sol.per_swimmer()
    for name, ass in sorted(per_sw.items(), key=lambda kv: -len(kv[1])):
        if len(ass) < 2:
            break
        events = ", ".join(f"{a.event.event_id} ({a.slot})" for a in ass)
        print(f"  {name:25s}: {events}")


if __name__ == "__main__":
    main()
