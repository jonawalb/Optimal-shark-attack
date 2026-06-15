# OPTIMAL SHARK ATTACK

A lineup optimizer for NVSL summer-league dual meets.

You give it your team's recent meet PDFs and the opponent's recent meet PDFs.
It tells you which swimmers to enter in which events to win the meet, what
the projected score is, and where the meet might actually be closer than it
looks.

## Why this exists

Setting an NVSL lineup is a real optimization problem. ~100 swimmers, 52
events, hard rules on how many events each swimmer can do, no repeating
strokes, swim-ups allowed in some events and not others. The naive "put your
fastest swimmer in every event" doesn't work — you have a 2-event cap per
kid, so picking is a constrained assignment problem where one wrong swap
costs you 5 points.

A spreadsheet can get you 80% of the way there. Getting to the actual
optimum requires solving the whole meet jointly, which is what this does.

## What it handles

- All 52 events (40 individual + 12 relays, including the mixed-age free)
- Per-swimmer caps: 2 individual events with no stroke repeated, plus 1
  age-group relay and the mixed-age relay
- Swim-ups (older age groups only; mixed-age relay is locked by age band)
- Up to 3 entries per team per individual event (A/B/C)
- 5-3-1 scoring on individuals, 5-0 on relays, tie-splitting on both
- Conservative race-day variance — close races (within 0.3s for individuals,
  1.0s for relays) get credited to the opponent for projection
- Multi-PDF data with three time-aggregation strategies (PR, most recent,
  weighted recent) reported side-by-side

## Quickstart

```bash
# Install (Python 3.12+ and uv)
uv sync

# Put both teams' Virtual Meet PDFs into data/raw/
# Get them from mynvsl.com under Schedule/Results -> any meet -> Virtual Meet
# Use one folder per team:
data/raw/oh_2025/oh_2025-06-14.pdf
data/raw/oh_2025/oh_2025-06-21.pdf
...
data/raw/vh_2025/vh_2025-06-14.pdf
...

# Run the optimizer
uv run python -m osa.cli vs \
    --us  data/raw/oh_2025/  --us-team  OH \
    --opp data/raw/vh_2025/  --opp-team VH \
    --aliases data/aliases.json
```

You get a printable lineup card: A/B/C swimmers per event with their times
under each aggregation strategy, the relay lineups, a per-event note flagging
where recent form would change the pick, and the projected score.

## The three aggregations

When a swimmer has multiple times in the same event across the season, you
want to know all three of these:

- **A — PR** (season best). Their ceiling. The recommended lineup uses A.
- **B — most recent**. What they swam last weekend.
- **D — linear-weighted recent**. A smoothed view of recent form.

The output shows all three for each swimmer, and the projected meet score
is computed three times: once with both teams at PR, once with both at
most recent, once weighted. The shadow scores tell you how robust the
projection is — if A says you win by 50 but D says it's tied, the meet is
actually close.

Per-event narratives fire when B or D would have picked a different swimmer
than A. Example:

```
# 8  G_13-14_50_FREE                 WIN  9.0pts
    SWIMMER                       A (PR)  B (recent)   D (wtd)
    Jane Doe                       30.40       31.22     31.08
    Janette Doe                    30.46       30.46     30.73
    Jessica R Doe                  30.67  (1 data point)
    -> Note: Recent times suggest Joan Doe in for Janette Doe
```

## Race-day adjustments

If a swimmer can't make the meet:

```bash
osa vs ... --unavailable "Jane Doe,John Doe"
osa vs ... --unavailable-file friday_outs.txt
```

Re-runs the entire optimization with those swimmers removed.

## Identity matching

NVSL meet PDFs are not consistent about how they spell names. The same kid
will show up as `Jane Doe` in one PDF and `JANE R DOE` in another. If you
don't merge these, the optimizer thinks they're two different people and the
2-event cap stops working.

The identity pre-flight runs first, before any optimization:

1. Names get lowercased and whitespace-normalized
2. Single-letter "middle initial" tokens get stripped (`R`, `J.`)
3. Common suffixes get stripped (Jr, Sr, II, III)
4. `data/aliases.json` provides manual overrides for everything else

When duplicates merge, the pre-flight prints what got merged. Read it. If
two real people got collapsed into one (happens with siblings who share
initials sometimes), add an explicit override to `aliases.json`:

```json
{
  "Jane Smith-Doe": ["Jane SmithDoe", "Jane S Doe"]
}
```

