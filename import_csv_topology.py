"""Build a mall navigation graph from a node/edge CSV pair.

An alternative front end to generate_graph.py for centres whose topology was
authored as an explicit node/edge list -- seeded from an asset plan and meshed
with waypoints -- rather than drawn as corridor polygons. Albany came out of the
earlier RetailSimulation work in that form, which is both richer and cleaner
than its raw OSM export: entries, weighted anchors and paired escalators are all
named, and the corridor mesh is already connected.

Input columns:

    nodes  node_id, type, lat, lon, floor, name, category, weight,
           dwell_mean_min, dwell_std_min
    edges  edge_id, from_node, to_node, floor, type, length_m, width_m,
           speed_mult, time_penalty_s, weight

`type` maps onto the vocabulary the simulation expects:

    waypoint  -> corridor       walkable mesh
    entry     -> mall_entrance  where agents enter and leave
    anchor    -> shop_entry     trip destinations
    escalator -> escalator      vertical connectors
    elevator  -> elevator

Edge weights are metres, matching the distances generate_graph.py computes, so
downstream routing is unchanged.
"""

from __future__ import annotations

import argparse
import csv
import json

import malls

NODE_TYPE_MAP = {
    "waypoint": "corridor",
    "entry": "mall_entrance",
    "anchor": "shop_entry",
    "escalator": "escalator",
    "elevator": "elevator",
}


def load_nodes(path):
    nodes = []
    skipped = {}
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            raw_type = (row.get("type") or "").strip()
            mapped = NODE_TYPE_MAP.get(raw_type)
            if mapped is None:
                skipped[raw_type] = skipped.get(raw_type, 0) + 1
                continue
            node = {
                "id": row["node_id"],
                "x": float(row["lon"]),
                "y": float(row["lat"]),
                "level": str(row["floor"]).strip(),
                "type": mapped,
            }
            name = (row.get("name") or "").strip()
            if name:
                node["name"] = name
            # Carried through for weighted destination choice and dwell models.
            for extra, cast in (("category", str), ("weight", float),
                                ("dwell_mean_min", float), ("dwell_std_min", float)):
                value = (row.get(extra) or "").strip()
                if value:
                    try:
                        node[extra] = cast(value)
                    except ValueError:
                        pass
            nodes.append(node)
    return nodes, skipped


def load_edges(path, node_ids):
    edges = []
    dangling = 0
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            source, target = row["from_node"], row["to_node"]
            if source not in node_ids or target not in node_ids:
                dangling += 1
                continue
            # length_m is the physical distance; `weight` may carry routing
            # penalties that the simulation applies itself, so prefer length.
            raw = row.get("length_m") or row.get("weight") or 0.0
            edges.append({
                "source": source,
                "target": target,
                "weight": float(raw),
                "level": str(row.get("floor", "")).strip(),
                "type": (row.get("type") or "").strip(),
            })
    return edges, dangling


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    malls.add_mall_argument(parser)
    args = parser.parse_args()
    mall = malls.resolve(args.mall)

    if not mall.csv_nodes or not mall.csv_edges:
        raise SystemExit(
            f"{mall.name} has no node/edge CSV topology configured -- it is built "
            f"from polygons instead. Run generate_graph.py --mall {mall.key}."
        )

    nodes_path = mall.path("csv_nodes")
    edges_path = mall.path("csv_edges")
    print(f"Loading {nodes_path.name} and {edges_path.name} for {mall.name}...")

    nodes, skipped = load_nodes(nodes_path)
    if skipped:
        print(f"  Ignored unmapped node types: {skipped}")
    edges, dangling = load_edges(edges_path, {n["id"] for n in nodes})
    if dangling:
        print(f"  Dropped {dangling} edges referencing unknown nodes")

    by_type = {}
    for node in nodes:
        by_type[node["type"]] = by_type.get(node["type"], 0) + 1
    print("  Nodes by type:", by_type)

    connected = {e["source"] for e in edges} | {e["target"] for e in edges}
    isolated = [n for n in nodes if n["id"] not in connected]
    if isolated:
        print(f"  Dropping {len(isolated)} isolated nodes")
        nodes = [n for n in nodes if n["id"] in connected]

    output_path = mall.path("graph")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        json.dump({"nodes": nodes, "edges": edges}, f, indent=2)

    print(f"\nSaved graph to {output_path.name}")
    print(f"Graph stats: {len(nodes)} nodes, {len(edges)} edges")


if __name__ == "__main__":
    main()
