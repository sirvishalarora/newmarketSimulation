"""Numba-accelerated corridor walk kernels for batch simulation."""

from __future__ import annotations

import math

import numpy as np
from numba import njit
from numba.core import types
from numba.typed import Dict

LAT_DEG_TO_M = 111000.0
LON_DEG_TO_M = 88800.0
MAX_VIEW_DIST = 15.0
CONE_ANGLE = 60.0
GRID_CELL_M = 15.0
MAX_ROUTE_STEPS = 500
COS_CONE = math.cos(math.radians(CONE_ANGLE))


@njit(cache=True)
def _rand(state: np.ndarray) -> float:
    # ponytail: simple LCG, fine for sim routing; swap for PCG if streams must match stdlib Random
    state[0] = (np.uint64(state[0]) * np.uint64(6364136223846793005) + np.uint64(1)) & np.uint64(0xFFFFFFFFFFFFFFFF)
    return (state[0] >> np.uint64(11)) * (1.0 / 9007199254740992.0)


@njit(cache=True)
def _gumbel(state: np.ndarray) -> float:
    u = _rand(state)
    if u <= 0.0:
        u = 1e-12
    if u >= 1.0:
        u = 1.0 - 1e-12
    return -math.log(-math.log(u))


@njit(cache=True)
def _reach_add(reach: np.ndarray, panel_i: int, person_idx: int) -> None:
    reach[panel_i, person_idx >> 3] |= np.uint8(1 << (person_idx & 7))


@njit(cache=True)
def _in_panel_view(
    x: float,
    y: float,
    floor: int,
    n1_x: float,
    n1_y: float,
    n2_x: float,
    n2_y: float,
    panel_lon: float,
    panel_lat: float,
    panel_floor: int,
    panel_orientation: float,
) -> bool:
    if panel_floor != floor:
        return False
    dx = (x - panel_lon) * LON_DEG_TO_M
    dy = (y - panel_lat) * LAT_DEG_TO_M
    dist = math.hypot(dx, dy)
    if dist <= 1e-6 or dist > MAX_VIEW_DIST:
        return False
    theta = math.radians(panel_orientation)
    nx = math.sin(theta)
    ny = math.cos(theta)
    p2a_x = dx / dist
    p2a_y = dy / dist
    if p2a_x * nx + p2a_y * ny < COS_CONE:
        return False
    hx = (n2_x - n1_x) * LON_DEG_TO_M
    hy = (n2_y - n1_y) * LAT_DEG_TO_M
    hd = math.hypot(hx, hy)
    if hd > 1e-4:
        hx /= hd
        hy /= hd
        if hx * (-p2a_x) + hy * (-p2a_y) < COS_CONE:
            return False
    return True


@njit(cache=True)
def _check_panels_at(
    x: float,
    y: float,
    floor: int,
    n1_x: float,
    n1_y: float,
    n2_x: float,
    n2_y: float,
    panel_lon: np.ndarray,
    panel_lat: np.ndarray,
    panel_floor: np.ndarray,
    panel_orientation: np.ndarray,
    panel_grid: Dict,
    person_idx: int,
    contacts: np.ndarray,
    reach: np.ndarray,
    viewing_mask: np.ndarray,
) -> None:
    cx = np.int32(int(x * LON_DEG_TO_M / GRID_CELL_M))
    cy = np.int32(int(y * LAT_DEG_TO_M / GRID_CELL_M))
    key = (floor, cx, cy)
    if key not in panel_grid:
        return
    for pi in panel_grid[key]:
        hit = _in_panel_view(
            x,
            y,
            floor,
            n1_x,
            n1_y,
            n2_x,
            n2_y,
            panel_lon[pi],
            panel_lat[pi],
            panel_floor[pi],
            panel_orientation[pi],
        )
        bit = np.uint64(1) << np.uint64(pi)
        seen = (viewing_mask[0] & bit) != 0
        if hit and not seen:
            contacts[pi] += 1
            _reach_add(reach, pi, person_idx)
            viewing_mask[0] |= bit
        elif not hit and seen:
            viewing_mask[0] &= ~bit


