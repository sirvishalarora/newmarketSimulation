# Westfield Newmarket Pedestrian Simulation

A browser-based pedestrian simulation for the Westfield Newmarket mall in Auckland, NZ.
The application visualizes simulated agent movement, panel detection, floor layers, and configurable routing behavior.

## Project Files

- `index.html` — Main application page.
- `app.js` — Simulation logic, map initialization, pathfinding, and UI behavior.
- `style.css` — UI styling for the simulation interface.
- `panel_locations_with_floor.csv` — Panel location data loaded by the simulation.
- `newmarket_graph.json` — Graph topology data used by the simulation.
- `Westfield_NewMarket_topology.geojson` / `Westfield_NewMarket_topology_4326.geojson` / `Westfield_Albany_topology.geojson` — GeoJSON files for mapping/topology reference.
- `generate_graph.py`, `generate_map.py`, `convert_newmarket_topology.py`, `verify_graph.py` — Python utilities for generating or validating graph and map data.

## Prerequisites

- A modern web browser (Chrome, Edge, Firefox, Safari).
- Local web server to serve files, because the app loads CSV and JSON via `fetch`.
- Python 3 installed if using the built-in HTTP server.

## Start the Application

From the project root directory (`/root/nwmSimulation`), start a simple HTTP server:

```bash
python3 -m http.server 8000
```

Then open the app in your browser:

```text
http://localhost:8000/
```

If you use VS Code, you can also open `index.html` with a Live Server extension.

## Stop the Application

If you started the server with Python, stop it by focusing the terminal and pressing:

```text
Ctrl+C
```

## How to Use

1. Open the app in your browser.
2. Use the `Start Simulation` button to begin agent movement.
3. Use the `Reset` button to pause and restart the simulation state.
4. Adjust simulation speed, spawn rate, walk speed, and visualization toggles in the sidebar.

## Notes

- The simulation loads panel and topology data from local CSV/JSON files.
- The app uses Leaflet for map rendering and overlays.
- No build step is required.
