# OH (Orange Hunt Sharks) Program-Specific Rules

These are local conventions for the **Orange Hunt Sharks** program that
**override the default NVSL handbook rules** encoded in `src/osa/rules/events.py`.
Apply these as a post-processing filter on the optimizer's output (or via a
program flag, e.g. `--program OH`) before printing the lineup card.

> If you ever generate an OH lineup card and these rules are not applied,
> **the card is wrong** — stop and re-run with the OH overrides.

---

## Rule OH-1: No 8 & Under Medley Relay

The OH program does **not** swim the 8&U Medley Relay (either gender).

- Drop `G_8U_MEDLEY_RELAY` and `B_8U_MEDLEY_RELAY` from any lineup output.
- Do **not** assign swimmers to those events.
- 9-10 / 11-12 / 13-14 / 15-18 medley relays are unaffected and follow
  standard NVSL conventions.

The default `EVENT_CATALOG` in `rules/events.py` includes both 8U medley
relays because that is the NVSL handbook default. The OH program filters
them out at the program layer; the catalog itself should stay
standards-compliant.

## Rule OH-2: 8 & Under Free Relay order

The 8&U Free Relay (both genders) uses a fixed swim order:

| Leg | Slot                |
|-----|---------------------|
| 1   | 2nd-fastest 25 Free |
| 2   | 4th-fastest 25 Free |
| 3   | 3rd-fastest 25 Free |
| 4   | **1st-fastest** (anchor) |

Pick the four fastest 25 Free swimmers for that gender off the ladder, then
slot them in the order above. **Do not** sort by time ascending or use the
optimizer's default ordering for 8&U free relays.

All other age groups (9-10 through 15-18) continue to use the optimizer's
default free relay ordering (typically slowest → fastest, anchor = #1).

---

## Implementation checklist

When wiring these into the code, the lightest-touch change is:

1. Add a `--program OH` (or equivalent) flag to `osa.cli`.
2. In the relay assembly step (`optimize/relays.py`), after solving:
   - If `program == "OH"` and `relay.age_group == "8U"` and
     `relay.kind == "MEDLEY_RELAY"` → drop the relay from the chosen list.
   - If `program == "OH"` and `relay.age_group == "8U"` and
     `relay.kind == "FREE_RELAY"` → re-order assignments to
     `[2nd, 4th, 3rd, 1st]` by 25 Free seed time.
3. In `render_compare.py`, suppress the 8U Medley row when `program == "OH"`.

Until the flag exists, treat this document as the authority: manually edit
the lineup card before it ships.

---

*Recorded 2026-06-19 from coach guidance. Source: maintainer instruction
during a manual lineup build. Update this file if the program ever adopts
the standard NVSL 8U medley relay.*
