#!/usr/bin/env python3
"""Exact reach for an arbitrary panel combination, from simulation ground truth.

panel_metrics.csv and panel_pair_overlap.csv only ever emit single-panel and
pairwise aggregates. run_batch_simulation.py's write_reach_bitsets() persists
the same per-agent exposure bitset each panel's numbers are computed from
(one bit per WEEKLY_UNIQUES agent id, per panel). Reach for any combination --
any subset of one mall's panels, or a mix across malls -- is the OR of the
selected panels' bitsets, popcounted. That is not an approximation of what the
simulation would report for that combination: it is the same computation
panel_metrics.csv's own numbers come from, just stopped one step earlier.

Two independently-simulated malls have disjoint agent-id spaces (Newmarket's
person_idx 42 and Albany's person_idx 42 are unrelated people), so a
cross-mall combination is exact, ordinary addition -- there is no pairwise
overlap to reason about, because there is no shared identity space to
intersect against.

For anything beyond 1 week, the simulation itself has no answer -- it has no
concept of a person returning (or not) in a later week. WEEKLY_REPEAT_RATE
below is an explicit, undata-backed PLACEHOLDER standing in for that until a
real week-over-week repeat-visit figure exists (from MAID ping data or
otherwise). It feeds a standard saturating reach curve:

    cumulative(N weeks) = W * (1 - r**N) / (1 - r)

where W is the exact 1-week bitset reach and r is the repeat rate. At N=1
this equals W exactly (the simulation's own number, untouched). As N grows it
saturates at W / (1 - r) -- with r=0.5 that ceiling is 2x the 1-week figure.
This shape (each week's *new* people shrink geometrically rather than the
same fixed count every week) needs only r, not a second invented
population-size ceiling, but it is still a bolt-on assumption sitting on top
of the simulation's ground truth, not something the simulation itself
produced. Replace WEEKLY_REPEAT_RATE the moment a real figure exists.

Usage:
    python3 reach_query.py 27000 27001 27035
    python3 reach_query.py --panels 27000,27001,27035
    python3 reach_query.py --panels 27000,27001,27035 --weeks 4
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

import malls

ROOT = Path(__file__).resolve().parent

# PLACEHOLDER -- see module docstring. Not derived from data; replace when a
# real week-over-week repeat-visit figure exists.
WEEKLY_REPEAT_RATE = 0.5


def cumulative_reach_over_weeks(week1_reach: int, weeks: int, repeat_rate: float = WEEKLY_REPEAT_RATE) -> float:
    """Saturating reach curve: cumulative(1) == week1_reach exactly; as weeks
    grows this approaches week1_reach / (1 - repeat_rate). See module docstring.
    """
    if weeks <= 0:
        raise ValueError("weeks must be >= 1")
    if repeat_rate <= 0:
        return week1_reach * weeks
    if repeat_rate >= 1:
        return week1_reach
    return week1_reach * (1 - repeat_rate**weeks) / (1 - repeat_rate)


class MallReachIndex:
    """Lazily-loaded bitset index for one mall's simulation output."""

    def __init__(self, mall: malls.Mall):
        self.mall = mall
        npz_path = mall.path("results_dir") / "panel_reach_bitsets.npz"
        if not npz_path.exists():
            raise FileNotFoundError(
                f"{npz_path} not found -- run "
                f"`python3 run_batch_simulation.py --mall {mall.key}` first "
                "(it now writes this alongside panel_metrics.csv)."
            )
        data = np.load(npz_path)
        self.panel_ids = [str(p) for p in data["panel_ids"]]
        self.reach_bits = data["reach_bits"]
        self.weekly_uniques = int(data["weekly_uniques"])
        self._row_by_panel = {pid: i for i, pid in enumerate(self.panel_ids)}

    def reach_for(self, panel_ids: list[str]) -> tuple[int, list[str]]:
        """Exact unique reach for panel_ids that belong to this mall.

        Returns (reach, missing_panel_ids); missing ids are simply the ones
        this mall's index doesn't recognise. reach_for_panels() already
        pre-filters each mall's list before calling this, so callers going
        through it never see a non-empty missing list here.
        """
        rows = []
        missing = []
        for pid in panel_ids:
            row = self._row_by_panel.get(pid)
            if row is None:
                missing.append(pid)
            else:
                rows.append(row)
        if not rows:
            return 0, missing
        union = np.zeros(self.reach_bits.shape[1], dtype=np.uint8)
        for r in rows:
            union |= self.reach_bits[r]
        return int(np.unpackbits(union).sum()), missing


