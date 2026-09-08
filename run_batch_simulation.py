#!/usr/bin/env python3
"""Headless weekly simulation — mirrors app.js logic for batch result export."""

from __future__ import annotations

import argparse
import csv
import gc
import heapq
import json
import math
import os
import random
import resource
import signal
import subprocess
import sys
import time
from multiprocessing import get_context
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "results"

LAT_DEG_TO_M = 111000.0
LON_DEG_TO_M = 88800.0

WEEKLY_VISITS = 200_000
WEEKLY_UNIQUES = 123_000
DAILY_WEIGHTS = [0.11, 0.12, 0.13, 0.145, 0.165, 0.195, 0.135]
MIN_SHOP_VISITS = 2
MAX_SHOP_VISITS = 4
DECAY_EXPONENT = 1.3
MAX_VIEW_DIST = 15.0
CONE_ANGLE = 60.0
STEP_METERS = 2.0
GRID_CELL_M = 15.0
USE_NUMBA = True

# Segment-choice routing defaults (match app.js)
ROUTING_MODE = "segment_logit"
ROUTE_BETA_PROGRESS = 0.08
ROUTE_RANDOMNESS = 1.0
ROUTE_ZONE_BOOST = 0.35
ROUTE_BETA_VERTICAL = 0.5
MAX_ROUTE_STEPS = 500
ESCALATOR_ZONE_RADIUS_M = 15.0
ESCALATOR_ZONE_NAME = "escalator_lv2_4"

# Read-only sim state populated in main, inherited by fork workers (ponytail: fork COW on macOS/Linux).
_SIM: dict = {}

try:
    import numpy as np
    from sim_fast import apply_fast_metrics, build_fast_context, init_rng_state, walk_route_fast, warmup

    NUMBA_AVAILABLE = True
except ImportError:
    NUMBA_AVAILABLE = False

CATEGORY_WEIGHTS = {
    "farmers": 0.60,
    "davidjones": 0.45,
    "hm": 0.35,
    "woolworths": 0.70,
    "jbhifi": 0.30,
    "foodcourt": 0.75,
    "noelleeming": 0.30,
    "archiebrothers": 0.35,
    "rebelsport": 0.35,
    "specialty": 0.12,
}


def distance_m(x1, y1, x2, y2) -> float:
    dx = (x1 - x2) * LON_DEG_TO_M
    dy = (y1 - y2) * LAT_DEG_TO_M
    return math.hypot(dx, dy)


def get_store_category(name: str) -> str:
    if not name:
        return "specialty"
    n = name.lower()
    checks = [
        ("farmers", ("farmers",)),
        ("davidjones", ("davidjones", "david jones")),
        ("hm", ("handm", "h&m", "hm")),
        ("woolworths", ("woolworths", "countdown")),
        ("jbhifi", ("jbhifi", "jb hifi", "jb hi-fi", "jb_hifi")),
        ("foodcourt", ("food_court", "foodcourt")),
        ("noelleeming", ("noelleeming", "noel leeming", "noel_leeming")),
        ("archiebrothers", ("archiebrothers", "archie brothers", "archie_brothers", "archiebros")),
        ("rebelsport", ("rebelsport", "rebel sport", "rebel_sport")),
    ]
    for cat, keys in checks:
        if any(k in n for k in keys):
            return cat
    if n.startswith("rs_"):
        return "rebelsport"
    return "specialty"


def _popcount(b: int) -> int:
    return bin(b).count("1")