@njit(cache=True)
def _walk_single_edge(
    n1_i: int,
    n2_i: int,
    node_x: np.ndarray,
    node_y: np.ndarray,
    node_level: np.ndarray,
    step_meters: float,
    panel_lon: np.ndarray,
    panel_lat: np.ndarray,
    panel_floor: np.ndarray,
    panel_orientation: np.ndarray,
    panel_grid: Dict,
    person_idx: int,
    contacts: np.ndarray,
    reach: np.ndarray,
    viewing_mask: np.ndarray,
) -> None:
    n1_x = node_x[n1_i]
    n1_y = node_y[n1_i]
    n2_x = node_x[n2_i]
    n2_y = node_y[n2_i]
    dx = (n1_x - n2_x) * LON_DEG_TO_M
    dy = (n1_y - n2_y) * LAT_DEG_TO_M
    seg = math.hypot(dx, dy)
    steps = max(1, int(seg / step_meters))
    floor = node_level[n1_i]
    for s in range(steps + 1):
        t = s / steps
        x = n1_x + t * (n2_x - n1_x)
        y = n1_y + t * (n2_y - n1_y)
        _check_panels_at(
            x,
            y,
            floor,
            n1_x,
            n1_y,
            n2_x,
            n2_y,
            panel_lon,
            panel_lat,
            panel_floor,
            panel_orientation,
            panel_grid,
            person_idx,
            contacts,
            reach,
            viewing_mask,
        )


@njit(cache=True)
def _choose_next_node(
    cur_i: int,
    prev_i: int,
    target_i: int,
    adj_offsets: np.ndarray,
    adj_indices: np.ndarray,
    dist_row: np.ndarray,
    node_level: np.ndarray,
    node_is_vertical: np.ndarray,
    escalator_zone: np.ndarray,
    route_beta: float,
    route_randomness: float,
    route_zone_boost: float,
    route_vertical: float,
    rng_state: np.ndarray,
) -> int:
    start = adj_offsets[cur_i]
    end = adj_offsets[cur_i + 1]
    target_level = node_level[target_i]
    cur_dist = dist_row[cur_i]

    total = 0.0
    count = 0
    cand_v = np.empty(end - start, dtype=np.int32)
    cand_w = np.empty(end - start, dtype=np.float64)

    for k in range(start, end):
        v = adj_indices[k]
        if v == prev_i:
            continue
        if dist_row[v] == math.inf:
            continue
        progress = cur_dist - dist_row[v]
        score = route_beta * progress
        if escalator_zone[v]:
            score += route_zone_boost
        if node_level[v] != target_level and node_is_vertical[v]:
            score += route_vertical
        w = math.exp(score + route_randomness * _gumbel(rng_state))
        cand_v[count] = v
        cand_w[count] = w
        total += w
        count += 1

    if count == 0:
        return prev_i

    r = _rand(rng_state) * total
    for i in range(count):
        r -= cand_w[i]
        if r <= 0:
            return cand_v[i]
    return cand_v[count - 1]


@njit(cache=True)
def walk_segment_choice_numba(
    start_i: int,
    target_i: int,
    node_x: np.ndarray,
    node_y: np.ndarray,
    node_level: np.ndarray,
    node_is_vertical: np.ndarray,
    adj_offsets: np.ndarray,
    adj_indices: np.ndarray,
    dist_row: np.ndarray,
    escalator_zone: np.ndarray,
    route_beta: float,
    route_randomness: float,
    route_zone_boost: float,
    route_vertical: float,
    step_meters: float,
    panel_lon: np.ndarray,
    panel_lat: np.ndarray,
    panel_floor: np.ndarray,
    panel_orientation: np.ndarray,
    panel_grid: Dict,
    person_idx: int,
    contacts: np.ndarray,
    reach: np.ndarray,
    viewing_mask: np.ndarray,
    rng_state: np.ndarray,
) -> None:
    if start_i == target_i:
        return
    current = start_i
    prev = -1
    for _ in range(MAX_ROUTE_STEPS):
        if current == target_i:
            break
        nxt = _choose_next_node(
            current,
            prev,
            target_i,
            adj_offsets,
            adj_indices,
            dist_row,
            node_level,
            node_is_vertical,
            escalator_zone,
            route_beta,
            route_randomness,
            route_zone_boost,
            route_vertical,
            rng_state,
        )
        if nxt < 0 or nxt == current:
            break
        _walk_single_edge(
            current,
            nxt,
            node_x,
            node_y,
            node_level,
            step_meters,
            panel_lon,
            panel_lat,
            panel_floor,
            panel_orientation,
            panel_grid,
            person_idx,
            contacts,
            reach,
            viewing_mask,
        )
        prev = current
        current = nxt


