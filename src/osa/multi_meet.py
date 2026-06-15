"""Build a Roster from MULTIPLE meet PDFs, retaining full time history.

Auto-detects HY-TEK Top Times vs NVSL Virtual Meet format per PDF. Each
swimmer's (event_id, TimeRecord) observations are accumulated across PDFs,
keyed by canonical lowercase full name. Per user spec, METER-course data only
is retained (yards data is dropped before aggregation).

Produces a RichRoster object whose `swimmers` carry full TimeRecord histories.
For optimizer input, use `roster_view(rich_roster, method='A')` to materialize
a regular Roster whose `best_times` reflect the chosen aggregation.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from osa.aggregation import TimeRecord, aggregate, load_alias_map, name_key
from osa.model.roster import Roster, Swimmer
from osa.parsing.hytek_top_times import Entry, parse_top_times
from osa.parsing.nvsl_virtual_meet import parse_virtual_meet


@dataclass
class RichSwimmer:
    """A swimmer with full time history across all meets."""
    name: str               # canonical display name (first seen capitalization)
    age: int                # most recently observed age
    gender: str
    team: str
    history: dict[str, list[TimeRecord]] = field(default_factory=dict)

    @property
    def natural_age_group(self) -> str:
        if self.age <= 8: return "8U"
        if self.age <= 10: return "9-10"
        if self.age <= 12: return "11-12"
        if self.age <= 14: return "13-14"
        return "15-18"


@dataclass
class RichRoster:
    team: str
    swimmers: list[RichSwimmer]


def _autodetect_and_parse(pdf_path: Path, team: str) -> list[Entry]:
    """Detect HY-TEK vs Virtual Meet format and parse accordingly."""
    import pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        first_page_text = pdf.pages[0].extract_text() or ""
    if "VIRTUAL MEET" in first_page_text or "mynvsl.com" in first_page_text:
        return parse_virtual_meet(pdf_path, team=team)
    if "HY-TEK" in first_page_text or "Individual T" in first_page_text:
        entries = parse_top_times(pdf_path)
        return [e for e in entries if e.team == team]
    raise ValueError(f"Unrecognized PDF format: {pdf_path}")


def _preflight_identity_report(
    entries_by_pdf: list[tuple[Path, list[Entry]]],
    aliases: dict[str, str],
    verbose: bool = True,
) -> None:
    """Print which name variants are being merged into one swimmer identity.

    This runs FIRST (before aggregation) so the user can spot merges that
    look wrong and add overrides to the alias file. Each canonical key gets
    one line listing all the surface-form spellings rolled into it.
    """
    if not verbose:
        return
    variants_by_key: dict[str, set[str]] = defaultdict(set)
    for _, entries in entries_by_pdf:
        for e in entries:
            key = name_key(e.swimmer_name, aliases=aliases)
            variants_by_key[key].add(e.swimmer_name)

    merged = [(k, v) for k, v in variants_by_key.items() if len(v) > 1]
    if not merged:
        print("  identity check: no name variants detected (clean data)")
        return
    print(f"  identity check: {len(merged)} swimmer(s) had multiple name "
          f"spellings -- merged into one identity each:")
    for canonical_key, variants in sorted(merged):
        sorted_variants = sorted(variants)
        print(f"    [{canonical_key}]  <- " + "  |  ".join(sorted_variants))


def build_rich_roster(pdf_paths: list[str | Path], team: str,
                       *, course: str = "M",
                       alias_file: str | Path | None = None,
                       verbose: bool = True) -> RichRoster:
    """Aggregate time observations for `team` across all PDFs.

    `course='M'` keeps only meter-course data (user-specified default).
    `alias_file` optionally points to a JSON file mapping
        {"Canonical Name": ["Variant 1", "Variant 2"], ...}
    used to merge edge cases that auto middle-initial stripping can't catch.

    A pre-flight pass runs first: it groups all entries by canonical key and
    reports which name spellings are being merged into one swimmer (so you
    can spot a wrong merge before the optimizer runs).
    """
    aliases = load_alias_map(alias_file) if alias_file else {}

    # Phase 1: parse all PDFs, then run identity pre-flight.
    parsed: list[tuple[Path, list[Entry]]] = []
    for pdf_path in pdf_paths:
        entries = _autodetect_and_parse(Path(pdf_path), team=team)
        parsed.append((Path(pdf_path), entries))
    if verbose:
        print(f"  identity pre-flight for team={team} across {len(parsed)} PDF(s)...")
    _preflight_identity_report(parsed, aliases, verbose=verbose)

    # Phase 2: aggregate into buckets keyed by canonical name.
    by_swimmer: dict[str, dict] = defaultdict(
        lambda: {"display_name": None, "ages": [], "gender": None,
                 "history": defaultdict(list)})

    for _pdf_path, entries in parsed:
        for e in entries:
            if course is not None and e.course != course:
                continue
            key = name_key(e.swimmer_name, aliases=aliases)
            bucket = by_swimmer[key]
            # Prefer the longest available display name (with middle initial)
            # for unambiguous identification.
            if bucket["display_name"] is None or \
               len(e.swimmer_name) > len(bucket["display_name"]):
                bucket["display_name"] = e.swimmer_name
            bucket["ages"].append((e.meet_date or "", e.swimmer_age))
            bucket["gender"] = e.gender
            bucket["history"][e.event_id].append(TimeRecord(
                time_seconds=e.time_seconds,
                meet_date=e.meet_date,
                course=e.course,
            ))

    swimmers: list[RichSwimmer] = []
    for key, bucket in by_swimmer.items():
        if not bucket["history"]:
            continue
        # Use the age observed in the most recent meet (largest date).
        ages_sorted = sorted(bucket["ages"], key=lambda p: p[0] or "0000-00-00")
        most_recent_age = ages_sorted[-1][1]
        swimmers.append(RichSwimmer(
            name=bucket["display_name"],
            age=most_recent_age,
            gender=bucket["gender"],
            team=team,
            history=dict(bucket["history"]),
        ))

    return RichRoster(team=team, swimmers=swimmers)


def roster_view(rich: RichRoster, method: str = "A") -> Roster:
    """Materialize a regular Roster whose best_times use the named aggregation
    method ('A' = PR, 'B' = most recent, 'D' = linear weighted)."""
    swimmers = []
    for rs in rich.swimmers:
        best = {ev_id: aggregate(records, method)
                for ev_id, records in rs.history.items()}
        swimmers.append(Swimmer(
            name=rs.name, age=rs.age, gender=rs.gender, team=rs.team,
            best_times=best,
        ))
    return Roster(team=rich.team, swimmers=swimmers)
