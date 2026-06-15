"""OH vs VW with A/B/D aggregation comparison.

With the 2 PDFs we currently have, each swimmer appears in only one meet,
so A == B == D and no narratives will fire. The framework is ready for when
you add more PDFs per team. Add another OH-source PDF to data/raw/ and append
to the list below to see B/D divergence in action.
"""
from pathlib import Path

from osa.multi_meet import build_rich_roster
from osa.optimize.compare import compare_aggregations
from osa.render_compare import render_comparison

RAW = Path(__file__).parent.parent / "data" / "raw"


def main():
    # All PDFs that contain OH's times (add more historic meets here as you get them)
    oh_pdfs = [RAW / "historic_meet_2.pdf"]
    # All PDFs that contain VW's times
    vw_pdfs = [RAW / "historic_meet_1.pdf"]

    print(f"Building OH rich roster from {len(oh_pdfs)} PDF(s)...")
    oh = build_rich_roster(oh_pdfs, team="OH")
    print(f"  OH: {len(oh.swimmers)} swimmers, "
          f"{sum(len(s.history) for s in oh.swimmers)} swimmer-event observations")
    multi_obs = sum(1 for s in oh.swimmers for ev_id, recs in s.history.items() if len(recs) > 1)
    print(f"  swimmer-events with ≥2 observations: {multi_obs} "
          f"(these are where B/D narratives can fire)")

    print(f"\nBuilding VW rich roster from {len(vw_pdfs)} PDF(s)...")
    vw = build_rich_roster(vw_pdfs, team="VW")
    print(f"  VW: {len(vw.swimmers)} swimmers")

    print("\nRunning optimizer under A, B, and D aggregations...")
    report = compare_aggregations(oh, vw)
    print(render_comparison(report, oh, vw))


if __name__ == "__main__":
    main()