@njit(cache=True)
def walk_path_numba(
    path_indices: np.ndarray,
    node_x: np.ndarray,
    node_y: np.ndarray,
    node_level: np.ndarray,
    step_meters: float,
    panel_lon: np.ndarray,
    panel_lat: np.ndarray,
    panel_floor: np.ndarray,
    panel_orientation: np.ndarray,
    panel_grid: Dict,
    person_idx: int,
    contacts: np.ndarray,
    reach: np.ndarray,
    viewing_mask: np.ndarray,
) -> None:
    for i in range(path_indices.shape[0] - 1):
        _walk_single_edge(
            path_indices[i],
            path_indices[i + 1],
            node_x,
            node_y,
            node_level,
            step_meters,
            panel_lon,
            panel_lat,
            panel_floor,
            panel_orientation,
            panel_grid,
            person_idx,
            contacts,
            reach,
            viewing_mask,
        )


class FastWalkContext:
    __slots__ = (
        "node_index",
        "node_x",
        "node_y",
        "node_level",
        "node_is_vertical",
        "adj_offsets",
        "adj_indices",
        "escalator_zone",
        "dist_to_target",
        "path_indices",
        "panel_lon",
        "panel_lat",
        "panel_floor",
        "panel_orientation",
        "panel_grid",
        "step_meters",
        "reach_bytes",
    )

    def __init__(
        self,
        node_index: dict[str, int],
        node_x: np.ndarray,
        node_y: np.ndarray,
        node_level: np.ndarray,
        node_is_vertical: np.ndarray,
        adj_offsets: np.ndarray,
        adj_indices: np.ndarray,
        escalator_zone: np.ndarray,
        dist_to_target: dict[str, np.ndarray],
        path_indices: dict[tuple[str, str], np.ndarray],
        panel_lon: np.ndarray,
        panel_lat: np.ndarray,
        panel_floor: np.ndarray,
        panel_orientation: np.ndarray,
        panel_grid: Dict,
        step_meters: float,
        reach_bytes: int,
    ):
        self.node_index = node_index
        self.node_x = node_x
        self.node_y = node_y
        self.node_level = node_level
        self.node_is_vertical = node_is_vertical
        self.adj_offsets = adj_offsets
        self.adj_indices = adj_indices
        self.escalator_zone = escalator_zone
        self.dist_to_target = dist_to_target
        self.path_indices = path_indices
        self.panel_lon = panel_lon
        self.panel_lat = panel_lat
        self.panel_floor = panel_floor
        self.panel_orientation = panel_orientation
        self.panel_grid = panel_grid
        self.step_meters = step_meters
        self.reach_bytes = reach_bytes


def _build_csr_adj(node_ids: list[str], adj_ids: dict[str, list[str]], node_index: dict[str, int]):
    n = len(node_ids)
    adj_indices: list[int] = []
    adj_offsets = np.zeros(n + 1, dtype=np.int32)
    for i, nid in enumerate(node_ids):
        for v in adj_ids.get(nid, []):
            vi = node_index.get(v)
            if vi is not None:
                adj_indices.append(vi)
        adj_offsets[i + 1] = len(adj_indices)
    return adj_offsets, np.array(adj_indices, dtype=np.int32)


