"""OH vs Virginia Hills using all 5 OH meets + all 5 VH meets from 2025 season.

Aggregations:
  A = PR (season best across the 5 meets)
  B = most recent meet's time
  D = linear-decay weighted average
The recommended lineup uses A; per-event narratives fire when B or D would
have picked different swimmers.
"""
from pathlib import Path

from osa.multi_meet import build_rich_roster
from osa.optimize.compare import compare_aggregations
from osa.render_compare import render_comparison

RAW = Path(__file__).parent.parent / "data" / "raw"


def main():
    oh_pdfs = sorted((RAW / "oh_2025").glob("*.pdf"))
    vh_pdfs = sorted((RAW / "vh_2025").glob("*.pdf"))

    print(f"OH inputs ({len(oh_pdfs)}):")
    for p in oh_pdfs: print(f"  {p.name}")
    print(f"VH inputs ({len(vh_pdfs)}):")
    for p in vh_pdfs: print(f"  {p.name}")

    alias_file = RAW.parent / "aliases.json"

    print("\nBuilding OH rich roster...")
    oh = build_rich_roster(oh_pdfs, team="OH", alias_file=alias_file)
    obs = sum(len(s.history) for s in oh.swimmers)
    multi = sum(1 for s in oh.swimmers for ev, recs in s.history.items() if len(recs) > 1)
    print(f"  OH: {len(oh.swimmers)} swimmers, {obs} swimmer-event records, "
          f"{multi} swimmer-events with ≥2 observations")

    print("\nBuilding VH rich roster...")
    vh = build_rich_roster(vh_pdfs, team="VH", alias_file=alias_file)
    obs = sum(len(s.history) for s in vh.swimmers)
    multi = sum(1 for s in vh.swimmers for ev, recs in s.history.items() if len(recs) > 1)
    print(f"  VH: {len(vh.swimmers)} swimmers, {obs} swimmer-event records, "
          f"{multi} swimmer-events with ≥2 observations")

    print("\nRunning optimizer under A, B, and D...")
    report = compare_aggregations(oh, vh)
    print(render_comparison(report, oh, vh))


if __name__ == "__main__":
    main()
