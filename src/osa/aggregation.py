"""Time aggregation strategies for multi-meet rosters.

When a swimmer has multiple recorded times in the same event (e.g. across
4 meets), we compute three signals:

  A = PR (season best)               -- the ceiling
  B = MOST RECENT meet's time         -- current form snapshot
  D = LINEAR WEIGHTED average        -- smoothed recent form

The lineup optimizer uses A by default. We also re-run it on B and D and
flag any event where the chosen swimmer would have differed -- this is the
"Audrey regressed, swap to Sydney" trigger.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TimeRecord:
    """One observed swim by a swimmer in a specific event at a specific meet."""
    time_seconds: float
    meet_date: str  # ISO YYYY-MM-DD; "" if unknown
    course: str     # "M" or "Y"


_SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}


def name_key(name: str, *, aliases: dict[str, str] | None = None) -> str:
    """Canonical identity key for swimmer matching.

    Steps:
      1. Lowercase + whitespace-normalize
      2. Strip single-letter tokens (middle initials like "R" or "J.")
      3. Strip common suffixes (Jr, Sr, II, III)
      4. Optionally map via aliases dict (variant_key -> canonical_key)

    Examples:
      'Sydney R Hergenroeder'  -> 'sydney hergenroeder'
      'SYDNEY R HERGENROEDER'  -> 'sydney hergenroeder'
      'Xander J Main'          -> 'xander main'
      'Sam Smith Jr.'          -> 'sam smith'
    """
    tokens = name.lower().split()
    # strip single-letter middle initials (optionally with trailing period)
    cleaned = []
    for t in tokens:
        bare = t.rstrip(".")
        if len(bare) == 1 and bare.isalpha():
            continue   # middle initial
        if bare in _SUFFIXES:
            continue   # suffix
        cleaned.append(bare)
    key = " ".join(cleaned)
    if aliases and key in aliases:
        return aliases[key]
    return key


def load_alias_map(path: str | "Path | None") -> dict[str, str]:
    """Load a JSON alias file mapping {canonical_name: [variant1, variant2, ...]}
    and return a flat dict mapping variant_key -> canonical_key.

    File format:
        {
          "Sydney Hergenroeder": ["Sydney R Hergenroeder", "S Hergenroeder"],
          ...
        }
    Variants and canonicals are auto-normalized through the same pipeline.
    Missing/empty file returns {}.
    """
    import json
    from pathlib import Path
    if path is None:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    out: dict[str, str] = {}
    for canonical, variants in data.items():
        # Apply name_key WITHOUT aliases (avoid recursion) to both sides
        canonical_key = name_key(canonical)
        for v in variants:
            variant_key = name_key(v)
            out[variant_key] = canonical_key
    return out


def aggregate_pr(records: list[TimeRecord]) -> float:
    """Aggregation A: personal record (minimum time)."""
    return min(r.time_seconds for r in records)


def aggregate_recent(records: list[TimeRecord]) -> float:
    """Aggregation B: most recent meet's time. Dated records sort latest first;
    undated records fall to the back."""
    # Sort by date descending; "" sorts before any dated string so we negate by
    # padding to make it sort LAST.
    def sort_key(r: TimeRecord) -> str:
        return r.meet_date or "0000-00-00"
    return sorted(records, key=sort_key, reverse=True)[0].time_seconds


def aggregate_weighted(records: list[TimeRecord]) -> float:
    """Aggregation D: linear-decay weighted average. Most recent meet gets the
    highest weight, oldest gets weight 1. Equal weight if all dates missing."""
    def sort_key(r: TimeRecord) -> str:
        return r.meet_date or "0000-00-00"
    sorted_recs = sorted(records, key=sort_key)  # oldest first
    n = len(sorted_recs)
    if n == 1:
        return sorted_recs[0].time_seconds
    # weights: 1, 2, ..., n (oldest -> newest)
    weights = list(range(1, n + 1))
    weighted_sum = sum(w * r.time_seconds for w, r in zip(weights, sorted_recs))
    return weighted_sum / sum(weights)


AGGREGATIONS = {
    "A": aggregate_pr,
    "B": aggregate_recent,
    "D": aggregate_weighted,
}


def aggregate(records: list[TimeRecord], method: str) -> float:
    """Apply the named aggregation method to a list of TimeRecord."""
    return AGGREGATIONS[method](records)
