"""Generate fully synthetic NVSL teams for testing the optimizer.

Time distributions are calibrated from the real OH 2022 data; team-level
"strength" and "depth" knobs let us build distinct opponents with different
profiles (deep balanced powerhouse vs star-driven vs top-heavy older squad).
Reproducible via the seed argument.
"""
from __future__ import annotations

import csv
import random
from dataclasses import dataclass
from pathlib import Path

from osa.model.roster import Roster, Swimmer, _age_group_for_age
from osa.rules.events import AGE_GROUPS, INDIVIDUAL_STROKES, AgeGroup, Gender, Stroke

# (gender, age_group, distance_yd, stroke) -> (mean_seconds, std_seconds)
# Derived from the 4 OH 2022 Top Times PDFs (boys + girls + opponents). For
# events with too-thin data we filled with neighbouring-age priors.
BASELINE_TIMES: dict[tuple[Gender, AgeGroup, int, Stroke], tuple[float, float]] = {
    ("B", "8U",    25, "FREE"):   (27.3, 5.9),
    ("B", "8U",    25, "BACK"):   (32.4, 6.9),
    ("B", "8U",    25, "BREAST"): (34.2, 5.0),
    ("B", "8U",    25, "FLY"):    (31.5, 8.6),
    ("B", "9-10",  50, "FREE"):   (48.1, 11.6),
    ("B", "9-10",  50, "BACK"):   (53.6, 8.3),
    ("B", "9-10",  50, "BREAST"): (63.2, 17.3),
    ("B", "9-10",  25, "FLY"):    (23.0, 5.0),
    ("B", "11-12", 50, "FREE"):   (41.5, 8.0),
    ("B", "11-12", 50, "BACK"):   (51.9, 10.9),
    ("B", "11-12", 50, "BREAST"): (53.7, 9.3),
    ("B", "11-12", 50, "FLY"):    (46.4, 10.5),
    ("B", "13-14", 50, "FREE"):   (32.5, 3.6),
    ("B", "13-14", 50, "BACK"):   (39.1, 4.8),
    ("B", "13-14", 50, "BREAST"): (43.5, 4.4),
    ("B", "13-14", 50, "FLY"):    (37.8, 7.5),
    ("B", "15-18", 50, "FREE"):   (27.6, 1.4),
    ("B", "15-18", 50, "BACK"):   (34.2, 4.4),
    ("B", "15-18", 50, "BREAST"): (37.8, 4.6),
    ("B", "15-18", 50, "FLY"):    (30.6, 2.3),

    ("G", "8U",    25, "FREE"):   (28.3, 5.3),
    ("G", "8U",    25, "BACK"):   (32.6, 5.6),
    ("G", "8U",    25, "BREAST"): (36.4, 7.0),
    ("G", "8U",    25, "FLY"):    (33.3, 7.0),
    ("G", "9-10",  50, "FREE"):   (47.8, 10.1),
    ("G", "9-10",  50, "BACK"):   (57.4, 11.6),
    ("G", "9-10",  50, "BREAST"): (59.8, 6.5),
    ("G", "9-10",  25, "FLY"):    (23.9, 4.0),
    ("G", "11-12", 50, "FREE"):   (38.0, 3.7),
    ("G", "11-12", 50, "BACK"):   (46.1, 5.3),
    ("G", "11-12", 50, "BREAST"): (52.7, 5.6),
    ("G", "11-12", 50, "FLY"):    (45.9, 6.5),
    ("G", "13-14", 50, "FREE"):   (37.6, 7.3),
    ("G", "13-14", 50, "BACK"):   (40.9, 3.9),
    ("G", "13-14", 50, "BREAST"): (49.3, 8.5),
    ("G", "13-14", 50, "FLY"):    (40.1, 4.0),
    ("G", "15-18", 50, "FREE"):   (33.9, 5.1),
    ("G", "15-18", 50, "BACK"):   (39.7, 7.9),
    ("G", "15-18", 50, "BREAST"): (46.3, 8.1),
    ("G", "15-18", 50, "FLY"):    (37.2, 5.0),
}


