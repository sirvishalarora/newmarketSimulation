// Panel Location & Orientation Editor
//
// Which centre is edited comes from the ?mall= query parameter, resolved
// against malls.json -- the same registry the Python pipeline reads, so the
// editor and the simulation can never disagree about a mall's files.
// Regenerate malls.json with `python3 malls.py` after changing malls.py.

// Constants for coordinate distance scale
const LAT_DEG_TO_M = 111000.0;
let LON_DEG_TO_M = 88800.0; // set per mall once its bounds are known

// Global Editor State
let map;
let geojsonData;
let panels = [];
let selectedPanel = null;
let mallConfig = null;

// Map Layer groups. Floors are discovered from the backdrop and the panel CSV
// rather than assumed to be 1/2/3 -- Newmarket has three, Albany has two.
let floorLayers = {};
let panelLayer = L.layerGroup();
let coneLayer = L.layerGroup();
let activeFloor = null;

// Return the layer group for a floor, creating it on first use.
function floorLayer(level) {
    const key = String(level);
    if (!floorLayers[key]) {
        floorLayers[key] = L.featureGroup();
    }
    return floorLayers[key];
}

function sortedFloors() {
    return Object.keys(floorLayers).sort((a, b) => {
        const na = parseFloat(a), nb = parseFloat(b);
        if (isNaN(na) || isNaN(nb)) return a.localeCompare(b);
        return na - nb;
    });
}

// Resolve the requested mall against malls.json.
function loadMallConfig() {
    const requested = new URLSearchParams(window.location.search).get("mall");
    return fetch('malls.json')
        .then(response => {
            if (!response.ok) {
                throw new Error(`Failed to load malls.json: HTTP ${response.status}`);
            }
            return response.json();
        })
        .then(registry => {
            const key = requested || registry.default;
            const config = registry.malls[key];
            if (!config) {
                const known = Object.keys(registry.malls).join(", ");
                throw new Error(`Unknown mall '${key}'. Available: ${known}`);
            }
            mallConfig = config;
            mallConfig.allKeys = Object.keys(registry.malls);
            document.title = `${config.name} Panel Editor`;
            const subtitle = document.querySelector(".sidebar-header .subtitle");
            if (subtitle) {
                subtitle.textContent = `${config.name} — drag markers or edit values to position panels`;
            }
            const note = document.getElementById("csv-target-name");
            if (note) note.textContent = config.panels;
            return config;
        });
}

// Cone parameters (consistent with simulation)
const maxViewingDistance = 15.0;
const viewingConeAngle = 60.0;

// Helper: Parse CSV
function parseCSV(text) {
    const lines = text.split("\n");
    if (lines.length === 0) return [];
    
    const headers = lines[0].split(",").map(h => h.trim().replace(/^"|"$/g, ''));
    const result = [];
    
    for (let i = 1; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) continue;
        
        const cols = line.split(",").map(c => c.trim().replace(/^"|"$/g, ''));
        const obj = {};
        for (let j = 0; j < headers.length; j++) {
            obj[headers[j]] = cols[j] || "";
        }
        result.push(obj);
    }
    return result;
}

// Initialize Leaflet Map
function initMap() {
    // No fixed centre: the view is fitted to the backdrop once it loads, so a
    // new mall needs no coordinates configured anywhere.
    map = L.map('map', {
        center: [-36.8715, 174.7766],
        zoom: 18,
        minZoom: 16,
        maxZoom: 21,
        zoomControl: true,
        attributionControl: false
    });

    // Dark minimalist basemap
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 20
    }).addTo(map);

    panelLayer.addTo(map);
    coneLayer.addTo(map);

    setTimeout(() => {
        map.invalidateSize();
    }, 200);
}

// Load whichever backdrop this mall has: a polygon floorplan or a corridor
// mesh. Both exist only to give the person placing panels something to place
// them against, so they render into the same per-floor layer groups.
function loadBackdrop() {
    if (mallConfig.backdrop.type === "graph") {
        return loadGraphBackdrop(mallConfig.backdrop.path);
    }
    return loadGeoJSON(mallConfig.backdrop.path);
}

