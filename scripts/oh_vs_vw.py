"""OH (us) vs VW (opp) using ONLY the 2025 Virtual Meet PDFs.

OH times come from PDF 2 (Orange Hunt at Vienna Woods, 7/5/2025).
VW times come from PDF 1 (Vienna Woods at Hiddenbrook, 6/21/2025).
Both meets were 25-meter course -- apples to apples.
"""
from pathlib import Path

from osa.parsing.nvsl_virtual_meet import parse_virtual_meet
from osa.model.roster import build_roster
from osa.optimize.meet import solve_vs
from osa.cli import render_meet

RAW = Path(__file__).parent.parent / "data" / "raw"


def main():
    print("Parsing OH times from PDF 2 (Orange Hunt at Vienna Woods 7/5/25)...")
    oh_entries = parse_virtual_meet(RAW / "historic_meet_2.pdf", team="OH")
    oh = build_roster(oh_entries, team="OH")
    print(f"  OH roster: {len(oh.swimmers)} distinct swimmers, "
          f"{sum(len(s.best_times) for s in oh.swimmers)} swimmer-event times")

    print("\nParsing VW times from PDF 1 (Vienna Woods at Hiddenbrook 6/21/25)...")
    vw_entries = parse_virtual_meet(RAW / "historic_meet_1.pdf", team="VW")
    vw = build_roster(vw_entries, team="VW")
    print(f"  VW roster: {len(vw.swimmers)} distinct swimmers, "
          f"{sum(len(s.best_times) for s in vw.swimmers)} swimmer-event times")

    print("\nSolving Problem 2 (OH best response vs VW)...")
    sol = solve_vs(oh, vw, verbose=False)
    print(render_meet(sol))


if __name__ == "__main__":
    main()