# Placeholder name pools for synthetic teams. All names are fictional; any
# resemblance to real swimmers is coincidental.
FIRST_NAMES_F = [
    "Jane", "Janette", "Jessica", "Jenny", "Julia", "Joan", "Joy", "Jada",
    "Jenna", "Jasmine", "Joanne", "Jamie", "Jocelyn", "Josephine", "Juliet",
    "June", "Jewel", "Jolie", "Janet", "Jill", "Joelle", "Jordyn", "Jolene",
    "Jeanette", "Jasper", "Jules", "Jacqueline", "Joi", "Janice", "Jerica",
]
FIRST_NAMES_M = [
    "John", "Jim", "Jack", "James", "Joe", "Joseph", "Jacob", "Jordan",
    "Julian", "Jake", "Justin", "Jeff", "Jay", "Jared", "Jason", "Josh",
    "Jeremy", "Julius", "Jerome", "Joel", "Jonah", "Jasper", "Jaden", "Jett",
    "Jude", "Junior", "Javier", "Jefferson", "Jameson", "Joaquin",
]
LAST_NAMES = [
    "Doe", "Roe", "Hayes", "Glass", "Reed", "Stone", "Nash", "Quinn", "Vance",
    "Owens", "Klein", "Adler", "Becker", "Fischer", "Tanner", "Wells", "Hale",
    "Pine", "Ash", "Ford", "Lane", "Knox", "Frost", "Holt", "Sage", "Wilde",
    "Crane", "Briar", "Vale", "Marsh", "Quill", "Brink", "Vaughn", "Thorne",
]

AGE_RANGES: dict[AgeGroup, tuple[int, int]] = {
    "8U":   (5, 8),
    "9-10": (9, 10),
    "11-12": (11, 12),
    "13-14": (13, 14),
    "15-18": (15, 18),
}


@dataclass
class TeamProfile:
    """Describes a synthetic team's identity for the generator.

    strength: multiplier on baseline mean times. <1.0 is faster (stronger team),
              >1.0 is slower. Typical range: 0.92..1.08.
    depth:    controls within-team talent spread. Higher = flatter (everyone
              similar), lower = top-heavy (a few stars, many slow). 0.5..1.5.
    age_weights: per-age-group proportion of the roster (auto-normalized).
    roster_size: target number of swimmers.
    """
    abbrev: str
    name: str
    roster_size: int
    strength: float = 1.0
    depth: float = 1.0
    age_weights: dict[AgeGroup, float] | None = None


DEFAULT_AGE_WEIGHTS: dict[AgeGroup, float] = {
    "8U": 0.20, "9-10": 0.25, "11-12": 0.25, "13-14": 0.20, "15-18": 0.10,
}


def _pick_events_for(swimmer_age_group: AgeGroup, gender: Gender,
                      rng: random.Random) -> list[tuple[int, Stroke]]:
    """Choose which events this swimmer has recorded times for.

    Most swimmers have times in free + back (universal). Breast/fly are slightly
    rarer. Distance is determined by age group (8U=25, 9-10 fly=25, else 50).
    """
    events = []
    # Always have free.
    distance = 25 if swimmer_age_group == "8U" else 50
    events.append((distance, "FREE"))
    # Back with high probability.
    if rng.random() < 0.85:
        events.append((distance, "BACK"))
    # Breast moderate.
    if rng.random() < 0.65:
        events.append((distance, "BREAST"))
    # Fly less common (technical stroke).
    if rng.random() < 0.55:
        fly_dist = 25 if swimmer_age_group in ("8U", "9-10") else 50
        events.append((fly_dist, "FLY"))
    return events


def _sample_swimmer_time(
    gender: Gender, ag: AgeGroup, distance: int, stroke: Stroke,
    team_strength: float, personal_talent: float,
    rng: random.Random,
) -> float | None:
    """Sample a single seed time, log-normal around the baseline."""
    key = (gender, ag, distance, stroke)
    if key not in BASELINE_TIMES:
        return None
    base_mean, base_std = BASELINE_TIMES[key]
    # personal_talent < 1.0 = star; > 1.0 = developing. team_strength similar.
    target_mean = base_mean * team_strength * personal_talent
    # Use log-normal with sigma derived from base_std/base_mean ratio so the
    # distribution stays right-skewed (a few slow swimmers, mass near the mean).
    sigma = max(0.05, base_std / base_mean * 0.7)
    # Mean of underlying normal so that the lognormal mean is target_mean.
    import math
    mu = math.log(target_mean) - sigma ** 2 / 2
    t = math.exp(rng.normalvariate(mu, sigma))
    return round(t, 2)


