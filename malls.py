"""Per-mall configuration for the topology -> graph -> simulation pipeline.

Every script in the pipeline takes a `--mall` key that resolves to one of the
entries below, so the same code runs for any centre once its inputs exist.

Pipeline stages and the fields each one reads:

    convert_topology.py     source_topology -> topology   (curated zone schema
                            in EPSG:3857 translated into OSM vocabulary in
                            EPSG:4326; skipped entirely when a mall's topology
                            is already a native OSM/4326 export)
    generate_graph.py       topology -> graph             (uses level_map,
                            lon_deg_to_m)
    run_batch_simulation.py graph + panels -> results_dir (uses weekly_visits,
                            weekly_uniques, watch_panels)
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Mall:
    key: str
    name: str
    site_id: int

    # Stage inputs/outputs, all relative to ROOT.
    topology: str
    graph: str
    panels: str
    results_dir: str
    # Curated zone-schema source for convert_topology.py. None means the
    # topology file is already OSM-flavoured 4326 and needs no conversion.
    source_topology: str | None = None

    # Metres per degree of longitude at this centre's latitude. Newmarket keeps
    # the empirical value the original graph was built with so its output stays
    # reproducible; other malls use 111320 * cos(latitude).
    lon_deg_to_m: float = 88800.0

    # Raw OSM `level` values -> canonical level. Malls whose topology already
    # uses clean, 1-based, single-valued levels leave this empty; generate_graph
    # then falls back to generic normalisation (take the first token of a
    # multi-level string like "0;1", drop features with no level at all).
    level_map: dict[str, str] = field(default_factory=dict)

    # Footfall. None means the mall has no agreed figure yet and the value must
    # be supplied on the command line -- these drive every reach number, so they
    # are deliberately not guessed.
    weekly_visits: int | None = None
    weekly_uniques: int | None = None

    # Panels echoed individually in the run summary; purely a reporting aid.
    watch_panels: tuple[str, ...] = ()

    def path(self, attr: str) -> Path:
        value = getattr(self, attr)
        if value is None:
            raise ValueError(f"mall '{self.key}' has no {attr} configured")
        return ROOT / value


MALLS: dict[str, Mall] = {
    "newmarket": Mall(
        key="newmarket",
        name="Westfield Newmarket",
        site_id=17056,
        source_topology="Westfield_NewMarket_topology.geojson",
        topology="Westfield_NewMarket_topology_4326.geojson",
        graph="newmarket_graph.json",
        panels="panel_locations_with_floor.csv",
        results_dir="results",
        lon_deg_to_m=88800.0,
        weekly_visits=200_000,
        weekly_uniques=123_000,
        watch_panels=("27052", "27053", "27054"),
    ),
    "albany": Mall(
        key="albany",
        name="Westfield Albany",
        site_id=17055,
        # Already a native OSM export in EPSG:4326 -- no conversion stage.
        source_topology=None,
        topology="Westfield_Albany_topology.geojson",
        graph="albany_graph.json",
        panels="albany_panel_locations_with_floor.csv",
        results_dir="results/albany",
        # 111320 * cos(36.7289 deg) -- Albany sits ~16km north of Newmarket.
        lon_deg_to_m=89241.0,
        # The OSM export is 0-based and carries multi-level strings. This map is
        # a starting point, not a curation decision: revisit it alongside the
        # topology pass that adds shop entry points and escalators.
        level_map={"0": "1", "1": "2", "0;1": "1", "1;2": "2"},
        # No agreed Albany footfall yet -- pass --weekly-visits/--weekly-uniques.
        weekly_visits=None,
        weekly_uniques=None,
        watch_panels=(),
    ),
}

DEFAULT_MALL = "newmarket"


def resolve(key: str) -> Mall:
    try:
        return MALLS[key]
    except KeyError:
        raise SystemExit(
            f"unknown mall '{key}' -- choose one of: {', '.join(sorted(MALLS))}"
        ) from None


def add_mall_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mall",
        choices=sorted(MALLS),
        default=DEFAULT_MALL,
        help=f"which centre to run (default: {DEFAULT_MALL})",
    )
