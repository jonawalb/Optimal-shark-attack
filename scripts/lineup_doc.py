"""Build a Word document of the OH lineup, grouped by age group.

Solo mode:
    python scripts/lineup_doc.py solo \
        --roster data/raw/oh_2026/ --team OH \
        --aliases data/aliases.json --out OH_Lineup.docx

VS mode (head-to-head vs another team):
    python scripts/lineup_doc.py vs \
        --us data/raw/oh_2026/ --us-team OH \
        --opp data/raw/vh_2026/ --opp-team VH \
        --aliases data/aliases.json --out OH_vs_VH_Lineup.docx

Outputs a structured JSON to a temp file then pipes it into the Node renderer
(_lineup_doc.js). Age-group order: 8U boys -> 9-10 boys -> ... -> 15-18 boys
-> mixed-age boys -> 8U girls -> ... -> 15-18 girls -> mixed-age girls.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from osa.multi_meet import build_rich_roster, roster_view  # noqa: E402
from osa.optimize.meet import solve_solo, solve_vs  # noqa: E402
from osa.rules.events import EVENT_CATALOG  # noqa: E402


AGE_ORDER = ("8U", "9-10", "11-12", "13-14", "15-18")
STROKE_ORDER = ("FREE", "BACK", "BREAST", "FLY")


def _expand(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            out.extend(sorted(path.glob("*.pdf")))
        else:
            out.append(path)
    return sorted(set(out))


def _individual_event_dict(ev, our_picks, opp_picks, mode):
    """Build per-event dict for the JSON intermediate."""
    us_list = []
    if our_picks:
        # our_picks is a list of either Assignment (solo) or HeadToHeadAssignment (vs)
        sorted_picks = sorted(our_picks, key=lambda a: a.time_seconds)
        for slot, a in zip("ABC", sorted_picks):
            entry = {
                "slot": slot,
                "name": a.swimmer.name,
                "time": float(a.time_seconds),
            }
            if mode == "vs":
                entry["points"] = float(getattr(a, "points_earned", 0.0))
                entry["place"] = int(getattr(a, "predicted_place", 0))
            else:
                # swim-up note in solo mode
                if a.swimmer.natural_age_group != ev.age_group:
                    entry["swim_up"] = a.swimmer.natural_age_group
            us_list.append(entry)

    opp_list = []
    if mode == "vs":
        for i, t in enumerate(opp_picks[:3]):
            opp_list.append({"slot": "ABC"[i], "name": "", "time": float(t)})

    out = {
        "event_id": ev.event_id,
        "event_number": ev.number,
        "stroke": ev.stroke,
        "distance": ev.lengths * 25,
        "us": us_list,
        "opp": opp_list,
    }
    if mode == "vs":
        our_pts = sum(a.get("points", 0.0) for a in us_list)
        # opp gets the rest of the 9 possible points (5+3+1) when both field
        from osa.optimize.problem2 import PointsByPlace
        max_places = min(3, len(us_list) + len(opp_list))
        awarded = sum(PointsByPlace[i] for i in range(max_places))
        opp_pts = awarded - our_pts
        out["our_pts"] = our_pts
        out["opp_pts"] = opp_pts
        out["result"] = (
            "WIN" if our_pts > opp_pts
            else "LOSS" if our_pts < opp_pts
            else "TIE"
        )
    return out


def _opp_swimmer_lookup(opp_roster, opp_lineup, event_id):
    """Map opponent times back to swimmer names for display in vs mode."""
    times = opp_lineup.get(event_id, []) if opp_lineup else []
    name_for = {}
    if opp_roster is None:
        return [{"time": t, "name": ""} for t in times]
    for s in opp_roster.swimmers:
        t = s.best_times.get(event_id)
        if t is not None and t not in name_for:
            name_for[t] = s.name
    return [{"time": t, "name": name_for.get(t, "")} for t in times]


def _relay_dict(rel_lu, opp_total, mode):
    if rel_lu is None:
        return None
    legs = [
        {"label": leg.label, "name": leg.swimmer.name, "time": float(leg.time_seconds)}
        for leg in rel_lu.legs
    ]
    out = {
        "event_id": rel_lu.relay.event_id,
        "event_number": rel_lu.relay.number,
        "kind": rel_lu.relay.kind,
        "us_legs": legs,
        "us_total": float(rel_lu.total_seconds),
        "opp_total": float(opp_total) if opp_total is not None else None,
    }
    return out


def build_solo(rich, alias_file: Path | None, verbose: bool):
    roster = roster_view(rich, method="A")
    sol = solve_solo(roster, verbose=verbose)
    per_event = sol.individuals.per_event()
    relays_by_id = {lu.relay.event_id: lu for lu in sol.relays.chosen}

    by_age_gender = []
    for gender in ("B", "G"):
        for ag in AGE_ORDER:
            individuals = []
            for st in STROKE_ORDER:
                evid = f"{gender}_{ag}_{25 if (ag == '8U' or (ag == '9-10' and st == 'FLY')) else 50}_{st}"
                ev = next((e for e in EVENT_CATALOG if e.event_id == evid), None)
                if ev is None:
                    continue
                picks = per_event.get(evid, [])
                individuals.append(_individual_event_dict(ev, picks, [], "solo"))
            # relay
            rev_kind = "FREE_RELAY" if ag == "8U" else "MEDLEY_RELAY"
            relay_id = f"{gender}_{ag}_{rev_kind}"
            relay_lu = relays_by_id.get(relay_id)
            by_age_gender.append({
                "gender": gender,
                "age_group": ag,
                "individuals": individuals,
                "relay": _relay_dict(relay_lu, None, "solo"),
            })

    mixed_age = {}
    for gen in ("B", "G"):
        rel_id = f"{gen}_MIXED_AGE_FREE_RELAY"
        lu = relays_by_id.get(rel_id)
        mixed_age[gen] = _relay_dict(lu, None, "solo")

    return {
        "mode": "solo",
        "us_team": rich.team,
        "us_swimmers_count": len(rich.swimmers),
        "generated": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "by_age_gender": by_age_gender,
        "mixed_age": mixed_age,
    }


def build_vs(us_rich, opp_rich, alias_file: Path | None, verbose: bool):
    us_roster = roster_view(us_rich, method="A")
    opp_roster = roster_view(opp_rich, method="A")
    sol = solve_vs(us_roster, opp_roster, verbose=verbose)
    per_event = sol.individuals.per_event()
    opp_lineup = sol.individuals.opp_lineup
    relays_by_id = {lu.relay.event_id: lu for lu in sol.relays.chosen}

    # Opp relay times: re-solve P1 for opp to get the times they'd field.
    from osa.optimize.relays import opponent_relay_times
    opp_rel_times = opponent_relay_times(opp_roster)

    by_age_gender = []
    for gender in ("B", "G"):
        for ag in AGE_ORDER:
            individuals = []
            for st in STROKE_ORDER:
                evid = f"{gender}_{ag}_{25 if (ag == '8U' or (ag == '9-10' and st == 'FLY')) else 50}_{st}"
                ev = next((e for e in EVENT_CATALOG if e.event_id == evid), None)
                if ev is None:
                    continue
                picks = per_event.get(evid, [])
                opp_with_names = _opp_swimmer_lookup(opp_roster, opp_lineup, evid)
                ev_dict = _individual_event_dict(ev, picks, [], "vs")
                ev_dict["opp"] = [
                    {"slot": "ABC"[i], "name": o["name"], "time": o["time"]}
                    for i, o in enumerate(opp_with_names[:3])
                ]
                individuals.append(ev_dict)
            rev_kind = "FREE_RELAY" if ag == "8U" else "MEDLEY_RELAY"
            relay_id = f"{gender}_{ag}_{rev_kind}"
            relay_lu = relays_by_id.get(relay_id)
            opp_t = opp_rel_times.get(relay_id)
            by_age_gender.append({
                "gender": gender,
                "age_group": ag,
                "individuals": individuals,
                "relay": _relay_dict(relay_lu, opp_t, "vs"),
            })

    mixed_age = {}
    for gen in ("B", "G"):
        rel_id = f"{gen}_MIXED_AGE_FREE_RELAY"
        lu = relays_by_id.get(rel_id)
        opp_t = opp_rel_times.get(rel_id)
        mixed_age[gen] = _relay_dict(lu, opp_t, "vs")

    totals = {
        "us_total_points": float(sol.our_total_points or 0),
        "opp_total_points": float(sol.opp_total_points or 0),
        "verdict": (
            "WIN" if (sol.our_total_points or 0) > (sol.opp_total_points or 0)
            else "LOSS" if (sol.our_total_points or 0) < (sol.opp_total_points or 0)
            else "TIE"
        ),
    }

    return {
        "mode": "vs",
        "us_team": us_rich.team,
        "opp_team": opp_rich.team,
        "us_swimmers_count": len(us_rich.swimmers),
        "opp_swimmers_count": len(opp_rich.swimmers),
        "generated": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "by_age_gender": by_age_gender,
        "mixed_age": mixed_age,
        "totals": totals,
    }


def main(argv=None):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    p_solo = sub.add_parser("solo")
    p_solo.add_argument("--roster", nargs="+", required=True)
    p_solo.add_argument("--team", required=True)
    p_solo.add_argument("--aliases")
    p_solo.add_argument("--course", default="Y")
    p_solo.add_argument("--out", required=True)
    p_solo.add_argument("--verbose", action="store_true")

    p_vs = sub.add_parser("vs")
    p_vs.add_argument("--us", nargs="+", required=True)
    p_vs.add_argument("--us-team", required=True)
    p_vs.add_argument("--opp", nargs="+", required=True)
    p_vs.add_argument("--opp-team", required=True)
    p_vs.add_argument("--aliases")
    p_vs.add_argument("--course", default="Y")
    p_vs.add_argument("--out", required=True)
    p_vs.add_argument("--verbose", action="store_true")

    args = p.parse_args(argv)

    if args.cmd == "solo":
        rich = build_rich_roster(
            _expand(args.roster), team=args.team,
            course=args.course, alias_file=args.aliases, verbose=args.verbose,
        )
        data = build_solo(rich, args.aliases, args.verbose)
    else:
        us = build_rich_roster(
            _expand(args.us), team=args.us_team,
            course=args.course, alias_file=args.aliases, verbose=args.verbose,
        )
        opp = build_rich_roster(
            _expand(args.opp), team=args.opp_team,
            course=args.course, alias_file=args.aliases, verbose=args.verbose,
        )
        data = build_vs(us, opp, args.aliases, args.verbose)

    out_path = Path(args.out).resolve()
    js = REPO / "scripts" / "_lineup_doc.js"
    payload = json.dumps(data).encode("utf-8")
    import os
    env = os.environ.copy()
    npm_root = subprocess.run(
        ["npm", "root", "-g"], capture_output=True, text=True, check=True,
    ).stdout.strip()
    env["NODE_PATH"] = npm_root + (":" + env["NODE_PATH"] if env.get("NODE_PATH") else "")
    res = subprocess.run(
        ["node", str(js), str(out_path)],
        input=payload, check=True, env=env,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