Keys are display names. Values are arrays of variants to merge into the
key. Both sides run through the same normalization pipeline, so capitalization
in the JSON doesn't matter.

## Input formats

Two PDF formats are auto-detected:

- **NVSL Virtual Meet** (from mynvsl.com). 25-meter course. This is what
  you'll get for opponents you haven't swum against yet.
- **HY-TEK Individual Top Times** (from a coach's HY-TEK export). 25-yard
  course. Useful for season-long top-times rollups.

The course (meters vs yards) is tagged on every parsed time. By default the
multi-meet builder keeps METER-course data only, since mixing units gives
nonsense answers. If your league uses yards, change the `course='M'`
default in `build_rich_roster` to `course='Y'`.

## Scoring rules

From the 2026 NVSL Handbook:

- Individual events: 5-3-1 to top three (Rule 15b)
- Relays: 5-0, winner-take-all (Rule 15b)
- Meet total: 420 points; 211 clinches it
- Ties split points equally among tied swimmers (Rule 15c)

I added one thing the handbook doesn't — a conservative variance threshold
for projection. Races within 0.3s (individuals) or 1.0s (relays) get
credited to the opponent. This is because race-day noise on a 25-second 50
is around 0.3 seconds, and a "predicted win by 0.1" is really a coin flip.
You'd rather plan for the bad coin flip than the good one. Thresholds live
in `src/osa/optimize/problem2.py` and `src/osa/optimize/relays.py` if you
want to change them.

## Layout

```
.
├── README.md, LICENSE, pyproject.toml
├── data/
│   ├── aliases.json              # editable name-merge overrides
│   └── raw/                      # drop your PDFs here (gitignored)
├── src/osa/
│   ├── cli.py                    # osa solo and osa vs commands
│   ├── aggregation.py            # A/B/D time strategies + name_key
│   ├── multi_meet.py             # multi-PDF rich roster builder
│   ├── loaders.py                # single-PDF loader + availability filter
│   ├── render_compare.py         # printable lineup card with narratives
│   ├── parsing/
│   │   ├── hytek_top_times.py    # HY-TEK Top Times PDF parser
│   │   └── nvsl_virtual_meet.py  # NVSL Virtual Meet PDF parser
│   ├── rules/events.py           # 52-event NVSL dual-meet catalog
│   ├── model/roster.py           # Swimmer / Roster data model
│   ├── data/synthetic.py         # test-data generator
│   └── optimize/
│       ├── problem1.py           # MILP: best self-consistent lineup
│       ├── problem2.py           # MILP: best response vs opponent
│       ├── relays.py             # joint solver for all 12 relays
│       ├── meet.py               # combines individuals + relays
│       └── compare.py            # runs problem 2 under A/B/D
└── scripts/                      # example end-to-end demos
```

## What the model doesn't do

A few things to know before you trust the output:

1. **Deterministic seed-wins model.** No per-swimmer noise distribution.
   The conservative tie threshold is a rough proxy. Margins inside the
   threshold are treated as losses; margins outside are treated as
   certain wins. Real life is messier.

2. **Opponent is assumed to play their own optimum.** If their coach
   plays sub-optimally, you'll win by more than projected. If their
   coach is adversarially anticipating your best-response, this model
   doesn't catch that.

3. **No DQ or fragility weighting.** A swimmer with a shaky 8U breast
   pullout is treated the same as one who never DQs. Coach judgment
   required.

4. **No meet-schedule conflict checking.** NVSL events run in a fixed
   order. With the 2-event cap plus no-stroke-repeat, schedule conflicts
   are rare but possible — the model won't flag them.

5. **Mixed-age relay 8U fallback.** The mixed-age free relay is 4×50.
   If an 8U swimmer goes in the 10&U leg and has no recorded 50 free,
   their 50 time is estimated as 2.05× their 25 free.

## Using this on your own team

1. Clone the repo
2. `uv sync`
3. Download Virtual Meet PDFs for your team and your opponent from
   mynvsl.com, put them in `data/raw/YOUR_TEAM/` and `data/raw/OPP/`
4. Run `osa vs --us data/raw/YOUR_TEAM/ --us-team XX --opp data/raw/OPP/
   --opp-team YY --aliases data/aliases.json`
5. Edit `data/aliases.json` when the pre-flight reports show name
   variants that look wrong

## License

MIT. See `LICENSE`.