def generate_team(profile: TeamProfile, *, seed: int) -> Roster:
    """Generate a synthetic team Roster from a TeamProfile and seed."""
    rng = random.Random(seed)
    age_weights = profile.age_weights or DEFAULT_AGE_WEIGHTS
    total_w = sum(age_weights.values())
    age_probs = {ag: w / total_w for ag, w in age_weights.items()}

    used_names: set[str] = set()
    swimmers: list[Swimmer] = []

    for _ in range(profile.roster_size):
        # Pick age group, then specific age, then gender.
        ag = rng.choices(list(age_probs.keys()),
                         weights=list(age_probs.values()), k=1)[0]
        age = rng.randint(*AGE_RANGES[ag])
        gender: Gender = rng.choice(["G", "B"])
        # Unique name (try a few times before giving up).
        first_pool = FIRST_NAMES_F if gender == "G" else FIRST_NAMES_M
        for _try in range(20):
            name = f"{rng.choice(first_pool)} {rng.choice(LAST_NAMES)}"
            if name not in used_names:
                used_names.add(name)
                break
        else:
            continue  # skip if we somehow exhausted name space

        # Per-swimmer talent. Log-normal around 1.0; depth controls spread.
        # depth>1.0 = tight (everyone similar); depth<1.0 = wide (stars+slow).
        import math
        talent_sigma = 0.15 / profile.depth
        personal_talent = math.exp(rng.normalvariate(0, talent_sigma))
        # clip so we don't get absurd outliers
        personal_talent = max(0.75, min(1.5, personal_talent))

        # Events the swimmer has times in.
        chosen = _pick_events_for(ag, gender, rng)
        # 25% chance they also have a swim-up time in the next group.
        if rng.random() < 0.25:
            idx = AGE_GROUPS.index(ag)
            if idx + 1 < len(AGE_GROUPS):
                up_group = AGE_GROUPS[idx + 1]
                up_dist = 25 if up_group == "8U" else 50
                up_stroke = rng.choice(["FREE", "BACK"])
                up_t = _sample_swimmer_time(
                    gender, up_group, up_dist, up_stroke,
                    profile.strength, personal_talent * 1.08, rng,
                )
                if up_t is not None:
                    # placeholder; we'll attach via event_id below
                    pass

        best_times: dict[str, float] = {}
        for dist, stroke in chosen:
            t = _sample_swimmer_time(
                gender, ag, dist, stroke,
                profile.strength, personal_talent, rng,
            )
            if t is not None:
                event_id = f"{gender}_{ag}_{dist}_{stroke}"
                best_times[event_id] = t

        if not best_times:
            continue

        swimmers.append(Swimmer(
            name=name, age=age, gender=gender, team=profile.abbrev,
            best_times=best_times,
        ))

    return Roster(team=profile.abbrev, swimmers=swimmers)


def roster_to_csv(roster: Roster, path: Path) -> None:
    """Save a Roster as long-form CSV (one row per swimmer-event)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["team", "name", "age", "gender", "event_id", "time_seconds"])
        for s in roster.swimmers:
            for eid, t in s.best_times.items():
                w.writerow([s.team, s.name, s.age, s.gender, eid, f"{t:.2f}"])


def roster_from_csv(path: Path) -> Roster:
    """Load a Roster from a long-form CSV produced by roster_to_csv."""
    from collections import defaultdict
    grouped: dict[tuple[str, int, str], dict[str, float]] = defaultdict(dict)
    gender_map: dict[tuple[str, int, str], Gender] = {}
    team = None
    with Path(path).open() as f:
        for row in csv.DictReader(f):
            team = row["team"]
            key = (row["name"], int(row["age"]), row["team"])
            grouped[key][row["event_id"]] = float(row["time_seconds"])
            gender_map[key] = row["gender"]  # type: ignore
    swimmers = [
        Swimmer(name=name, age=age, gender=gender_map[(name, age, t)],
                team=t, best_times=times)
        for (name, age, t), times in grouped.items()
    ]
    return Roster(team=team or "?", swimmers=swimmers)


# Four reference team profiles for testing.
TEST_TEAM_PROFILES = [
    TeamProfile(
        abbrev="SHK", name="Sharks",
        roster_size=110, strength=0.94, depth=1.2,  # strong, deep, balanced
    ),
    TeamProfile(
        abbrev="DOL", name="Dolphins",
        roster_size=85, strength=1.05, depth=0.65,  # weaker overall but star-heavy
    ),
    TeamProfile(
        abbrev="OTR", name="Otters",
        roster_size=95, strength=1.00, depth=1.0,   # average / balanced
    ),
    TeamProfile(
        abbrev="MNT", name="Manta Rays",
        roster_size=100, strength=0.97, depth=1.0,  # solid; older-group skewed
        age_weights={"8U": 0.10, "9-10": 0.15, "11-12": 0.25, "13-14": 0.25, "15-18": 0.25},
    ),
]