def _build_panel_grid_numba(
    panel_lon: np.ndarray,
    panel_lat: np.ndarray,
    panel_floor: np.ndarray,
) -> Dict:
    grid = Dict.empty(key_type=types.UniTuple(types.int32, 3), value_type=types.int32[:])
    n = panel_lon.shape[0]
    for pi in range(n):
        cx = int(panel_lon[pi] * LON_DEG_TO_M / GRID_CELL_M)
        cy = int(panel_lat[pi] * LAT_DEG_TO_M / GRID_CELL_M)
        f = int(panel_floor[pi])
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                key = (np.int32(f), np.int32(cx + dx), np.int32(cy + dy))
                if key in grid:
                    old = grid[key]
                    new = np.empty(old.shape[0] + 1, dtype=np.int32)
                    new[:-1] = old
                    new[-1] = pi
                    grid[key] = new
                else:
                    grid[key] = np.array([pi], dtype=np.int32)
    return grid


def build_fast_context(ctx: dict, panels: list, step_meters: float, reach_bytes: int) -> FastWalkContext:
    if len(panels) > 64:
        raise ValueError("Numba fast path supports at most 64 panels (viewing bitmask)")
    nodes = ctx["nodes"]
    node_ids = ctx["node_ids"]
    node_index = ctx["node_index"]
    n = len(node_ids)

    node_x = np.empty(n, dtype=np.float64)
    node_y = np.empty(n, dtype=np.float64)
    node_level = np.empty(n, dtype=np.int32)
    node_is_vertical = np.zeros(n, dtype=np.bool_)
    for nid, i in node_index.items():
        node = nodes[nid]
        node_x[i] = node["x"]
        node_y[i] = node["y"]
        node_level[i] = int(node["level"])
        node_is_vertical[i] = node["type"] in ("escalator", "elevator")

    adj_offsets, adj_indices = _build_csr_adj(node_ids, ctx["adj_ids"], node_index)

    escalator_zone = np.zeros(n, dtype=np.bool_)
    for nid in ctx["escalator_zone"]:
        idx = node_index.get(nid)
        if idx is not None:
            escalator_zone[idx] = True

    dist_to_target = {
        target_id: np.array(row, dtype=np.float64)
        for target_id, row in ctx["dist_to_target"].items()
    }

    path_indices: dict[tuple[str, str], np.ndarray] = {}
    for start_id, targets in ctx["path_cache"].items():
        si = node_index.get(start_id)
        if si is None:
            continue
        for target_id, path in targets.items():
            if len(path) < 2:
                continue
            path_indices[(start_id, target_id)] = np.array(
                [node_index[nid] for nid in path if nid in node_index],
                dtype=np.int32,
            )

    panel_lon = np.array([p.lon for p in panels], dtype=np.float64)
    panel_lat = np.array([p.lat for p in panels], dtype=np.float64)
    panel_floor = np.array([int(p.floor) for p in panels], dtype=np.int32)
    panel_orientation = np.array([p.orientation for p in panels], dtype=np.float64)
    panel_grid = _build_panel_grid_numba(panel_lon, panel_lat, panel_floor)

    return FastWalkContext(
        node_index=node_index,
        node_x=node_x,
        node_y=node_y,
        node_level=node_level,
        node_is_vertical=node_is_vertical,
        adj_offsets=adj_offsets,
        adj_indices=adj_indices,
        escalator_zone=escalator_zone,
        dist_to_target=dist_to_target,
        path_indices=path_indices,
        panel_lon=panel_lon,
        panel_lat=panel_lat,
        panel_floor=panel_floor,
        panel_orientation=panel_orientation,
        panel_grid=panel_grid,
        step_meters=step_meters,
        reach_bytes=reach_bytes,
    )


def init_rng_state(trip_index: int) -> np.ndarray:
    state = np.zeros(1, dtype=np.uint64)
    state[0] = np.uint64(42 + trip_index)
    return state


