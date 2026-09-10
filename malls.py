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
import json
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

    # Explicit node/edge list, the input to import_csv_topology.py. Set instead
    # of `topology` for a centre whose layout was authored as a graph rather
    # than drawn as corridor polygons.
    csv_nodes: str | None = None
    csv_edges: str | None = None

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

    # Node name marking the corridor cluster that gets ROUTE_ZONE_BOOST under
    # segment-logit routing. None disables the boost for this mall.
    escalator_zone_name: str | None = None
    escalator_zone_level: str = "2"

    # Observed pairwise panel similarity from MAID ping data, if available.
    # Not a simulation input -- ground truth to validate the output against.
    observed_similarity: str | None = None

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
        escalator_zone_name="escalator_lv2_4",
        escalator_zone_level="2",
    ),
    "albany": Mall(
        key="albany",
        name="Westfield Albany",
        site_id=17055,
        # Built from the explicit node/edge topology the earlier
        # RetailSimulation work produced (import_csv_topology.py), not from the
        # OSM export. The export is kept for reference and mapping, but it has
        # no shop entry points and no escalators tagged `conveying`, so a graph
        # built from it has nowhere to walk to and no way between floors.
        csv_nodes="data/albany/albany_nodes.csv",
        csv_edges="data/albany/albany_edges.csv",
        source_topology=None,
        topology="Westfield_Albany_topology.geojson",
        graph="albany_graph.json",
        panels="albany_panel_locations_with_floor.csv",
        results_dir="results/albany",
        # 111320 * cos(36.7289 deg) -- Albany sits ~16km north of Newmarket.
        lon_deg_to_m=89241.0,
        # The node/edge topology is already 1-based and single-valued. This map
        # only matters if the OSM export is ever used instead.
        level_map={"0": "1", "1": "2", "0;1": "1", "1;2": "2"},
        # DERIVED, not agreed. data/albany/albany_demand.json puts Albany at
        # 8.4M annual visits against Newmarket's 12.7M. Scaling Newmarket's
        # 200k/123k by 8.4/12.7 gives 132k weekly visits and 81k uniques.
        # Override per run with --weekly-visits / --weekly-uniques.
        weekly_visits=132_000,
        weekly_uniques=81_000,
        watch_panels=(),
        # No equivalent of Newmarket's boosted escalator corridor identified.
        escalator_zone_name=None,
        observed_similarity="data/albany/albany_panel_similarity_matrix_a.csv",
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


def browser_config() -> dict:
    """The subset of the registry the browser tools need.

    Written to malls.json so panel_editor.js and app.js resolve a mall from the
    same source as the Python pipeline instead of hardcoding one centre's
    filenames. Floor lists are deliberately absent: the pages derive them from
    the backdrop and panel data they load, so a mall never has to declare its
    floors in two places.
    """
    out = {}
    for key, mall in MALLS.items():
        # A polygon topology draws as a floorplan; a node/edge graph draws as a
        # corridor mesh. The editor renders whichever this mall actually has.
        if mall.csv_nodes and mall.csv_edges:
            backdrop = {"type": "graph", "path": mall.graph}
        else:
            backdrop = {"type": "geojson", "path": mall.topology}
        out[key] = {
            "key": key,
            "name": mall.name,
            "siteId": mall.site_id,
            "panels": mall.panels,
            "backdrop": backdrop,
        }
    return {"default": DEFAULT_MALL, "malls": out}


def add_mall_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mall",
        choices=sorted(MALLS),
        default=DEFAULT_MALL,
        help=f"which centre to run (default: {DEFAULT_MALL})",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Write malls.json for the browser tools to read"
    )
    parser.add_argument(
        "--out", default="malls.json", help="output path (default: malls.json)"
    )
    args = parser.parse_args()
    path = ROOT / args.out
    with path.open("w") as f:
        json.dump(browser_config(), f, indent=2)
        f.write("\n")
    print(f"Wrote {path.name} ({', '.join(sorted(MALLS))})")


if __name__ == "__main__":
    main()