class Bitset:
    __slots__ = ("size", "data")

    def __init__(self, size: int):
        self.size = size
        self.data = bytearray((size + 7) // 8)

    def add(self, idx: int) -> None:
        self.data[idx >> 3] |= 1 << (idx & 7)

    def count(self) -> int:
        return sum(_popcount(v) for v in self.data)

    def intersect_count(self, other: Bitset) -> int:
        return sum(_popcount(a & b) for a, b in zip(self.data, other.data))

    def union_with(self, other: Bitset) -> None:
        for i in range(len(self.data)):
            self.data[i] |= other.data[i]


class Panel:
    __slots__ = ("id", "lon", "lat", "floor", "orientation", "reach", "contacts")

    def __init__(self, row: dict, reach_size: int):
        self.id = row["panel_id"]
        self.lon = float(row["longitude"])
        self.lat = float(row["latitude"])
        self.floor = row["floor"].strip()
        self.orientation = float(row["orientation"])
        self.reach = Bitset(reach_size)
        self.contacts = 0


def load_panels() -> list[Panel]:
    path = ROOT / "panel_locations_with_floor.csv"
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    return [Panel(r, WEEKLY_UNIQUES) for r in rows]


def load_graph():
    with (ROOT / "newmarket_graph.json").open() as f:
        data = json.load(f)
    nodes = {n["id"]: n for n in data["nodes"]}
    adj: dict[str, list[tuple[str, float]]] = {nid: [] for nid in nodes}
    for e in data["edges"]:
        s, t, w = e["source"], e["target"], e["weight"]
        if s in adj and t in adj:
            adj[s].append((t, w))
            adj[t].append((s, w))
    return nodes, adj


def dijkstra_all(start_id: str, nodes: dict, adj: dict):
    dist = {nid: math.inf for nid in nodes}
    prev = {nid: None for nid in nodes}
    dist[start_id] = 0.0
    heap = [(0.0, start_id)]
    while heap:
        d, u = heapq.heappop(heap)
        if d > dist[u]:
            continue
        for v, w in adj.get(u, []):
            alt = d + w
            if alt < dist[v]:
                dist[v] = alt
                prev[v] = u
                heapq.heappush(heap, (alt, v))
    paths = {}
    for target in nodes:
        path = []
        cur = target
        if prev[cur] is not None or cur == start_id:
            while cur is not None:
                path.append(cur)
                cur = prev[cur]
            path.reverse()
        paths[target] = path
    return dist, paths


def precompute_paths(nodes: dict, adj: dict, node_ids: list[str]):
    decision = [n for n in nodes.values() if n["type"] in ("mall_entrance", "shop_entry")]
    dist_matrix: dict[str, dict[str, float]] = {}
    path_cache: dict[str, dict[str, list[str]]] = {}
    dist_to_target: dict[str, list[float]] = {}
    for i, node in enumerate(decision, 1):
        d, p = dijkstra_all(node["id"], nodes, adj)
        dist_matrix[node["id"]] = d
        path_cache[node["id"]] = p
        dist_to_target[node["id"]] = [d.get(nid, math.inf) for nid in node_ids]
        if i % 10 == 0 or i == len(decision):
            print(f"  paths {i}/{len(decision)}", flush=True)
    adj_ids = {nid: [v for v, _ in pairs] for nid, pairs in adj.items()}
    return dist_matrix, path_cache, dist_to_target, adj_ids, decision


def build_escalator_zone_flags(nodes: dict) -> set[str]:
    anchor = next((n for n in nodes.values() if n.get("name") == ESCALATOR_ZONE_NAME), None)
    if not anchor:
        return set()
    zone: set[str] = set()
    for node in nodes.values():
        if node["type"] != "corridor" or str(node["level"]) != "2":
            continue
        if distance_m(node["x"], node["y"], anchor["x"], anchor["y"]) <= ESCALATOR_ZONE_RADIUS_M:
            zone.add(node["id"])
    return zone


def build_category_counts(shop_nodes: list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for n in shop_nodes:
        cat = get_store_category(n.get("name", ""))
        counts[cat] = counts.get(cat, 0) + 1
    return counts


def build_panel_grid(panels: list[Panel]) -> dict[str, dict[tuple[int, int], list[Panel]]]:
    grid: dict[str, dict[tuple[int, int], list[Panel]]] = {"1": {}, "2": {}, "3": {}}
    for p in panels:
        cx = int(p.lon * LON_DEG_TO_M / GRID_CELL_M)
        cy = int(p.lat * LAT_DEG_TO_M / GRID_CELL_M)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                key = (cx + dx, cy + dy)
                grid[p.floor].setdefault(key, []).append(p)
    return grid


def panels_near(grid, floor: str, x: float, y: float) -> list[Panel]:
    cx = int(x * LON_DEG_TO_M / GRID_CELL_M)
    cy = int(y * LAT_DEG_TO_M / GRID_CELL_M)
    return grid.get(floor, {}).get((cx, cy), [])


def daily_trip_counts() -> list[int]:
    counts = [round(WEEKLY_VISITS * w) for w in DAILY_WEIGHTS]
    counts[5] += WEEKLY_VISITS - sum(counts)
    return counts


def in_panel_view(x, y, floor, n1, n2, panel: Panel) -> bool:
    if panel.floor != str(floor):
        return False
    dx = (x - panel.lon) * LON_DEG_TO_M
    dy = (y - panel.lat) * LAT_DEG_TO_M
    dist = math.hypot(dx, dy)
    if dist <= 1e-6 or dist > MAX_VIEW_DIST:
        return False
    theta = math.radians(panel.orientation)
    nx, ny = math.sin(theta), math.cos(theta)
    p2a_x, p2a_y = dx / dist, dy / dist
    cos_cone = math.cos(math.radians(CONE_ANGLE))
    if p2a_x * nx + p2a_y * ny < cos_cone:
        return False
    hx = (n2["x"] - n1["x"]) * LON_DEG_TO_M
    hy = (n2["y"] - n1["y"]) * LAT_DEG_TO_M
    hd = math.hypot(hx, hy)
    if hd > 1e-4:
        hx, hy = hx / hd, hy / hd
        if hx * (-p2a_x) + hy * (-p2a_y) < cos_cone:
            return False
    return True


def check_panels(x, y, floor, n1, n2, person_idx, panel_grid, viewing: set[str]):
    for panel in panels_near(panel_grid, str(floor), x, y):
        pid = panel.id
        seen = pid in viewing
        hit = in_panel_view(x, y, floor, n1, n2, panel)
        if hit and not seen:
            panel.contacts += 1
            panel.reach.add(person_idx)
            viewing.add(pid)
        elif not hit and seen:
            viewing.discard(pid)


def walk_single_edge(n1, n2, person_idx, nodes, panel_grid, viewing: set[str]):
    seg = distance_m(n1["x"], n1["y"], n2["x"], n2["y"])
    steps = max(1, int(seg / STEP_METERS))
    for s in range(steps + 1):
        t = s / steps
        x = n1["x"] + t * (n2["x"] - n1["x"])
        y = n1["y"] + t * (n2["y"] - n1["y"])
        check_panels(x, y, n1["level"], n1, n2, person_idx, panel_grid, viewing)


def walk_path(path, person_idx, nodes, panel_grid, viewing: set[str]):
    for i in range(len(path) - 1):
        walk_single_edge(nodes[path[i]], nodes[path[i + 1]], person_idx, nodes, panel_grid, viewing)


def _gumbel(rng: random.Random) -> float:
    return -math.log(-math.log(rng.random()))


def choose_next_node(
    current_id: str,
    prev_id: str | None,
    target_id: str,
    node_index: dict[str, int],
    adj_ids: dict[str, list[str]],
    dist_row: list[float],
    escalator_zone: set[str],
    nodes: dict,
    rng: random.Random,
) -> str | None:
    cur_i = node_index[current_id]
    candidates = [v for v in adj_ids.get(current_id, []) if v != prev_id and v in node_index]
    if not candidates:
        return prev_id

    target_node = nodes[target_id]
    total = 0.0
    weighted: list[tuple[str, float]] = []
    cur_dist = dist_row[cur_i]
    for v in candidates:
        vi = node_index[v]
        if dist_row[vi] == math.inf:
            continue
        progress = cur_dist - dist_row[vi]
        score = ROUTE_BETA_PROGRESS * progress
        if v in escalator_zone:
            score += ROUTE_ZONE_BOOST
        vn = nodes[v]
        if str(vn["level"]) != str(target_node["level"]) and vn["type"] in ("escalator", "elevator"):
            score += ROUTE_BETA_VERTICAL
        w = math.exp(score + ROUTE_RANDOMNESS * _gumbel(rng))
        weighted.append((v, w))
        total += w

    if not weighted:
        return prev_id

    r = rng.random() * total
    for v, w in weighted:
        r -= w
        if r <= 0:
            return v
    return weighted[-1][0]


def walk_segment_choice(
    start_id: str,
    target_id: str,
    person_idx,
    nodes,
    node_index,
    adj_ids,
    dist_to_target,
    escalator_zone,
    panel_grid,
    viewing: set[str],
    rng: random.Random,
):
    if start_id == target_id:
        return
    dist_row = dist_to_target.get(target_id)
    if not dist_row:
        return
    current = start_id
    prev = None
    for _ in range(MAX_ROUTE_STEPS):
        if current == target_id:
            break
        nxt = choose_next_node(
            current, prev, target_id, node_index, adj_ids, dist_row, escalator_zone, nodes, rng
        )
        if not nxt or nxt == current:
            break
        walk_single_edge(nodes[current], nodes[nxt], person_idx, nodes, panel_grid, viewing)
        prev = current
        current = nxt


def walk_route(
    start_id: str,
    target_id: str,
    person_idx,
    nodes,
    node_index,
    adj_ids,
    path_cache,
    dist_to_target,
    escalator_zone,
    panel_grid,
    viewing: set[str],
    rng: random.Random,
):
    if ROUTING_MODE == "segment_logit":
        walk_segment_choice(
            start_id,
            target_id,
            person_idx,
            nodes,
            node_index,
            adj_ids,
            dist_to_target,
            escalator_zone,
            panel_grid,
            viewing,
            rng,
        )
        return
    path = path_cache.get(start_id, {}).get(target_id, [])
    if len(path) > 1:
        walk_path(path, person_idx, nodes, panel_grid, viewing)


def select_shop(current_id, last_id, shop_nodes, dist_matrix, cat_counts, rng):
    total = 0.0
    cands = []
    for node in shop_nodes:
        if node["id"] == last_id:
            continue
        cat = get_store_category(node.get("name", ""))
        base = max(0.001, CATEGORY_WEIGHTS.get(cat, 0.3) / cat_counts.get(cat, 1))
        dist = dist_matrix[current_id].get(node["id"], math.inf)
        if dist == math.inf:
            continue
        wt = base / (max(2.0, dist) ** DECAY_EXPONENT)
        cands.append((node, wt))
        total += wt
    if not cands:
        return rng.choice(shop_nodes)
    r = rng.random() * total
    for node, wt in cands:
        r -= wt
        if r <= 0:
            return node
    return cands[-1][0]


def simulate_trip(
    trip_index: int,
    person_idx: int,
    ctx: dict,
    panels: list[Panel],
    fast_contacts=None,
    fast_reach=None,
):
    rng = random.Random(42 + trip_index)
    fast = ctx.get("fast") if USE_NUMBA and NUMBA_AVAILABLE else None
    viewing: set[str] = set()
    viewing_mask = np.zeros(1, dtype=np.uint64) if fast is not None else None
    rng_state = init_rng_state(trip_index) if fast is not None else None
    if viewing_mask is not None:
        viewing_mask[0] = 0

    start = rng.choice(ctx["spawn_nodes"])
    current = start["id"]
    last_shop = None
    visits = rng.randint(MIN_SHOP_VISITS, MAX_SHOP_VISITS)
    for _ in range(visits):
        target = select_shop(
            current, last_shop, ctx["shop_nodes"], ctx["dist_matrix"], ctx["cat_counts"], rng
        )
        if current != target["id"]:
            if fast is not None:
                walk_route_fast(
                    fast,
                    current,
                    target["id"],
                    person_idx,
                    fast_contacts,
                    fast_reach,
                    viewing_mask,
                    rng_state,
                    ROUTING_MODE,
                    ROUTE_BETA_PROGRESS,
                    ROUTE_RANDOMNESS,
                    ROUTE_ZONE_BOOST,
                    ROUTE_BETA_VERTICAL,
                )
            else:
                walk_route(
                    current,
                    target["id"],
                    person_idx,
                    ctx["nodes"],
                    ctx["node_index"],
                    ctx["adj_ids"],
                    ctx["path_cache"],
                    ctx["dist_to_target"],
                    ctx["escalator_zone"],
                    ctx["panel_grid"],
                    viewing,
                    rng,
                )
        current = target["id"]
        last_shop = target["id"]
    exit_node = rng.choice(ctx["spawn_nodes"])
    if current != exit_node["id"]:
        if fast is not None:
            walk_route_fast(
                fast,
                current,
                exit_node["id"],
                person_idx,
                fast_contacts,
                fast_reach,
                viewing_mask,
                rng_state,
                ROUTING_MODE,
                ROUTE_BETA_PROGRESS,
                ROUTE_RANDOMNESS,
                ROUTE_ZONE_BOOST,
                ROUTE_BETA_VERTICAL,
            )
        else:
            walk_route(
                current,
                exit_node["id"],
                person_idx,
                ctx["nodes"],
                ctx["node_index"],
                ctx["adj_ids"],
                ctx["path_cache"],
                ctx["dist_to_target"],
                ctx["escalator_zone"],
                ctx["panel_grid"],
                viewing,
                rng,
            )


def build_sim_context(nodes, adj, spawn_nodes, shop_nodes, cat_counts, panel_grid, escalator_zone):
    node_ids = list(nodes.keys())
    node_index = {nid: i for i, nid in enumerate(node_ids)}
    dist_matrix, path_cache, dist_to_target, adj_ids, _ = precompute_paths(nodes, adj, node_ids)
    return {
        "nodes": nodes,
        "node_ids": node_ids,
        "node_index": node_index,
        "adj_ids": adj_ids,
        "spawn_nodes": spawn_nodes,
        "shop_nodes": shop_nodes,
        "cat_counts": cat_counts,
        "panel_grid": panel_grid,
        "escalator_zone": escalator_zone,
        "dist_matrix": dist_matrix,
        "path_cache": path_cache,
        "dist_to_target": dist_to_target,
    }


def build_trip_plan(total_trips: int, seed: int = 42) -> list[tuple[int, int]]:
    """Assign trips so every pool member gets >=1 visit when total_trips >= pool size."""
    rng = random.Random(seed)
    if total_trips <= 0:
        return []
    pool = WEEKLY_UNIQUES
    if total_trips >= pool:
        people = list(range(pool))
        rng.shuffle(people)
        assignments = people[:pool]
        assignments.extend(rng.randrange(pool) for _ in range(total_trips - pool))
        rng.shuffle(assignments)
    else:
        people = list(range(pool))
        rng.shuffle(people)
        assignments = people[:total_trips]
    return [(i, assignments[i]) for i in range(total_trips)]


def rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss = usage.ru_maxrss
    if sys.platform == "darwin":
        return rss / (1024 * 1024)
    return rss / 1024


def stop_local_server(port: int) -> list[int]:
    """Stop the static UI server (start_server.py) if it is listening on port."""
    try:
        out = subprocess.check_output(["lsof", "-ti", f":{port}"], stderr=subprocess.DEVNULL, text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    if not out:
        return []
    killed: list[int] = []
    for token in out.split():
        try:
            pid = int(token)
        except ValueError:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            killed.append(pid)
        except ProcessLookupError:
            pass
    if killed:
        time.sleep(0.3)
        gc.collect()
    return killed


def trim_sim_context(ctx: dict, use_numba: bool, routing_mode: str) -> list[str]:
    """Drop precompute blobs that are redundant once Numba arrays exist."""
    dropped: list[str] = []
    if use_numba or routing_mode == "segment_logit":
        if ctx.pop("path_cache", None) is not None:
            dropped.append("path_cache (~50-60 MB)")
    if use_numba:
        if ctx.pop("dist_to_target", None) is not None:
            dropped.append("dist_to_target")
        if ctx.pop("panel_grid", None) is not None:
            dropped.append("panel_grid")
    if dropped:
        gc.collect()
    return dropped


def estimate_peak_mb(workers: int, use_numba: bool) -> int:
    # ponytail: coarse heuristic; fork shares read-only ctx, workers add panel + chunk buffers
    parent_mb = 180 if use_numba else 250
    per_worker_mb = 35 if use_numba else 70
    return parent_mb + max(0, workers - 1) * per_worker_mb


def prepare_for_simulation(kill_server: bool, server_port: int, workers: int, use_numba: bool) -> None:
    gc.collect()
    if kill_server:
        killed = stop_local_server(server_port)
        if killed:
            print(f"  Stopped server on port {server_port}: PIDs {', '.join(map(str, killed))}")
        else:
            print(f"  No process listening on port {server_port}")
    rss = rss_mb()
    peak = estimate_peak_mb(workers, use_numba)
    print(f"  Process RSS now: {rss:.0f} MB")
    print(f"  Rough peak estimate ({workers} worker(s)): ~{peak} MB")
    if peak > 2048 and workers > 4:
        print(f"  Tip: if memory is tight, try --workers 4")
    gc.collect()


def _init_worker(ctx: dict) -> None:
    _SIM["ctx"] = ctx


def run_trip_chunk(chunk: list[tuple[int, int]]) -> list[tuple[str, bytes, int]]:
    base_ctx = _SIM["ctx"]
    panels = load_panels()
    fast = base_ctx.get("fast")
    if fast is not None:
        ctx = base_ctx
    else:
        ctx = {**base_ctx, "panel_grid": build_panel_grid(panels)}
    if fast is not None:
        fast_contacts = np.zeros(len(panels), dtype=np.int64)
        fast_reach = np.zeros((len(panels), fast.reach_bytes), dtype=np.uint8)
        for trip_index, person_idx in chunk:
            simulate_trip(trip_index, person_idx, ctx, panels, fast_contacts, fast_reach)
        apply_fast_metrics(panels, fast_contacts, fast_reach)
    else:
        for trip_index, person_idx in chunk:
            simulate_trip(trip_index, person_idx, ctx, panels)
    return [(p.id, bytes(p.reach.data), p.contacts) for p in panels]


def merge_chunk_results(panels: list[Panel], chunks: list[list[tuple[str, bytes, int]]]) -> None:
    by_id = {p.id: p for p in panels}
    for chunk in chunks:
        for pid, reach_data, contacts in chunk:
            panel = by_id[pid]
            panel.contacts += contacts
            other = Bitset(WEEKLY_UNIQUES)
            other.data = bytearray(reach_data)
            panel.reach.union_with(other)


def run_sequential(trip_plan: list[tuple[int, int]], panels: list[Panel], ctx: dict) -> None:
    done = 0
    total = len(trip_plan)
    t0 = time.time()
    fast = ctx.get("fast")
    if fast is not None:
        fast_contacts = np.zeros(len(panels), dtype=np.int64)
        fast_reach = np.zeros((len(panels), fast.reach_bytes), dtype=np.uint8)
        for trip_index, person_idx in trip_plan:
            simulate_trip(trip_index, person_idx, ctx, panels, fast_contacts, fast_reach)
            done += 1
            if done % 10000 == 0:
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed else 0
                eta = (total - done) / rate if rate else 0
                print(f"  {done:,}/{total:,} trips ({rate:.0f}/s, ETA {eta/60:.1f}m)", flush=True)
        apply_fast_metrics(panels, fast_contacts, fast_reach)
        return

    for trip_index, person_idx in trip_plan:
        simulate_trip(trip_index, person_idx, ctx, panels)
        done += 1
        if done % 10000 == 0:
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed else 0
            eta = (total - done) / rate if rate else 0
            print(f"  {done:,}/{total:,} trips ({rate:.0f}/s, ETA {eta/60:.1f}m)", flush=True)


def run_parallel(trip_plan: list[tuple[int, int]], panels: list[Panel], workers: int, ctx: dict) -> None:
    workers = max(1, min(workers, len(trip_plan)))
    chunk_size = max(1, (len(trip_plan) + workers - 1) // workers)
    chunks = [trip_plan[i : i + chunk_size] for i in range(0, len(trip_plan), chunk_size)]
    mp_ctx = get_context("fork") if sys.platform != "win32" else get_context("spawn")

    print(f"  Parallel workers: {len(chunks)} (requested {workers})", flush=True)
    t0 = time.time()
    with mp_ctx.Pool(processes=len(chunks), initializer=_init_worker, initargs=(ctx,)) as pool:
        results = pool.map(run_trip_chunk, chunks)
    merge_chunk_results(panels, results)
    elapsed = time.time() - t0
    print(f"  Parallel merge done in {elapsed:.1f}s", flush=True)


def write_panel_metrics(panels: list[Panel], path: Path):
    rows = sorted(panels, key=lambda p: p.reach.count(), reverse=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["rank", "panel_id", "floor", "unique_reach", "contacts", "exposure_efficiency_pct"])
        for i, p in enumerate(rows, 1):
            reach = p.reach.count()
            eff = 100.0 * reach / WEEKLY_UNIQUES
            w.writerow([i, p.id, p.floor, reach, p.contacts, f"{eff:.2f}"])


def write_pair_overlap(panels: list[Panel], path: Path):
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["panel_a", "panel_b", "unique_reach_a", "unique_reach_b", "shared_agents", "overlap_coefficient"])
        plist = sorted(panels, key=lambda p: p.id)
        for i, a in enumerate(plist):
            ra = a.reach.count()
            for b in plist[i + 1 :]:
                rb = b.reach.count()
                shared = a.reach.intersect_count(b.reach)
                denom = min(ra, rb)
                coef = shared / denom if denom else 0.0
                w.writerow([a.id, b.id, ra, rb, shared, f"{coef:.6f}"])


def parse_args():
    p = argparse.ArgumentParser(description="Run weekly mall panel simulation batch")
    p.add_argument("--routing", choices=("shortest", "segment_logit"), default=ROUTING_MODE)
    p.add_argument("--route-beta", type=float, default=ROUTE_BETA_PROGRESS)
    p.add_argument("--route-randomness", type=float, default=ROUTE_RANDOMNESS)
    p.add_argument("--route-zone-boost", type=float, default=ROUTE_ZONE_BOOST)
    p.add_argument("--route-vertical", type=float, default=ROUTE_BETA_VERTICAL)
    p.add_argument("--trips", type=int, default=0, help="Override trip count (0 = full week)")
    p.add_argument(
        "--workers",
        type=int,
        default=max(1, (os.cpu_count() or 4) - 1),
        help="CPU workers for trip parallelism (1 = sequential)",
    )
    p.add_argument(
        "--step-meters",
        type=float,
        default=STEP_METERS,
        help="Panel visibility sample spacing along walked edges (default 2m)",
    )
    p.add_argument(
        "--no-numba",
        action="store_true",
        help="Disable Numba JIT kernels (pure Python walk loop)",
    )
    p.add_argument(
        "--kill-server",
        action="store_true",
        help="Stop the local UI server (start_server.py on port 8000) before running",
    )
    p.add_argument(
        "--server-port",
        type=int,
        default=8000,
        help="Port for --kill-server (default: 8000)",
    )
    return p.parse_args()


def main():
    global ROUTING_MODE, ROUTE_BETA_PROGRESS, ROUTE_RANDOMNESS, ROUTE_ZONE_BOOST, ROUTE_BETA_VERTICAL
    global STEP_METERS, USE_NUMBA

    args = parse_args()
    ROUTING_MODE = args.routing
    ROUTE_BETA_PROGRESS = args.route_beta
    ROUTE_RANDOMNESS = args.route_randomness
    ROUTE_ZONE_BOOST = args.route_zone_boost
    ROUTE_BETA_VERTICAL = args.route_vertical
    STEP_METERS = max(0.5, args.step_meters)
    USE_NUMBA = not args.no_numba and NUMBA_AVAILABLE

    OUT_DIR.mkdir(exist_ok=True)

    workers = 1 if args.workers <= 1 else args.workers
    print("Preparing memory...")
    prepare_for_simulation(args.kill_server, args.server_port, workers, USE_NUMBA)

    print("Loading panels and graph...")
    panels = load_panels()
    nodes, adj = load_graph()
    spawn_nodes = [n for n in nodes.values() if n["type"] == "mall_entrance"]
    shop_nodes = [n for n in nodes.values() if n["type"] == "shop_entry"]
    cat_counts = build_category_counts(shop_nodes)
    panel_grid = build_panel_grid(panels)
    escalator_zone = build_escalator_zone_flags(nodes)
    print(f"  Routing mode: {ROUTING_MODE}")
    print(f"  Panel step: {STEP_METERS}m")
    print(f"  Numba kernels: {'on' if USE_NUMBA else 'off'}")
    print(f"  Escalator zone corridor nodes: {len(escalator_zone)}")

    print("Precomputing shortest paths...")
    t0 = time.time()
    ctx = build_sim_context(nodes, adj, spawn_nodes, shop_nodes, cat_counts, panel_grid, escalator_zone)
    if USE_NUMBA:
        print("  Building Numba walk context...", flush=True)
        ctx["fast"] = build_fast_context(ctx, panels, STEP_METERS, len(panels[0].reach.data))
        print("  Warming up Numba JIT...", flush=True)
        warmup()
    dropped = trim_sim_context(ctx, USE_NUMBA, ROUTING_MODE)
    if dropped:
        print(f"  Trimmed unused context: {', '.join(dropped)}")
        print(f"  Process RSS after trim: {rss_mb():.0f} MB")
    _SIM["ctx"] = ctx
    print(f"  done in {time.time() - t0:.1f}s")

    trips = daily_trip_counts()
    total_trips = sum(trips)
    if args.trips > 0:
        total_trips = args.trips
    trip_plan = build_trip_plan(total_trips)
    print(f"Running {total_trips:,} weekly trips ({WEEKLY_UNIQUES:,} unique pool)...")
    print(f"  Workers: {workers} ({'sequential' if workers <= 1 else 'parallel'})")
    t1 = time.time()
    if workers <= 1:
        run_sequential(trip_plan, panels, ctx)
    else:
        run_parallel(trip_plan, panels, workers, ctx)

    elapsed = time.time() - t1
    print(f"Simulation finished in {elapsed:.1f}s ({total_trips/elapsed:.0f} trips/s)")

    panel_path = OUT_DIR / "panel_metrics.csv"
    pair_path = OUT_DIR / "panel_pair_overlap.csv"
    write_panel_metrics(panels, panel_path)
    write_pair_overlap(panels, pair_path)

    total_contacts = sum(p.contacts for p in panels)
    union_reach = Bitset(WEEKLY_UNIQUES)
    for p in panels:
        union_reach.union_with(p.reach)
    print(f"\nSummary:")
    print(f"  Weekly trips simulated: {total_trips:,}")
    print(f"  Weekly unique pool:     {WEEKLY_UNIQUES:,}")
    print(f"  Mall-wide unique reach: {union_reach.count():,}")
    print(f"  Total contacts:         {total_contacts:,}")
    print(f"  Panel metrics:          {panel_path}")
    print(f"  Pair overlap matrix:    {pair_path}")
    top = sorted(panels, key=lambda p: p.reach.count(), reverse=True)[:5]
    print("\nTop 5 panels by unique reach:")
    for p in top:
        print(f"  Panel {p.id} (L{p.floor}): reach={p.reach.count():,}, contacts={p.contacts:,}")

    watch = ["27052", "27053", "27054"]
    print("\nEscalator-branch panels:")
    by_id = {p.id: p for p in panels}
    for pid in watch:
        p = by_id.get(pid)
        if p:
            print(f"  Panel {pid}: reach={p.reach.count():,}, contacts={p.contacts:,}")


if __name__ == "__main__":
    plan = build_trip_plan(WEEKLY_VISITS)
    assert len(plan) == WEEKLY_VISITS
    assert len({p for _, p in plan}) == WEEKLY_UNIQUES, "full pool coverage when trips >= uniques"
    main()