def load_all_mall_indexes() -> dict[str, MallReachIndex]:
    indexes = {}
    for key, mall in malls.MALLS.items():
        npz_path = mall.path("results_dir") / "panel_reach_bitsets.npz"
        if npz_path.exists():
            indexes[key] = MallReachIndex(mall)
    return indexes


def reach_for_panels(
    panel_ids: list[str],
    indexes: dict[str, MallReachIndex] | None = None,
    weeks: int = 1,
    repeat_rate: float = WEEKLY_REPEAT_RATE,
) -> dict:
    """Exact 1-week combined reach across an arbitrary, possibly cross-mall,
    panel list, optionally projected to `weeks` via cumulative_reach_over_weeks.

    Cross-mall reach is plain addition -- see module docstring for why that
    is exact rather than an approximation. The multi-week projection is
    applied per mall then summed; since the curve is linear in week1_reach
    for a shared repeat_rate, that is identical to applying it once to the
    combined total, but keeps the door open to a per-mall repeat_rate later.
    """
    if indexes is None:
        indexes = load_all_mall_indexes()

    remaining = set(panel_ids)
    per_mall = {}
    for key, idx in indexes.items():
        requested_here = [p for p in panel_ids if p in idx._row_by_panel]
        if not requested_here:
            continue
        reach, _ = idx.reach_for(requested_here)
        entry = {"panels": requested_here, "week1_reach": reach}
        if weeks > 1:
            entry["cumulative_reach"] = cumulative_reach_over_weeks(reach, weeks, repeat_rate)
        per_mall[key] = entry
        remaining -= set(requested_here)

    total_week1 = sum(m["week1_reach"] for m in per_mall.values())
    result = {
        "weeks": weeks,
        "total_week1_reach": total_week1,
        "by_mall": per_mall,
        "unresolved_panel_ids": sorted(remaining),
    }
    if weeks > 1:
        result["total_cumulative_reach"] = sum(m["cumulative_reach"] for m in per_mall.values())
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("panels", nargs="*", help="panel ids as positional args")
    p.add_argument("--panels", dest="panels_csv", help="panel ids as one comma-separated string")
    p.add_argument("--weeks", type=int, default=1, help="campaign duration in weeks (default 1)")
    p.add_argument(
        "--repeat-rate",
        type=float,
        default=WEEKLY_REPEAT_RATE,
        help=f"PLACEHOLDER weekly repeat-visit rate, 0-1 (default {WEEKLY_REPEAT_RATE}; see module docstring)",
    )
    args = p.parse_args()

    panel_ids = list(args.panels)
    if args.panels_csv:
        panel_ids += [x.strip() for x in args.panels_csv.split(",") if x.strip()]
    if not panel_ids:
        p.error("no panel ids given")

    result = reach_for_panels(panel_ids, weeks=args.weeks, repeat_rate=args.repeat_rate)

    print(f"Requested {len(panel_ids)} panel(s), {args.weeks} week(s):")
    for key, m in result["by_mall"].items():
        line = f"  {key}: {len(m['panels'])} panel(s) -> week-1 reach {m['week1_reach']:,}"
        if args.weeks > 1:
            line += f", {args.weeks}-week reach {m['cumulative_reach']:,.0f}"
        print(line)
    if result["unresolved_panel_ids"]:
        print(f"  UNRESOLVED (not found in any mall's simulation output): {result['unresolved_panel_ids']}")

    print(f"\nTotal week-1 reach (exact, simulation ground truth): {result['total_week1_reach']:,}")
    if args.weeks > 1:
        print(
            f"Total {args.weeks}-week reach (PLACEHOLDER model, "
            f"repeat_rate={args.repeat_rate}): {result['total_cumulative_reach']:,.0f}"
        )
        print(
            "\nThe week-1 figure above is the simulation's own ground truth for "
            "this exact panel set. The multi-week figure is NOT -- it is that "
            "number run through a saturating curve driven by an undata-backed "
            "placeholder repeat rate (see module docstring). Replace "
            "WEEKLY_REPEAT_RATE, or pass --repeat-rate, once a real figure exists."
        )
    else:
        print(
            "\nThis is the simulation's exact 1-week ground truth for this panel "
            "set. Pass --weeks N for a multi-week projection (placeholder model)."
        )


if __name__ == "__main__":
    main()
