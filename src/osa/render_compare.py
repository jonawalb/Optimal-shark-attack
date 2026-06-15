"""Render a head-to-head ComparisonReport as a printable lineup card.

Per user spec:
  * Recommended lineup uses aggregation A (PR).
  * Each chosen swimmer's row shows A / B / D times.
  * Single-data-point swimmers show only one column (A == B == D).
  * Below any event where B or D would have picked different swimmers,
    a one-sentence narrative explains the swap.
"""
from __future__ import annotations

from osa.optimize.compare import ComparisonReport, narrative
from osa.rules.events import EVENT_CATALOG


def _fmt(t: float) -> str:
    if t >= 60:
        return f"{int(t//60)}:{t-int(t//60)*60:05.2f}"
    return f"{t:5.2f}"


def render_comparison(report: ComparisonReport, our_rich, opp_rich) -> str:
    """Format the comparison report as a printable lineup."""
    lines: list[str] = []
    sol = report.solution_A
    lines.append("=" * 100)
    lines.append("  BEST-RESPONSE LINEUP  (recommended on A = PR; B/D shown for context)")
    lines.append("=" * 100)
    lines.append("")
    lines.append(f"  US:  {our_rich.team}  ({len(our_rich.swimmers)} swimmers)")
    lines.append(f"  OPP: {opp_rich.team} ({len(opp_rich.swimmers)} swimmers)")
    lines.append("")
    lines.append("  Legend:  A=PR (season best)  B=most recent  D=linear-weighted recent")
    lines.append("")
    lines.append("INDIVIDUAL EVENTS")
    lines.append("-" * 100)

    # Lookup: swimmer name -> RichSwimmer
    rich_by_name = {s.name: s for s in our_rich.swimmers}

    per_event = sol.individuals.per_event()
    for ev in (e for e in EVENT_CATALOG if e.kind == "INDIVIDUAL"):
        picks = sorted(per_event.get(ev.event_id, []), key=lambda a: a.time_seconds)
        ev_comp = report.per_event.get(ev.event_id)
        opp_times = sol.individuals.opp_lineup.get(ev.event_id, [])
        our_pts = sum(a.points_earned for a in picks)
        win_marker = "WIN " if our_pts >= 5 and our_pts > (
            9 - our_pts if opp_times else 0) else "    "

        lines.append(f"  #{ev.number:2d}  {ev.event_id:30s}  "
                     f"{win_marker} {our_pts}pts  opp times: "
                     + "  ".join(_fmt(t) for t in opp_times[:3]))

        if not picks:
            lines.append(f"      (no eligible US swimmers)")
            continue

        # Header row for A/B/D columns
        lines.append(f"      {'SWIMMER':25s}  {'A (PR)':>9s} {'B (recent)':>11s} {'D (wtd)':>9s}")
        for a in picks:
            rich = rich_by_name.get(a.swimmer.name)
            if rich is None:
                # fallback -- shouldn't happen with multi-meet flow
                lines.append(f"      {a.swimmer.name:25s}  {_fmt(a.time_seconds):>9s}")
                continue
            records = rich.history.get(ev.event_id, [])
            if len(records) <= 1:
                # single data point -- show one time only
                t = a.time_seconds
                lines.append(f"      {a.swimmer.name:25s}  {_fmt(t):>9s}  "
                             f"(1 data point)")
            else:
                from osa.aggregation import aggregate
                ta = aggregate(records, "A")
                tb = aggregate(records, "B")
                td = aggregate(records, "D")
                lines.append(
                    f"      {a.swimmer.name:25s}  {_fmt(ta):>9s} "
                    f"{_fmt(tb):>11s} {_fmt(td):>9s}"
                )

        # Narrative -- only if B or D would have picked different swimmers
        if ev_comp is not None:
            note = narrative(ev_comp)
            if note:
                lines.append(f"      → Note: {note}")

    # Add relays section (we use the A-run's relay solution for display)
    lines.append("")
    lines.append("RELAYS  (lineup recommended under A)")
    lines.append("-" * 100)
    rel = sol.relays
    by_id = {lu.relay.event_id: lu for lu in rel.chosen}
    for ev in (e for e in EVENT_CATALOG if e.is_relay):
        lu = by_id.get(ev.event_id)
        if lu is None:
            lines.append(f"  #{ev.number:2d}  {ev.event_id:30s}  -- not fielded --")
            continue
        legs_str = "  ".join(
            f"{l.label[:3]} {_fmt(l.time_seconds)} {l.swimmer.name}"
            for l in lu.legs
        )
        lines.append(f"  #{ev.number:2d}  {ev.event_id:30s}  total "
                     f"{_fmt(lu.total_seconds)}")
        for l in lu.legs:
            lines.append(f"        {l.label:6s} {_fmt(l.time_seconds):>7s}  {l.swimmer.name}")

    # Final scores under all three aggregations
    lines.append("")
    lines.append("=" * 100)
    def _verdict(us, them):
        if us > them: return "WIN"
        if us < them: return "LOSS"
        return "TIE"
    if sol.our_total_points is not None:
        lines.append(f"  PROJECTED FINAL SCORE  (under A = PR symmetric):    "
                     f"US {sol.our_total_points:6.1f} - {sol.opp_total_points:6.1f} OPP"
                     f"  [{_verdict(sol.our_total_points, sol.opp_total_points)}]")
    if report.solution_B.our_total_points is not None:
        lines.append(f"  shadow score under B (most recent symmetric):       "
                     f"{report.solution_B.our_total_points:6.1f} - "
                     f"{report.solution_B.opp_total_points:6.1f}"
                     f"  [{_verdict(report.solution_B.our_total_points, report.solution_B.opp_total_points)}]")
    if report.solution_D.our_total_points is not None:
        lines.append(f"  shadow score under D (weighted symmetric):          "
                     f"{report.solution_D.our_total_points:6.1f} - "
                     f"{report.solution_D.opp_total_points:6.1f}"
                     f"  [{_verdict(report.solution_D.our_total_points, report.solution_D.opp_total_points)}]")
    lines.append("")
    lines.append(f"  Scoring rules: 211 to clinch out of 420.  Conservative variance:")
    lines.append(f"  individual ties (<= 0.3s margin) and relay ties (<= 1.0s margin)")
    lines.append(f"  are credited to the opponent for projection.")
    lines.append("=" * 100)
    return "\n".join(lines)