def walk_route_fast(
    fast: FastWalkContext,
    start_id: str,
    target_id: str,
    person_idx: int,
    contacts: np.ndarray,
    reach: np.ndarray,
    viewing_mask: np.ndarray,
    rng_state: np.ndarray,
    routing_mode: str,
    route_beta: float,
    route_randomness: float,
    route_zone_boost: float,
    route_vertical: float,
) -> None:
    start_i = fast.node_index.get(start_id)
    target_i = fast.node_index.get(target_id)
    if start_i is None or target_i is None:
        return

    if routing_mode == "segment_logit":
        dist_row = fast.dist_to_target.get(target_id)
        if dist_row is None:
            return
        walk_segment_choice_numba(
            start_i,
            target_i,
            fast.node_x,
            fast.node_y,
            fast.node_level,
            fast.node_is_vertical,
            fast.adj_offsets,
            fast.adj_indices,
            dist_row,
            fast.escalator_zone,
            route_beta,
            route_randomness,
            route_zone_boost,
            route_vertical,
            fast.step_meters,
            fast.panel_lon,
            fast.panel_lat,
            fast.panel_floor,
            fast.panel_orientation,
            fast.panel_grid,
            person_idx,
            contacts,
            reach,
            viewing_mask,
            rng_state,
        )
        return

    path = fast.path_indices.get((start_id, target_id))
    if path is not None and path.shape[0] > 1:
        walk_path_numba(
            path,
            fast.node_x,
            fast.node_y,
            fast.node_level,
            fast.step_meters,
            fast.panel_lon,
            fast.panel_lat,
            fast.panel_floor,
            fast.panel_orientation,
            fast.panel_grid,
            person_idx,
            contacts,
            reach,
            viewing_mask,
        )


def apply_fast_metrics(panels: list, contacts: np.ndarray, reach: np.ndarray) -> None:
    for i, panel in enumerate(panels):
        panel.contacts += int(contacts[i])
        other = reach[i]
        for j in range(len(panel.reach.data)):
            panel.reach.data[j] |= other[j]


def warmup() -> None:
    """Trigger JIT compilation with a tiny dummy run."""
    grid = Dict.empty(key_type=types.UniTuple(types.int32, 3), value_type=types.int32[:])
    grid[(np.int32(1), np.int32(0), np.int32(0))] = np.array([0], dtype=np.int32)
    node_x = np.array([174.7770, 174.7780], dtype=np.float64)
    node_y = np.array([-36.8700, -36.8700], dtype=np.float64)
    node_level = np.array([1, 1], dtype=np.int32)
    node_is_vertical = np.array([False, False])
    adj_offsets = np.array([0, 1, 2], dtype=np.int32)
    adj_indices = np.array([1, 0], dtype=np.int32)
    dist_row = np.array([100.0, 0.0], dtype=np.float64)
    escalator_zone = np.array([False, False])
    panel_lon = np.array([0.0], dtype=np.float64)
    panel_lat = np.array([0.0], dtype=np.float64)
    panel_floor = np.array([1], dtype=np.int32)
    panel_orientation = np.array([0.0], dtype=np.float64)
    contacts = np.zeros(1, dtype=np.int64)
    reach = np.zeros((1, 1), dtype=np.uint8)
    viewing_mask = np.zeros(1, dtype=np.uint64)
    rng_state = init_rng_state(0)
    walk_segment_choice_numba(
        0,
        1,
        node_x,
        node_y,
        node_level,
        node_is_vertical,
        adj_offsets,
        adj_indices,
        dist_row,
        escalator_zone,
        0.08,
        1.0,
        0.35,
        0.5,
        2.0,
        panel_lon,
        panel_lat,
        panel_floor,
        panel_orientation,
        grid,
        0,
        contacts,
        reach,
        viewing_mask,
        rng_state,
    )


if __name__ == "__main__":
    warmup()
    assert _rand(np.array([np.uint64(99)], dtype=np.uint64)) > 0.0
    print("sim_fast ok")