// Corridor-mesh backdrop: walkable edges as lines, plus the named entries,
// destinations and escalators that anchor the layout.
function loadGraphBackdrop(path) {
    return fetch(path)
        .then(response => {
            if (!response.ok) {
                throw new Error(`Failed to load graph ${path}: HTTP ${response.status}`);
            }
            return response.json();
        })
        .then(graph => {
            const nodeById = {};
            (graph.nodes || []).forEach(n => { nodeById[n.id] = n; });

            const nodeStyles = {
                mall_entrance: { color: '#10b981', radius: 7, label: 'Entrance' },
                shop_entry:    { color: '#f59e0b', radius: 7, label: 'Destination' },
                escalator:     { color: '#d97706', radius: 6, label: 'Escalator' },
                elevator:      { color: '#06b6d4', radius: 6, label: 'Elevator' }
            };

            (graph.edges || []).forEach(edge => {
                const a = nodeById[edge.source], b = nodeById[edge.target];
                if (!a || !b) return;
                // Vertical links join two floors; drawing them on either one
                // is misleading, so they are left out of the floor layers.
                if (String(a.level) !== String(b.level)) return;
                L.polyline([[a.y, a.x], [b.y, b.x]], {
                    color: 'rgba(148, 163, 184, 0.35)',
                    weight: 2
                }).addTo(floorLayer(a.level));
            });

            (graph.nodes || []).forEach(node => {
                const style = nodeStyles[node.type];
                if (!style) return; // plain corridor mesh nodes stay implicit
                const marker = L.circleMarker([node.y, node.x], {
                    radius: style.radius,
                    fillColor: style.color,
                    color: style.color,
                    weight: 1.5,
                    opacity: 0.9,
                    fillOpacity: 0.65
                });
                marker.bindTooltip(node.name || style.label, {
                    permanent: false,
                    direction: 'top',
                    className: 'shop-label-tooltip'
                });
                marker.addTo(floorLayer(node.level));
            });
        });
}

