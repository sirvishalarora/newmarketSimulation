# Mall panel simulation

Agent-based simulation of shopper movement inside a Westfield centre, used to
estimate per-panel weekly reach and contacts and the pairwise overlap between
panels in the same centre.

Shoppers enter at `mall_entrance` nodes, walk a corridor grid to `shop_entry`
destinations, and change floors via escalators and elevators. A panel records a
contact when a walking agent passes within its view cone.

## Pipeline

Every stage takes `--mall <key>`, resolved against the registry in
[malls.py](malls.py). Adding a centre means adding an entry there, not editing
the scripts.

```bash
# 1. Only for a mall with a curated zone-schema topology (see below).
python3 convert_topology.py --mall newmarket

# 2. Build the navigation graph from the topology.
python3 generate_graph.py --mall newmarket

# 3. Sanity-check it: duplicate ids, dangling edges, connectivity.
python3 verify_graph.py --mall newmarket

# 4. Run the simulation.
python3 run_batch_simulation.py --mall newmarket
```

Stage 4 writes `panel_metrics.csv` and `panel_pair_overlap.csv` into the mall's
`results_dir`.

## Topology: two flavours

`generate_graph.py` reads OSM vocabulary — `indoor=corridor`,
`highway=steps`+`conveying=yes`, `highway=elevator`, `entrance=*`, `level` — in
EPSG:4326. A mall's topology reaches that shape one of two ways:

- **Curated.** Hand-drawn zones (`zone_type` / `zone_name` / `floor_level`) in
  EPSG:3857. `convert_topology.py` translates and reprojects it. Newmarket.
- **Native OSM.** Exported straight from OpenStreetMap, already in the target
  vocabulary and CRS, so stage 1 is skipped (`source_topology=None`). Albany.

A native OSM export is rarely complete enough on its own: it tends to be
0-based, tag multi-floor features as `"0;1"`, and omit shop entry points and
escalator `conveying` tags. `Mall.level_map` handles the level vocabulary;
missing entry points and escalators are a curation job on the topology itself.

## Panel positions

`run_batch_simulation.py` reads the mall's `panels` CSV:
`panel_id,site_id,latitude,longitude,orientation,floor`.

Panel coordinates in the warehouse are **too coarse to simulate with** — for
Newmarket, 54 panels sit at 17 distinct positions, and for Albany 35 panels sit
at 16. Panels sharing a coordinate see identical passers-by, so every pairwise
overlap collapses to ~1.0.

Newmarket's positions were therefore refined by hand in `panel_editor.html`
(drag to reposition, assign floor). `panel_locations_with_floor_org.csv` is the
raw warehouse extract; `panel_locations_with_floor.csv` is the edited result
with 54 distinct positions. Any new mall needs the same pass.

> The editor and the viewer (`app.js`) are still pinned to Newmarket's topology,
> CSV, and a fixed Level 1/2/3 control. They have not been parameterised yet.

## Footfall

`weekly_visits` and `weekly_uniques` scale every reach number. A mall with no
agreed figure leaves them unset in the registry and must supply them per run:

```bash
python3 run_batch_simulation.py --mall albany --weekly-visits 150000 --weekly-uniques 95000
```

## Mall trend pipeline

`mall_trends/` is separate: it builds weekly visitor-trend indexes from
BigQuery ping data and loads them into
`geo-reach.mortalportal.site_weekly_trend`, which the reach API reads as a
per-site seasonal trend. It needs BigQuery credentials
(`gcloud auth application-default login`).

## Status by mall

| | Newmarket (17056) | Albany (17055) |
|---|---|---|
| Topology | curated, 3 levels | raw OSM, needs curation |
| Corridors | 4 polys, ~17,700 m² | 2 polys, ~10,500 m² |
| Shop entries | 42 | 0 — none tagged |
| Escalators | 19 | 0 — 10 `steps`, none `conveying` |
| Panel positions | 54, hand-placed | 35, warehouse-coarse |
| Footfall | configured | not agreed |

## Known issues

- `--no-numba` raises `KeyError: 'path_cache'` under the default
  `segment_logit` routing: `trim_sim_context` drops the cache that the pure
  Python walk loop still reads. Use the Numba path, or `--routing shortest`.
