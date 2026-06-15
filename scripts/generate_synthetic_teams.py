"""Generate 4 synthetic NVSL teams, save as CSVs, and print summary stats."""
from collections import Counter
from pathlib import Path

from osa.data.synthetic import (
    TEST_TEAM_PROFILES, generate_team, roster_to_csv,
)
from osa.optimize.problem1 import solve_problem1

OUT = Path(__file__).parent.parent / "data" / "synthetic"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rosters = []
    for i, profile in enumerate(TEST_TEAM_PROFILES):
        roster = generate_team(profile, seed=1000 + i)
        rosters.append((profile, roster))
        csv_path = OUT / f"{profile.abbrev}.csv"
        roster_to_csv(roster, csv_path)
        print(f"\n=== {profile.abbrev} ({profile.name}) -> {csv_path.name} ===")
        print(f"  roster_size target={profile.roster_size}, generated={len(roster.swimmers)}")
        print(f"  strength={profile.strength}, depth={profile.depth}")
        by_age = Counter(s.natural_age_group for s in roster.swimmers)
        by_gender = Counter(s.gender for s in roster.swimmers)
        total_times = sum(len(s.best_times) for s in roster.swimmers)
        print(f"  by age:    {dict(by_age)}")
        print(f"  by gender: {dict(by_gender)}")
        print(f"  total swimmer-event times: {total_times}")

    # Solve Problem 1 on each team and report total time -- a one-number
    # team-strength summary that's directly comparable across teams.
    print("\n" + "=" * 72)
    print("PROBLEM-1 SOLVE PER TEAM (lower total = stronger team)")
    print("=" * 72)
    for profile, roster in rosters:
        sol = solve_problem1(roster, verbose=False)
        slots = len(sol.assignments)
        print(f"  {profile.abbrev} ({profile.name:11s})  "
              f"slots filled {slots:3d}/120  "
              f"total time {sol.total_seconds:7.2f}s  "
              f"avg per slot {sol.total_seconds / max(slots, 1):5.2f}s")


if __name__ == "__main__":
    main()
