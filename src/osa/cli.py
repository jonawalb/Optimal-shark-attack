"""Command-line interface for the NVSL lineup optimizer.

Usage examples:

  # Multi-PDF head-to-head (the canonical 2026 workflow)
  osa vs \\
      --us data/raw/oh_2025/*.pdf  --us-team OH \\
      --opp data/raw/vh_2025/*.pdf --opp-team VH \\
      --aliases data/aliases.json

  # Subtract specific swimmers who can't make the meet
  osa vs ... --unavailable "Jane Doe,John Doe"
  osa vs ... --unavailable-file friday_outs.txt

  # Self-consistent lineup with no opponent data
  osa solo --roster data/raw/oh_2025/*.pdf --team OH

The `vs` command runs the optimizer under three time-aggregation strategies
symmetrically (both teams):
  A = PR / season best
  B = most recent meet
  D = linear-weighted recent
Recommended lineup uses A. B and D shadow scores show how the result shifts
under recent form. Per-event narratives flag where B or D would have picked
different swimmers.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from osa.loaders import filter_available, load_roster, read_available_names
from osa.multi_meet import build_rich_roster, roster_view
from osa.optimize.compare import compare_aggregations
from osa.optimize.meet import MeetSolution, solve_solo
from osa.render_compare import render_comparison
from osa.rules.events import EVENT_CATALOG


def _fmt(t: float) -> str:
    if t >= 60:
        return f"{int(t//60)}:{t-int(t//60)*60:05.2f}"
    return f"{t:5.2f}"


def _expand_pdf_args(paths: list[str]) -> list[Path]:
    """Accept globs, directories, or individual PDF paths. Return sorted PDFs."""
    out: list[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            out.extend(sorted(path.glob("*.pdf")))
        elif "*" in str(path) or "?" in str(path):
            # User shell didn't expand the glob -- do it ourselves
            from glob import glob
            out.extend(sorted(Path(m) for m in glob(p)))
        else:
            out.append(path)
    return sorted(set(out))


def _read_unavailable_list(text: str | None, file: Path | None) -> set[str]:
    """Parse comma-separated names (--unavailable) and/or one-per-line file."""
    names: set[str] = set()
    if text:
        names.update(n.strip() for n in text.split(",") if n.strip())
    if file:
        for line in Path(file).read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                names.add(line)
    return names


def _filter_rich_roster(rich, unavailable_names: set[str]):
    """Drop swimmers whose normalized names match the unavailable set."""
    from osa.aggregation import name_key
    if not unavailable_names:
        return rich
    drop_keys = {name_key(n) for n in unavailable_names}
    kept = [s for s in rich.swimmers if name_key(s.name) not in drop_keys]
    from osa.multi_meet import RichRoster
    return RichRoster(team=rich.team, swimmers=kept)


def _render_solo(sol: MeetSolution) -> str:
    """Format Problem-1 (solo) output -- legacy single-PDF render."""
    lines: list[str] = []
    lines.append("=" * 88)
    lines.append("  BEST SELF-CONSISTENT LINEUP (no opponent data)")
    lines.append("=" * 88)
    lines.append("")
    lines.append("INDIVIDUAL EVENTS")
    lines.append("-" * 88)
    per_event = sol.individuals.per_event()
    for ev in (e for e in EVENT_CATALOG if e.kind == "INDIVIDUAL"):
        picks = per_event.get(ev.event_id, [])
        if not picks:
            lines.append(f"  #{ev.number:2d}  {ev.event_id:30s}  -- no eligible swimmer --")
            continue
        entries = "  ".join(f"{a.slot} {_fmt(a.time_seconds)} {a.swimmer.name}"
                            for a in picks)
        lines.append(f"  #{ev.number:2d}  {ev.event_id:30s}  {entries}")
    lines.append("")
    lines.append("RELAYS")
    lines.append("-" * 88)
    by_id = {lu.relay.event_id: lu for lu in sol.relays.chosen}
    for ev in (e for e in EVENT_CATALOG if e.is_relay):
        lu = by_id.get(ev.event_id)
        if lu is None:
            lines.append(f"  #{ev.number:2d}  {ev.event_id:30s}  -- not fielded --")
            continue
        lines.append(f"  #{ev.number:2d}  {ev.event_id:30s}  total {_fmt(lu.total_seconds)}")
        for l in lu.legs:
            lines.append(f"        {l.label:6s} {_fmt(l.time_seconds):>7s}  {l.swimmer.name}")
    lines.append("")
    lines.append("=" * 88)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="osa", description="NVSL dual-meet lineup optimizer")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_solo = sub.add_parser("solo", help="Best lineup (no opponent data)")
    p_solo.add_argument("--roster", nargs="+", required=True,
                         help="One or more PDF/CSV paths, globs, or directories")
    p_solo.add_argument("--team", help="Team abbrev (required for PDF input)")
    p_solo.add_argument("--aliases", help="JSON alias file for name normalization")
    p_solo.add_argument("--unavailable",
                         help="Comma-separated names to exclude (sick/missing swimmers)")
    p_solo.add_argument("--unavailable-file",
                         help="File with one swimmer name per line to exclude")
    p_solo.add_argument("--out", help="Write to file instead of stdout")
    p_solo.add_argument("--verbose", action="store_true")

    p_vs = sub.add_parser("vs", help="Best lineup vs opponent (multi-PDF aware)")
    p_vs.add_argument("--us", nargs="+", required=True,
                       help="Our team's PDFs (paths/globs/dirs)")
    p_vs.add_argument("--us-team", required=True, help="Our team abbreviation")
    p_vs.add_argument("--opp", nargs="+", required=True,
                       help="Opponent's PDFs (paths/globs/dirs)")
    p_vs.add_argument("--opp-team", required=True, help="Opponent abbreviation")
    p_vs.add_argument("--aliases", help="JSON alias file for name normalization")
    p_vs.add_argument("--unavailable",
                       help="Comma-separated US swimmer names to exclude")
    p_vs.add_argument("--unavailable-file",
                       help="File with one US swimmer name per line to exclude")
    p_vs.add_argument("--out", help="Write to file instead of stdout")
    p_vs.add_argument("--verbose", action="store_true")

    args = p.parse_args(argv)

    if args.cmd == "solo":
        roster_paths = _expand_pdf_args(args.roster)
        # multi-PDF rich roster
        rich = build_rich_roster(
            roster_paths, team=args.team,
            alias_file=args.aliases, verbose=args.verbose,
        )
        unavail = _read_unavailable_list(args.unavailable, args.unavailable_file)
        rich = _filter_rich_roster(rich, unavail)
        roster_A = roster_view(rich, method="A")
        sol = solve_solo(roster_A, verbose=args.verbose)
        text = _render_solo(sol)
    else:
        us_paths = _expand_pdf_args(args.us)
        opp_paths = _expand_pdf_args(args.opp)
        print(f"US:  {len(us_paths)} PDF(s) for team {args.us_team}", file=sys.stderr)
        for q in us_paths: print(f"  {q}", file=sys.stderr)
        print(f"OPP: {len(opp_paths)} PDF(s) for team {args.opp_team}", file=sys.stderr)
        for q in opp_paths: print(f"  {q}", file=sys.stderr)

        us = build_rich_roster(us_paths, team=args.us_team,
                                alias_file=args.aliases, verbose=True)
        opp = build_rich_roster(opp_paths, team=args.opp_team,
                                 alias_file=args.aliases, verbose=True)
        unavail = _read_unavailable_list(args.unavailable, args.unavailable_file)
        if unavail:
            print(f"\n  excluding unavailable: {sorted(unavail)}", file=sys.stderr)
            us = _filter_rich_roster(us, unavail)

        print("\nRunning optimizer under A, B, D (symmetric on both sides)...",
              file=sys.stderr)
        report = compare_aggregations(us, opp)
        text = render_comparison(report, us, opp)

    if args.out:
        Path(args.out).write_text(text + "\n")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
