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

# 2. Build the navigation graph. Polygon topology:
python3 generate_graph.py --mall newmarket
#    ...or node/edge CSV topology:
python3 import_csv_topology.py --mall albany

# 3. Sanity-check it: duplicate ids, dangling edges, connectivity.
python3 verify_graph.py --mall albany

# 4. Run the simulation.
python3 run_batch_simulation.py --mall albany

# 5. Score it against observed MAID similarity, where available.
python3 validate_against_observed.py --mall albany
```

Stage 4 writes `panel_metrics.csv` and `panel_pair_overlap.csv` into the mall's
`results_dir`.

## Two similarity measures

`panel_pair_overlap.csv` carries both, and they are not interchangeable:

- **overlap coefficient** = shared / smaller audience — how much of the smaller
  panel's audience the larger already covers.
- **Jaccard** = shared / combined audience — what the MAID-derived observed
  matrices measure, and what `validate_against_observed.py` scores on.

Jaccard is always the smaller of the two. Comparing a simulated overlap
coefficient against an observed Jaccard makes a well-calibrated run look about
twice too high.

## Topology: three flavours

`generate_graph.py` reads OSM vocabulary — `indoor=corridor`,
`highway=steps`+`conveying=yes`, `highway=elevator`, `entrance=*`, `level` — in
EPSG:4326. A mall's topology reaches that shape one of two ways:

- **Curated polygons.** Hand-drawn zones (`zone_type` / `zone_name` /
  `floor_level`) in EPSG:3857. `convert_topology.py` translates and reprojects
  it, then `generate_graph.py` meshes the corridors. Newmarket.
- **Node/edge CSV.** An explicit graph — waypoint mesh plus named entries,
  weighted anchors and paired escalators — seeded from the centre's asset plan.
  `import_csv_topology.py` converts it directly. Albany.
- **Native OSM.** Exported straight from OpenStreetMap. In the target
  vocabulary and CRS already, but rarely complete enough to use: Albany's
  export has 2 corridor polygons, 8 entrances, **no shop entry points** and
  **no escalators** (10 `highway=steps`, none tagged `conveying=yes`), so a
  graph built from it has nowhere to walk to and no way between floors. It is
  kept for reference and mapping only.

`Westfield_Albany_topology.geojson` is that OSM export. Albany's actual graph
comes from `data/albany/albany_nodes.csv` + `albany_edges.csv`.

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

### Using the editor

```bash
python3 start_server.py 8000
```

Then open `http://localhost:8000/panel_editor.html?mall=albany` — omit the
parameter for Newmarket. The sidebar has links to switch between malls.

The editor resolves its files from `malls.json`, generated from the same
registry the pipeline uses. **Regenerate it after editing `malls.py`:**

```bash
python3 malls.py
```

Floors, the floor switcher, and the map extent all come from the loaded data,
so a new mall needs nothing configured in the page. The backdrop is whatever
the mall has: a polygon floorplan for Newmarket, the corridor mesh with its
named entrances, destinations and escalators for Albany.

Drag markers or edit lat/lon/orientation, then **Download Updated CSV** — it
writes `<mall>_panel_locations_<date>.csv` in the same format as the input.
Replace the mall's `panels` file with it and re-run the simulation.

### The in-browser simulation

`index.html` takes the same `?mall=` parameter and runs the simulation
interactively — footfall, gravity and routing sliders, live map, exposure and
similarity results. It shares mall resolution with the editor via
`mall_config.js`, so both pages and the Python pipeline read one registry.

Two things adapt to the loaded mall beyond its files:

- **Footfall sliders** start at the mall's configured figures, widening their
  range if needed rather than silently clamping to a footfall it never had.
- **Destination weights.** The store-category sliders are named for
  Newmarket's tenants. A topology that supplies its own destination weights —
  as Albany's does (Food Court 9, New World 8, Kmart 7, …) — uses them
  directly; the sliders are then disabled and say so. Categories likewise come
  from the topology when it states them, since name matching only recognises
  Newmarket's tenants and would file every Albany anchor but two under
  "specialty".

The browser and headless engines agree: on Albany they rank the top panels
identically (27014, 27025, 27019, 27015, 27023).

## Footfall

`weekly_visits` and `weekly_uniques` scale every reach number. A mall with no
agreed figure leaves them unset in the registry and must supply them per run:

```bash
python3 run_batch_simulation.py --mall albany --weekly-visits 150000 --weekly-uniques 95000
```

Albany's configured 132k/81k is **derived, not agreed**:
`data/albany/albany_demand.json` puts Albany at 8.4M annual visits against
Newmarket's 12.7M, so Newmarket's 200k/123k scaled by 8.4/12.7. Replace it with
a real figure when one exists.

## Mall trend pipeline

`mall_trends/` is separate: it builds weekly visitor-trend indexes from
BigQuery ping data and loads them into
`geo-reach.mortalportal.site_weekly_trend`, which the reach API reads as a
per-site seasonal trend. It needs BigQuery credentials
(`gcloud auth application-default login`).

## Status by mall

| | Newmarket (17056) | Albany (17055) |
|---|---|---|
| Topology source | curated polygons | node/edge CSV |
| Graph | 1025 nodes, 5728 edges, 3 levels | 707 nodes, 3400 edges, 2 levels |
| Destinations | 42 shop entries | 8 weighted anchors |
| Entrances / escalators | 11 / 19 | 5 / 8 |
| Panels | 54, hand-placed, 54 distinct positions | 35, **16 distinct positions** |
| Footfall | 200k visits / 123k uniques | 132k / 81k, derived from 8.4M annual |
| Observed MAID similarity | — | 35×35 Jaccard matrix |

Albany runs end to end today. Scored against the observed MAID matrix over all
595 panel pairs, an uncalibrated full-week run gives:

| | observed | simulated |
|---|---|---|
| mean Jaccard | 0.255 | 0.240 (0.94×) |
| Pearson r | | 0.558 |
| Spearman ρ | | 0.594 |

The **level** is close; the **rank** correlation is where the remaining error
sits, and coarse panel positions are the most likely cause — 35 Albany panels
occupy 16 distinct coordinates, so panels that are genuinely apart in the
centre are simulated as if co-located. Newmarket solved this with the manual
placement pass; Albany has not had one, and unlike Newmarket it has ground
truth to check the result against.

## Known issues

- `--no-numba` raises `KeyError: 'path_cache'` under the default
  `segment_logit` routing: `trim_sim_context` drops the cache that the pure
  Python walk loop still reads. Use the Numba path, or `--routing shortest`.