// Polygon floorplan backdrop.
function loadGeoJSON(path) {
    return fetch(path)
        .then(response => {
            if (!response.ok) {
                throw new Error(`Failed to load topology ${path}: HTTP ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            geojsonData = data;
            
            L.geoJSON(geojsonData, {
                pointToLayer: function(feature, latlng) {
                    const props = feature.properties || {};
                    const isEntrance = !!props.entrance;
                    return L.circleMarker(latlng, {
                        radius: isEntrance ? 6 : 4,
                        fillColor: isEntrance ? '#10b981' : '#6366f1',
                        color: isEntrance ? '#059669' : '#4f46e5',
                        weight: 1.5,
                        opacity: 0.9,
                        fillOpacity: 0.7
                    });
                },
                style: function(feature) {
                    const props = feature.properties || {};
                    const indoor = props.indoor;
                    
                    if (indoor === "corridor") {
                        return {
                            fillColor: '#334155',
                            fillOpacity: 0.35,
                            color: 'rgba(255, 255, 255, 0.12)',
                            weight: 1,
                            dashArray: '3, 5'
                        };
                    } else if (props.highway === "steps" || props.highway === "elevator") {
                        return {
                            fillColor: props.highway === "steps" ? '#d97706' : '#0891b2',
                            fillOpacity: 0.45,
                            color: props.highway === "steps" ? '#f59e0b' : '#06b6d4',
                            weight: 1.5
                        };
                    } else {
                        return {
                            fillColor: '#0f172a',
                            fillOpacity: 0.75,
                            color: 'rgba(99, 102, 241, 0.35)',
                            weight: 1.2
                        };
                    }
                },
                onEachFeature: function(feature, layer) {
                    const props = feature.properties || {};
                    const level = props.level || "1";
                    
                    if (props.name && props.indoor === "room") {
                        let dispName = props.name.replace(/_lv[1-3].*/, '').replace(/_/g, ' ');
                        dispName = dispName.charAt(0).toUpperCase() + dispName.slice(1);
                        layer.bindTooltip(dispName, {
                            permanent: false,
                            direction: 'center',
                            className: 'shop-label-tooltip'
                        });
                    }
                    
                    floorLayer(level).addLayer(layer);
                }
            });
        });
}

// Load Panels from CSV
function loadPanels() {
    return fetch(mallConfig.panels)
        .then(response => {
            if (!response.ok) {
                throw new Error(`Failed to load ${mallConfig.panels}: HTTP ${response.status}`);
            }
            return response.text();
        })
        .then(csvText => {
            const parsed = parseCSV(csvText);
            panels = parsed.map(row => ({
                id: row.panel_id,
                siteId: row.site_id || String(mallConfig.siteId),
                name: `Panel ${row.panel_id}`,
                lon: parseFloat(row.longitude),
                lat: parseFloat(row.latitude),
                floor: row.floor.trim(),
                orientation: parseFloat(row.orientation),
                marker: null,
                cone: null
            }));

            // A panel on a floor the backdrop does not cover still needs a
            // layer, or it would silently vanish from the editor.
            panels.forEach(p => floorLayer(p.floor));
        });
}

// Build the floor switcher from the floors actually present, then show the
// lowest one. Called once, after the backdrop and panels have both loaded.
function initFloors() {
    // The map is laid out after initMap() runs, and Leaflet computes a zoom of
    // maxZoom for any bounds while it still believes the container is 0x0 --
    // which reads as the editor opening blank. Re-measure before fitting.
    map.invalidateSize();

    const container = document.querySelector(".floor-selector");
    const floors = sortedFloors();
    if (container) {
        container.innerHTML = "";
        floors.forEach(level => {
            const btn = document.createElement("button");
            btn.className = "floor-btn";
            btn.setAttribute("data-floor", level);
            btn.textContent = `Level ${level}`;
            btn.addEventListener("click", () => switchFloor(level));
            container.appendChild(btn);
        });
    }

    const floorSelect = document.getElementById("edit-panel-floor");
    if (floorSelect) {
        floorSelect.innerHTML = "";
        floors.forEach(level => {
            const option = document.createElement("option");
            option.value = level;
            option.textContent = `Level ${level}`;
            floorSelect.appendChild(option);
        });
    }

    activeFloor = floors[0] || "1";
    floorLayer(activeFloor).addTo(map);
    const activeBtn = document.querySelector(`.floor-btn[data-floor="${activeFloor}"]`);
    if (activeBtn) activeBtn.classList.add("active");

    // Fit to every floor, not just the first one: floors rarely share a
    // footprint, and fitting to the smallest opens the editor zoomed into a
    // corner of the centre.
    let bounds = null;
    floors.forEach(level => {
        const b = floorLayer(level).getBounds();
        if (!b || !b.isValid()) return;
        bounds = bounds ? bounds.extend(b) : L.latLngBounds(b.getSouthWest(), b.getNorthEast());
    });
    if (bounds && bounds.isValid()) {
        fitWhenSized(bounds);
        // Longitude degrees shrink with latitude; use the fitted centre so the
        // view cones are drawn to the same scale the simulation measures with.
        LON_DEG_TO_M = 111320.0 * Math.cos(bounds.getCenter().lat * Math.PI / 180);
    }

    renderPanelsGrid();
    renderPanelMarkers();
}

// Fit once the map container has a real size.
//
// initFloors() can run before the stylesheet has been applied, and while
// Leaflet still measures the container as 0x0 it resolves ANY bounds to
// maxZoom -- which opens the editor blank, zoomed into a few square metres.
// Waiting for a non-zero size costs a frame or two and is the difference
// between a usable first view and an apparently broken one.
function fitWhenSized(bounds, attemptsLeft = 60) {
    map.invalidateSize();
    const size = map.getSize();
    if (size.x > 0 && size.y > 0) {
        map.fitBounds(bounds, { padding: [10, 10] });
        return;
    }
    if (attemptsLeft > 0) {
        requestAnimationFrame(() => fitWhenSized(bounds, attemptsLeft - 1));
    }
}

// Offer the other malls as links, so switching does not mean editing the URL.
function initMallSwitcher() {
    const container = document.getElementById("mall-switcher");
    if (!container || !mallConfig.allKeys) return;
    container.innerHTML = "";
    mallConfig.allKeys.forEach(key => {
        const link = document.createElement("a");
        link.href = `?mall=${encodeURIComponent(key)}`;
        link.textContent = key;
        link.className = "mall-link" + (key === mallConfig.key ? " active" : "");
        container.appendChild(link);
    });
}

// Render Panel Markers on Map
function renderPanelMarkers() {
    panelLayer.clearLayers();
    coneLayer.clearLayers();
    
    panels.forEach(panel => {
        const isSelected = selectedPanel && selectedPanel.id === panel.id;
        
        // Custom HTML marker style
        const customIcon = L.divIcon({
            html: `<div class="panel-marker-inner ${isSelected ? 'panel-marker-selected' : ''}" id="marker-inner-${panel.id}"></div>`,
            className: 'panel-map-marker',
            iconSize: [16, 16],
            iconAnchor: [8, 8]
        });
        
        // Create marker (make it draggable!)
        const marker = L.marker([panel.lat, panel.lon], { 
            icon: customIcon,
            draggable: true
        });
        
        marker.bindTooltip(`<b>${panel.name}</b><br>Floor: L${panel.floor}<br>Orient: ${panel.orientation}°<br><i>Drag to reposition</i>`);
        panel.marker = marker;
        
        // Handle selection on click
        marker.on('click', () => {
            selectPanel(panel);
        });
        
        // Handle drag events
        marker.on('drag', (e) => {
            const newLatLng = e.target.getLatLng();
            panel.lat = newLatLng.lat;
            panel.lon = newLatLng.lng;
            
            // Recompute its specific wedge
            updatePanelWedge(panel);
            
            // If it is the selected panel, update sidebar fields
            if (isSelected) {
                document.getElementById("edit-panel-lat").value = panel.lat.toFixed(8);
                document.getElementById("edit-panel-lon").value = panel.lon.toFixed(8);
            }
        });
        
        // Update selection on drag end
        marker.on('dragend', () => {
            selectPanel(panel);
        });
        
        // Only add to active floor
        if (panel.floor === activeFloor) {
            panelLayer.addLayer(marker);
            updatePanelWedge(panel);
        }
    });
}

// Draw/Update orientation wedge for a single panel
function updatePanelWedge(panel) {
    if (panel.cone) {
        coneLayer.removeLayer(panel.cone);
        panel.cone = null;
    }
    
    if (panel.floor !== activeFloor) return;
    
    const centerLat = panel.lat;
    const centerLon = panel.lon;
    const orient = panel.orientation;
    
    // Wedge coordinates starting at center
    const points = [[centerLat, centerLon]];
    
    const startAngle = orient - viewingConeAngle;
    const endAngle = orient + viewingConeAngle;
    
    for (let a = startAngle; a <= endAngle; a += 5) {
        const aRad = (a * Math.PI) / 180.0;
        const latOffset = (maxViewingDistance * Math.cos(aRad)) / LAT_DEG_TO_M;
        const lonOffset = (maxViewingDistance * Math.sin(aRad)) / LON_DEG_TO_M;
        points.push([centerLat + latOffset, centerLon + lonOffset]);
    }
    
    points.push([centerLat, centerLon]);
    
    const isSelected = selectedPanel && selectedPanel.id === panel.id;
    
    const wedge = L.polygon(points, {
        color: isSelected ? 'rgba(6, 182, 212, 0.45)' : 'rgba(236, 72, 153, 0.35)',
        weight: 1.5,
        fillColor: isSelected ? '#06b6d4' : '#ec4899',
        fillOpacity: isSelected ? 0.12 : 0.06,
        interactive: false
    });
    
    panel.cone = wedge;
    coneLayer.addLayer(wedge);
}

// Select a panel for editing
function selectPanel(panel) {
    // Unselect previous card
    if (selectedPanel) {
        const prevCard = document.getElementById(`card-edit-${selectedPanel.id}`);
        if (prevCard) prevCard.classList.remove("editor-selected");
        
        const prevMarker = document.getElementById(`marker-inner-${selectedPanel.id}`);
        if (prevMarker) prevMarker.classList.remove("panel-marker-selected");
    }
    
    selectedPanel = panel;
    
    // Show and populate form
    document.getElementById("editor-no-selection").style.display = "none";
    document.getElementById("editor-form").style.display = "block";
    
    document.getElementById("edit-panel-name").value = panel.name;
    document.getElementById("edit-panel-floor").value = panel.floor;
    document.getElementById("edit-panel-orientation").value = panel.orientation;
    document.getElementById("val-edit-orientation").textContent = `${panel.orientation}°`;
    document.getElementById("edit-panel-lat").value = panel.lat.toFixed(8);
    document.getElementById("edit-panel-lon").value = panel.lon.toFixed(8);
    
    // Highlight new selection
    const activeCard = document.getElementById(`card-edit-${panel.id}`);
    if (activeCard) {
        activeCard.classList.add("editor-selected");
        activeCard.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
    
    const activeMarker = document.getElementById(`marker-inner-${panel.id}`);
    if (activeMarker) activeMarker.classList.add("panel-marker-selected");
    
    // Refresh wedge color
    panels.forEach(p => updatePanelWedge(p));
}

// Render panel list directory in sidebar
function renderPanelsGrid(searchFilter = "") {
    const grid = document.getElementById("editor-panels-grid");
    grid.innerHTML = "";
    
    const filtered = panels.filter(p => {
        return p.id.toLowerCase().includes(searchFilter.toLowerCase()) || 
               p.floor.includes(searchFilter);
    });
    
    if (filtered.length === 0) {
        grid.innerHTML = `<div class="loading-placeholder"><p>No panels match.</p></div>`;
        return;
    }
    
    filtered.forEach(panel => {
        const isSelected = selectedPanel && selectedPanel.id === panel.id;
        const card = document.createElement("div");
        card.className = `panel-card-select ${isSelected ? 'editor-selected' : ''}`;
        card.id = `card-edit-${panel.id}`;
        
        let flClass = "fl-1";
        if (panel.floor === "2") flClass = "fl-2";
        if (panel.floor === "3") flClass = "fl-3";
        
        card.innerHTML = `
            <div class="panel-card-info" style="width: 100%;">
                <div class="panel-card-id" style="display: flex; justify-content: space-between;">
                    <span>${panel.name}</span>
                    <span class="panel-card-floor-badge ${flClass}">L${panel.floor}</span>
                </div>
                <div class="panel-card-meta" style="margin-top: 4px; display: flex; justify-content: space-between; font-size: 9px;">
                    <span>Lat: ${panel.lat.toFixed(5)}</span>
                    <span>Lon: ${panel.lon.toFixed(5)}</span>
                    <span>Orient: ${panel.orientation}°</span>
                </div>
            </div>
        `;
        
        card.addEventListener('click', () => {
            // Switch floor if card is on another level
            if (panel.floor !== activeFloor) {
                switchFloor(panel.floor);
            }
            
            selectPanel(panel);
            
            // Pan map to panel position
            map.panTo([panel.lat, panel.lon]);
        });
        
        grid.appendChild(card);
    });
}

// Handle switching floor level
function switchFloor(floorNum) {
    const mapFloorBtns = document.querySelectorAll(".floor-btn");
    mapFloorBtns.forEach(btn => {
        if (btn.getAttribute("data-floor") === floorNum) {
            btn.classList.add("active");
        } else {
            btn.classList.remove("active");
        }
    });
    
    const prevFloor = activeFloor;
    activeFloor = floorNum;
    
    // Swap layers
    if (floorLayers[prevFloor]) map.removeLayer(floorLayers[prevFloor]);
    if (floorLayers[activeFloor]) map.addLayer(floorLayers[activeFloor]);
    
    // Re-draw markers/wedges for the active floor
    renderPanelMarkers();
}

// Bind input change triggers in Sidebar Editor Form
function bindEditorFormEvents() {
    // Orientation slider
    const sOrient = document.getElementById("edit-panel-orientation");
    sOrient.addEventListener("input", () => {
        if (!selectedPanel) return;
        const val = parseInt(sOrient.value);
        selectedPanel.orientation = val;
        document.getElementById("val-edit-orientation").textContent = `${val}°`;
        
        // Update marker tooltip and redraw wedge
        selectedPanel.marker.setTooltipContent(`<b>${selectedPanel.name}</b><br>Floor: L${selectedPanel.floor}<br>Orient: ${selectedPanel.orientation}°<br><i>Drag to reposition</i>`);
        updatePanelWedge(selectedPanel);
        
        // Update list card
        const card = document.getElementById(`card-edit-${selectedPanel.id}`);
        if (card) {
            const meta = card.querySelector(".panel-card-meta");
            meta.children[2].textContent = `Orient: ${val}°`;
        }
    });
    
    // Latitude field
    const inputLat = document.getElementById("edit-panel-lat");
    inputLat.addEventListener("input", () => {
        if (!selectedPanel) return;
        const latVal = parseFloat(inputLat.value);
        if (isNaN(latVal)) return;
        
        selectedPanel.lat = latVal;
        selectedPanel.marker.setLatLng([selectedPanel.lat, selectedPanel.lon]);
        updatePanelWedge(selectedPanel);
        
        const card = document.getElementById(`card-edit-${selectedPanel.id}`);
        if (card) {
            const meta = card.querySelector(".panel-card-meta");
            meta.children[0].textContent = `Lat: ${latVal.toFixed(5)}`;
        }
    });
    
    // Longitude field
    const inputLon = document.getElementById("edit-panel-lon");
    inputLon.addEventListener("input", () => {
        if (!selectedPanel) return;
        const lonVal = parseFloat(inputLon.value);
        if (isNaN(lonVal)) return;
        
        selectedPanel.lon = lonVal;
        selectedPanel.marker.setLatLng([selectedPanel.lat, selectedPanel.lon]);
        updatePanelWedge(selectedPanel);
        
        const card = document.getElementById(`card-edit-${selectedPanel.id}`);
        if (card) {
            const meta = card.querySelector(".panel-card-meta");
            meta.children[1].textContent = `Lon: ${lonVal.toFixed(5)}`;
        }
    });
    
    // Floor dropdown selector
    const selectFloor = document.getElementById("edit-panel-floor");
    selectFloor.addEventListener("change", () => {
        if (!selectedPanel) return;
        const newFl = selectFloor.value;
        
        selectedPanel.floor = newFl;
        
        // Redraw all panel markers (it will move to correct layer group)
        switchFloor(newFl);
        selectPanel(selectedPanel);
        renderPanelsGrid(document.getElementById("editor-search").value);
    });
}

// Download modified panel configurations as CSV
function downloadUpdatedCSV() {
    if (panels.length === 0) return;
    
    // original columns: panel_id,site_id,latitude,longitude,orientation,floor
    const headers = ["panel_id", "site_id", "latitude", "longitude", "orientation", "floor"];
    
    const rows = panels.map(p => [
        p.id,
        p.siteId,
        p.lat.toFixed(8),
        p.lon.toFixed(8),
        p.orientation,
        p.floor
    ]);
    
    const csvContent = [headers.join(",")].concat(rows.map(r => r.join(","))).join("\n");
    
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    
    const dateStr = new Date().toISOString().slice(0, 10);
    link.setAttribute("download", `${mallConfig.key}_panel_locations_${dateStr}.csv`);
    
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// Main DOM Entry Point
window.addEventListener("DOMContentLoaded", () => {
    initMap();
    
    // Bind search field filter
    const searchField = document.getElementById("editor-search");
    searchField.addEventListener("input", () => {
        renderPanelsGrid(searchField.value);
    });
    
    // Floor buttons are built in initFloors(), once the floors are known.

    // Bind Sidebar actions and forms
    bindEditorFormEvents();
    document.getElementById("btn-download-csv").addEventListener("click", downloadUpdatedCSV);

    // Resolve the mall first: everything else depends on which files to fetch.
    loadMallConfig()
        .then(() => {
            initMallSwitcher();
            return Promise.all([loadBackdrop(), loadPanels()]);
        })
        .then(() => {
            initFloors();
            console.log(`Panel editor ready (${mallConfig.name}, ${panels.length} panels).`);
        })
        .catch(err => {
            console.error("Initialization failed: ", err);
            const grid = document.getElementById("editor-panels-grid");
            if (grid) {
                grid.innerHTML = `<p class="help-text" style="color:#f87171;">${err.message}</p>`;
            }
        });
});
