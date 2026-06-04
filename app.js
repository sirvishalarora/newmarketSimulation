// Westfield Newmarket Pedestrian Simulation Engine

// Constants
const LAT_DEG_TO_M = 111000.0;
const LON_DEG_TO_M = 88800.0; // at Auckland latitude

// Global Panels list (loaded from CSV)
let panels = [];

// Parse CSV helper
function parseCSV(text) {
    const lines = text.split("\n");
    if (lines.length === 0) return [];
    
    // Clean headers
    const headers = lines[0].split(",").map(h => h.trim().replace(/^"|"$/g, ''));
    const result = [];
    
    for (let i = 1; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) continue;
        
        // Simple comma split (assuming no commas inside quotes)
        const cols = line.split(",").map(c => c.trim().replace(/^"|"$/g, ''));
        const obj = {};
        for (let j = 0; j < headers.length; j++) {
            obj[headers[j]] = cols[j] || "";
        }
        result.push(obj);
    }
    return result;
}

// Load panel locations from CSV
function loadPanels() {
    return fetch('panel_locations_with_floor.csv')
        .then(response => response.text())
        .then(csvText => {
            const parsed = parseCSV(csvText);
            panels = parsed.map(row => ({
                id: row.panel_id,
                name: `Panel ${row.panel_id} (O: ${row.orientation}°)`,
                lon: parseFloat(row.longitude),
                lat: parseFloat(row.latitude),
                floor: row.floor.trim(),
                orientation: row.orientation,
                crossedAgents: new Set(),
                marker: null
            }));
            console.log(`Loaded ${panels.length} panels from CSV.`);
            renderPanelListUI();
            renderPanelMarkers();
        })
        .catch(err => {
            console.error("Error loading CSV panels:", err);
            panels = [];
        });
}

// Simulation State
let map;
let geojsonData;
let graphData;
let adjacencyList = {};
let nodesMap = {};
let activeFloor = "1";
let isRunning = false;
let agents = [];
let totalSpawns = 0;
let lastSpawnTime = 0;
let lastUpdateTime = 0;

// UI Configuration Parameters
let simSpeedMultiplier = 5;
let maxActiveAgents = 200;
let spawnRatePerMin = 60;
let baseWalkSpeedMS = 1.3;
let showGraph = false;
let showPaths = true;

// Attractiveness weights
let categoryWeights = {
    farmers: 0.9,
    davidjones: 0.9,
    hm: 0.7,
    woolworths: 0.8,
    jbhifi: 0.85,
    foodcourt: 0.95,
    specialty: 0.3
};

// Map Layers
let floorLayers = { "1": L.featureGroup(), "2": L.featureGroup(), "3": L.featureGroup() };
let graphLayer = L.layerGroup();
let agentLayer = L.layerGroup();
let panelLayer = L.layerGroup();

// Priority Queue for Dijkstra
class PriorityQueue {
    constructor() {
        this.values = [];
    }
    enqueue(val, priority) {
        this.values.push({ val, priority });
        this.sort();
    }
    dequeue() {
        return this.values.shift().val;
    }
    sort() {
        this.values.sort((a, b) => a.priority - b.priority);
    }
    isEmpty() {
        return this.values.length === 0;
    }
}

// Distance helper
function distanceM(p1, p2) {
    const dx = (p1[0] - p2[0]) * LON_DEG_TO_M;
    const dy = (p1[1] - p2[1]) * LAT_DEG_TO_M;
    return Math.hypot(dx, dy);
}

// Dijkstra Pathfinding Algorithm
function findShortestPath(startNodeId, endNodeId) {
    if (!adjacencyList[startNodeId] || !adjacencyList[endNodeId]) return [];
    
    const dist = {};
    const prev = {};
    const queue = new PriorityQueue();
    
    // Initialize
    for (const nodeId in nodesMap) {
        dist[nodeId] = Infinity;
        prev[nodeId] = null;
    }
    dist[startNodeId] = 0;
    queue.enqueue(startNodeId, 0);
    
    while (!queue.isEmpty()) {
        const u = queue.dequeue();
        if (u === endNodeId) break;
        
        const neighbors = adjacencyList[u];
        if (!neighbors) continue;
        
        for (const edge of neighbors) {
            const v = edge.target;
            const alt = dist[u] + edge.weight;
            if (alt < dist[v]) {
                dist[v] = alt;
                prev[v] = u;
                queue.enqueue(v, alt);
            }
        }
    }
    
    // Reconstruct path
    const path = [];
    let curr = endNodeId;
    if (prev[curr] !== null || curr === startNodeId) {
        while (curr !== null) {
            path.unshift(curr);
            curr = prev[curr];
        }
    }
    return path;
}

// Initialize Leaflet Map
function initMap() {
    map = L.map('map', {
        center: [-36.8715, 174.7766], // Center of Westfield Newmarket
        zoom: 18,
        minZoom: 16,
        maxZoom: 21,
        zoomControl: true,
        attributionControl: false
    });

    // Premium Minimalist Dark Basemap
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        maxZoom: 20
    }).addTo(map);
    
    // Add layers to map
    floorLayers["1"].addTo(map);
    agentLayer.addTo(map);
    panelLayer.addTo(map);
}

// Load and Render Westfield Newmarket GeoJSON layouts
function loadGeoJSON() {
    fetch('Westfield_NewMarket_topology_4326.geojson')
        .then(response => response.json())
        .then(data => {
            geojsonData = data;
            
            L.geoJSON(geojsonData, {
                style: function(feature) {
                    const props = feature.properties;
                    const indoor = props.indoor;
                    const name = props.name || "";
                    
                    if (indoor === "corridor") {
                        return {
                            fillColor: '#475569',
                            fillOpacity: 0.22,
                            color: '#64748b',
                            weight: 1,
                            dashArray: '4'
                        };
                    } else if (props.highway === "steps") {
                        return {
                            fillColor: '#d97706',
                            fillOpacity: 0.45,
                            color: '#f59e0b',
                            weight: 1.5
                        };
                    } else if (props.highway === "elevator") {
                        return {
                            fillColor: '#0891b2',
                            fillOpacity: 0.45,
                            color: '#06b6d4',
                            weight: 1.5
                        };
                    } else if (props.entrance) {
                        return {
                            fillColor: '#059669',
                            fillOpacity: 0.6,
                            color: '#10b981',
                            weight: 1
                        };
                    } else {
                        // Regular shop
                        return {
                            fillColor: '#1e293b',
                            fillOpacity: 0.65,
                            color: 'rgba(255, 255, 255, 0.08)',
                            weight: 1
                        };
                    }
                },
                onEachFeature: function(feature, layer) {
                    const props = feature.properties;
                    const level = props.level || "1";
                    
                    // Bind tooltips for shop names
                    if (props.name && props.indoor === "room") {
                        // Format clean display name
                        let dispName = props.name.replace(/_lv[1-3].*/, '').replace(/_/g, ' ');
                        dispName = dispName.charAt(0).toUpperCase() + dispName.slice(1);
                        layer.bindTooltip(dispName, {
                            permanent: false,
                            direction: 'center',
                            className: 'shop-label-tooltip'
                        });
                    }
                    
                    // Put in correct floor layer group
                    if (floorLayers[level]) {
                        floorLayers[level].addLayer(layer);
                    }
                }
            });
            
            // Zoom to fit bounds
            const bounds = floorLayers["1"].getBounds();
            if (bounds.isValid()) {
                map.fitBounds(bounds, { padding: [20, 20] });
            }
        });
}

// Load Network Graph and build connectivity lists
function loadGraph() {
    fetch('newmarket_graph.json')
        .then(response => response.json())
        .then(data => {
            graphData = data;
            
            // Build Nodes Map and Adjacency list
            graphData.nodes.forEach(node => {
                nodesMap[node.id] = node;
                adjacencyList[node.id] = [];
            });
            
            graphData.edges.forEach(edge => {
                const s = edge.source;
                const t = edge.target;
                const w = edge.weight;
                
                if (adjacencyList[s] && adjacencyList[t]) {
                    adjacencyList[s].push({ target: t, weight: w });
                    adjacencyList[t].push({ target: s, weight: w });
                }
            });
            
            // Render Graph overlay
            renderGraphOverlay();
        });
}

// Draw the network graph links faintly on the map
function renderGraphOverlay() {
    graphLayer.clearLayers();
    if (!graphData) return;
    
    graphData.edges.forEach(edge => {
        const sNode = nodesMap[edge.source];
        const tNode = nodesMap[edge.target];
        if (!sNode || !tNode) return;
        
        // Render if edge level matches active floor
        // Handle floor transit links (render on both floors)
        const isTransit = sNode.level !== tNode.level;
        const matchesLevel = sNode.level === activeFloor || tNode.level === activeFloor;
        
        if (matchesLevel) {
            const color = isTransit ? '#c084fc' : '#8b5cf6';
            const weight = isTransit ? 2 : 0.8;
            const dashArray = isTransit ? '3, 5' : '1';
            const opacity = isTransit ? 0.6 : 0.15;
            
            const line = L.polyline(
                [[sNode.y, sNode.x], [tNode.y, tNode.x]],
                { color: color, weight: weight, opacity: opacity, dashArray: dashArray }
            );
            graphLayer.addLayer(line);
        }
    });
    
    if (showGraph) {
        graphLayer.addTo(map);
    }
}

// Get store category by name
function getStoreCategory(name) {
    if (!name) return "specialty";
    const nameLower = name.toLowerCase();
    
    if (nameLower.includes("farmers")) return "farmers";
    if (nameLower.includes("davidjones") || nameLower.includes("david jones")) return "davidjones";
    if (nameLower.includes("handm") || nameLower.includes("h&m") || nameLower.includes("hm")) return "hm";
    if (nameLower.includes("woolworths") || nameLower.includes("countdown")) return "woolworths";
    if (nameLower.includes("jbhifi") || nameLower.includes("jb hifi") || nameLower.includes("jb hi-fi")) return "jbhifi";
    if (nameLower.includes("food_court") || nameLower.includes("foodcourt")) return "foodcourt";
    
    return "specialty";
}

// Select target destination shop based on weights and/or gravity model
function selectTargetShop(agent, algorithm) {
    const level = agent.level;
    
    // Get all shop entry nodes
    const shopNodes = Object.values(nodesMap).filter(n => n.type === "shop_entry");
    if (shopNodes.length === 0) return null;
    
    const candidates = [];
    let totalWeight = 0;
    
    const currentLoc = [nodesMap[agent.currentNodeId].x, nodesMap[agent.currentNodeId].y];
    
    shopNodes.forEach(node => {
        // Do not choose same shop
        if (node.id === agent.lastVisitedShopId) return;
        
        const cat = getStoreCategory(node.name);
        let baseWt = categoryWeights[cat] || 0.3;
        
        // Turn weight slider percentages into fraction
        baseWt = Math.max(0.001, baseWt); 
        
        if (algorithm === "gravity") {
            // Gravity Model: P(S) ~ Attraction / Dist^1.5
            const dist = distanceM(currentLoc, [node.x, node.y]);
            
            // Avoid divide by 0 if agent is right on shop entry
            const distFactor = Math.max(2.0, dist);
            const wt = baseWt / Math.pow(distFactor, 1.3); // decay factor 1.3
            candidates.push({ node, weight: wt });
            totalWeight += wt;
        } else {
            // Normal Goal-Oriented Choice
            candidates.push({ node, weight: baseWt });
            totalWeight += baseWt;
        }
    });
    
    if (totalWeight === 0) return shopNodes[Math.floor(Math.random() * shopNodes.length)];
    
    // Roulette wheel selection
    let r = Math.random() * totalWeight;
    for (const cand of candidates) {
        r -= cand.weight;
        if (r <= 0) return cand.node;
    }
    
    return candidates[candidates.length - 1].node;
}

// Agent class containing simulation properties and update loop
class Agent {
    constructor() {
        totalSpawns++;
        this.id = `agent_${totalSpawns}`;
        
        // Find a random mall entrance to spawn
        const spawnNodes = Object.values(nodesMap).filter(n => n.type === "mall_entrance");
        const startNode = spawnNodes[Math.floor(Math.random() * spawnNodes.length)];
        
        this.currentNodeId = startNode.id;
        this.level = startNode.level;
        this.x = startNode.x;
        this.y = startNode.y;
        
        // Configurable base speed + small variation (1.1m/s to 1.6m/s)
        this.speedMS = baseWalkSpeedMS * (0.85 + Math.random() * 0.3);
        
        this.status = "active";
        this.visitedCount = 0;
        this.lastVisitedShopId = null;
        this.maxVisits = 2 + Math.floor(Math.random() * 3); // shop visits count before exiting (2 to 4)
        
        this.path = [];
        this.pathIndex = 0;
        this.segmentProgress = 0; // time elapsed in current edge traversal
        this.segmentDuration = 0; // total time required for current edge
        this.prevNodePos = [this.x, this.y];
        this.nextNodePos = [this.x, this.y];
        
        // Create circle marker on map
        // Render on canvas to support hundreds of agents smoothly
        this.marker = L.circleMarker([this.y, this.x], {
            renderer: L.canvas(),
            radius: 5,
            fillColor: this.getFloorColor(this.level),
            color: '#ffffff',
            weight: 1,
            fillOpacity: 0.85
        });
        
        // Show tooltip on hover
        this.marker.bindTooltip(`Agent #${totalSpawns}<br>Level: ${this.level}<br>Speed: ${this.speedMS.toFixed(2)} m/s`, {
            direction: 'top'
        });
        
        // Only draw if agent level matches active floor view
        if (this.level === activeFloor) {
            this.marker.addTo(agentLayer);
        }
        
        // Find first destination path
        this.setNextDestination();
    }
    
    getFloorColor(level) {
        if (level === "1") return "#3b82f6"; // Blue
        if (level === "2") return "#10b981"; // Green
        if (level === "3") return "#d97706"; // Amber
        return "#8b5cf6";
    }
    
    setNextDestination() {
        const algo = document.getElementById("select-algo").value;
        
        if (algo === "random") {
            // Random Walk Algorithm: simply choose a random adjacent edge
            const neighbors = adjacencyList[this.currentNodeId];
            if (!neighbors || neighbors.length === 0) {
                // Remove if trapped, should not happen in a connected graph
                this.status = "finished";
                return;
            }
            
            const nextEdge = neighbors[Math.floor(Math.random() * neighbors.length)];
            const nextNode = nodesMap[nextEdge.target];
            
            this.path = [this.currentNodeId, nextNode.id];
            this.pathIndex = 0;
            this.setupSegment(this.currentNodeId, nextNode.id);
            return;
        }
        
        // Goal-Oriented or Gravity model
        if (this.visitedCount >= this.maxVisits) {
            // Head to exit
            const spawnNodes = Object.values(nodesMap).filter(n => n.type === "mall_entrance");
            const exitNode = spawnNodes[Math.floor(Math.random() * spawnNodes.length)];
            
            this.path = findShortestPath(this.currentNodeId, exitNode.id);
            this.pathIndex = 0;
            
            if (this.path.length <= 1) {
                this.status = "finished";
            } else {
                this.setupSegment(this.path[0], this.path[1]);
            }
        } else {
            // Select next target shop
            const targetShop = selectTargetShop(this, algo);
            if (!targetShop) {
                this.status = "finished";
                return;
            }
            
            this.path = findShortestPath(this.currentNodeId, targetShop.id);
            this.pathIndex = 0;
            this.targetShopId = targetShop.id;
            
            if (this.path.length <= 1) {
                // Directly touch if already adjacent
                this.touchShopAndProceed();
            } else {
                this.setupSegment(this.path[0], this.path[1]);
            }
        }
    }
    
    setupSegment(nodeId1, nodeId2) {
        const n1 = nodesMap[nodeId1];
        const n2 = nodesMap[nodeId2];
        
        this.prevNodePos = [n1.x, n1.y];
        this.nextNodePos = [n2.x, n2.y];
        
        const dist = distanceM(this.prevNodePos, this.nextNodePos);
        
        this.segmentProgress = 0;
        this.segmentDuration = dist / this.speedMS; // T = D / S
        
        this.level = n2.level;
    }
    
    touchShopAndProceed() {
        this.visitedCount++;
        this.lastVisitedShopId = this.targetShopId;
        
        // With 0 dwell time: immediately pick next target shop (or exit) and return to corridor
        this.setNextDestination();
    }
    
    update(dt) {
        if (this.status !== "active") return;
        
        // Tick time elapsed multiplied by simulation speed multiplier
        const simDt = dt * simSpeedMultiplier;
        this.segmentProgress += simDt;
        
        if (this.segmentProgress >= this.segmentDuration) {
            // Arrived at next node in path segment
            const nextNodeId = this.path[this.pathIndex + 1];
            this.currentNodeId = nextNodeId;
            this.x = this.nextNodePos[0];
            this.y = this.nextNodePos[1];
            
            this.pathIndex++;
            
            // Check if we reached the final node of current path
            if (this.pathIndex >= this.path.length - 1) {
                const algo = document.getElementById("select-algo").value;
                if (algo === "random") {
                    // Random Walk updates node by node continuously
                    this.setNextDestination();
                } else if (this.visitedCount >= this.maxVisits) {
                    // Reached mall exit
                    this.status = "finished";
                } else {
                    // Reached shop entrance, touch it and pick new destination
                    this.touchShopAndProceed();
                }
            } else {
                // Setup next segment in current path
                this.setupSegment(this.path[this.pathIndex], this.path[this.pathIndex + 1]);
            }
        } else {
            // Interpolate position linearly along the segment coordinates
            const t = this.segmentProgress / this.segmentDuration;
            this.x = this.prevNodePos[0] + t * (this.nextNodePos[0] - this.prevNodePos[0]);
            this.y = this.prevNodePos[1] + t * (this.nextNodePos[1] - this.prevNodePos[1]);
        }
        
        // Update marker position
        this.marker.setLatLng([this.y, this.x]);
        
        // Filter marker visibility on active floor switching
        if (this.level === activeFloor) {
            if (!map.hasLayer(this.marker)) {
                this.marker.addTo(agentLayer);
            }
            
            // Update color to match floor
            this.marker.setStyle({ fillColor: this.getFloorColor(this.level) });
        } else {
            if (map.hasLayer(this.marker)) {
                map.removeLayer(this.marker);
            }
        }
        
        // Verify path rendering if enabled
        this.renderPathLine();
        
        // Run Panel detection check
        this.checkPanelCrossing();
    }
    
    renderPathLine() {
        if (!showPaths || this.level !== activeFloor) {
            if (this.pathLine) {
                map.removeLayer(this.pathLine);
                this.pathLine = null;
            }
            return;
        }
        
        const pathCoords = [];
        // Map remaining path nodes to lat/lons
        for (let i = this.pathIndex; i < this.path.length; i++) {
            const node = nodesMap[this.path[i]];
            if (node && node.level === activeFloor) {
                pathCoords.push([node.y, node.x]);
            }
        }
        
        // Add current interpolated position at the front of the line
        pathCoords.unshift([this.y, this.x]);
        
        if (pathCoords.length > 1) {
            if (this.pathLine) {
                this.pathLine.setLatLngs(pathCoords);
            } else {
                this.pathLine = L.polyline(pathCoords, {
                    color: this.getFloorColor(this.level),
                    weight: 1.5,
                    opacity: 0.35,
                    dashArray: '3, 4'
                }).addTo(agentLayer);
            }
        } else {
            if (this.pathLine) {
                map.removeLayer(this.pathLine);
                this.pathLine = null;
            }
        }
    }
    
    checkPanelCrossing() {
        // Find active floor panels
        panels.forEach(panel => {
            if (panel.floor !== this.level) return;
            
            // Check if checkbox is selected for this panel
            const chk = document.getElementById(`chk-${panel.id}`);
            if (!chk || !chk.checked) return;
            
            // Distance threshold: 8.0 meters
            const dist = distanceM([this.x, this.y], [panel.lon, panel.lat]);
            if (dist < 8.0) {
                if (!panel.crossedAgents.has(this.id)) {
                    panel.crossedAgents.add(this.id);
                    
                    // Trigger visual flash
                    triggerPanelCrossingFeedback(panel.id);
                }
            }
        });
    }
    
    cleanup() {
        if (map.hasLayer(this.marker)) {
            map.removeLayer(this.marker);
        }
        if (this.pathLine) {
            map.removeLayer(this.pathLine);
        }
    }
}

// UI trigger crossing animation and count update
function triggerPanelCrossingFeedback(panelId) {
    const el = document.getElementById(`item-${panelId}`);
    if (el) {
        el.classList.add("active-crossing");
        // Flash panel badge count
        const badge = el.querySelector(".panel-crossing-badge");
        const panel = panels.find(p => p.id === panelId);
        if (badge && panel) {
            badge.textContent = panel.crossedAgents.size;
        }
        
        // Remove active class after animation fades
        setTimeout(() => {
            el.classList.remove("active-crossing");
        }, 1000);
    }
    
    // Flash map marker
    const panel = panels.find(p => p.id === panelId);
    if (panel && panel.marker) {
        const element = panel.marker.getElement();
        if (element) {
            const innerIcon = element.querySelector('.panel-marker-inner');
            if (innerIcon) {
                innerIcon.classList.add('detecting');
                setTimeout(() => {
                    innerIcon.classList.remove('detecting');
                }, 1000);
            }
        }
    }
    
    updateCrossingSummary();
}

// Calculate unique agents crossing the SELECTED set of panels (Set 2 Requirement)
function updateCrossingSummary() {
    const selectedActiveUnique = new Set();
    
    panels.forEach(panel => {
        const chk = document.getElementById(`chk-${panel.id}`);
        if (chk && chk.checked) {
            panel.crossedAgents.forEach(agentId => {
                selectedActiveUnique.add(agentId);
            });
        }
    });
    
    document.getElementById("unique-cross-count").textContent = selectedActiveUnique.size;
}

// Render Panel list in the UI Sidebar
function renderPanelListUI() {
    const container = document.getElementById("panel-list-container");
    container.innerHTML = "";
    
    panels.forEach(panel => {
        const item = document.createElement("div");
        item.className = "panel-item";
        item.id = `item-${panel.id}`;
        
        item.innerHTML = `
            <div class="panel-item-left">
                <input type="checkbox" id="chk-${panel.id}" checked />
                <span class="panel-name">${panel.name}</span>
            </div>
            <div class="panel-crossing-badge">0</div>
        `;
        
        // Checkbox listener to update unique crossed counter immediately on toggle
        item.querySelector("input").addEventListener("change", () => {
            updateCrossingSummary();
            updatePanelMarkersVisibility();
        });
        
        container.appendChild(item);
    });
}

// Draw panel markers on Leaflet map
function renderPanelMarkers() {
    panelLayer.clearLayers();
    
    panels.forEach(panel => {
        // Custom HTML pulsing marker
        const customIcon = L.divIcon({
            html: '<div class="panel-marker-inner"></div>',
            className: 'panel-map-marker',
            iconSize: [20, 20]
        });
        
        const marker = L.marker([panel.lat, panel.lon], { icon: customIcon });
        marker.bindTooltip(`${panel.name}<br>Floor: L${panel.floor}`, { direction: 'top' });
        
        panel.marker = marker;
        
        // Show marker on map only if floor level matches and it is selected/active
        if (panel.floor === activeFloor) {
            const chk = document.getElementById(`chk-${panel.id}`);
            if (!chk || chk.checked) {
                panelLayer.addLayer(marker);
            }
        }
    });
}

// Hide/Show panel markers when active floor switches or checkboxes toggle
function updatePanelMarkersVisibility() {
    panels.forEach(panel => {
        if (!panel.marker) return;
        
        const chk = document.getElementById(`chk-${panel.id}`);
        const isActive = !chk || chk.checked;
        const matchesLevel = panel.floor === activeFloor;
        
        if (matchesLevel && isActive) {
            if (!panelLayer.hasLayer(panel.marker)) {
                panelLayer.addLayer(panel.marker);
            }
        } else {
            if (panelLayer.hasLayer(panel.marker)) {
                panelLayer.removeLayer(panel.marker);
            }
        }
    });
}

// Main Simulation Loop
function updateSimulation() {
    if (!isRunning) return;
    
    const now = performance.now();
    let dt = (now - lastUpdateTime) / 1000.0; // seconds
    
    // Safety cap to avoid huge leaps during lags
    if (dt > 0.1) dt = 0.1;
    
    lastUpdateTime = now;
    
    // 1. Spawning Agents
    const spawnIntervalSec = 60.0 / spawnRatePerMin; // spawn delay in seconds
    const elapsedSpawnTime = (now - lastSpawnTime) / 1000.0;
    
    if (elapsedSpawnTime >= spawnIntervalSec && agents.length < maxActiveAgents) {
        if (graphData) {
            const agent = new Agent();
            agents.push(agent);
            lastSpawnTime = now;
            
            document.getElementById("stat-total-spawns").textContent = totalSpawns;
        }
    }
    
    // 2. Update all active agents
    const activeAgents = [];
    agents.forEach(agent => {
        agent.update(dt);
        if (agent.status === "active") {
            activeAgents.push(agent);
        } else {
            // Remove agent from map
            agent.cleanup();
        }
    });
    agents = activeAgents;
    
    // 3. Update UI Metrics
    document.getElementById("stat-active-agents").textContent = agents.length;
    
    // Recur loop using requestAnimationFrame for 60fps smoothness
    requestAnimationFrame(updateSimulation);
}

// Bind UI Control Event Listeners
function bindUIEvents() {
    // Start / Pause
    const btnStart = document.getElementById("btn-start");
    btnStart.addEventListener("click", () => {
        if (isRunning) {
            isRunning = false;
            btnStart.textContent = "Resume Simulation";
            btnStart.className = "btn btn-primary";
            document.getElementById("sim-status").textContent = "Paused";
            document.getElementById("sim-status").style.background = "rgba(245, 158, 11, 0.2)";
            document.getElementById("sim-status").style.color = "#fbbf24";
        } else {
            isRunning = true;
            btnStart.textContent = "Pause Simulation";
            btnStart.className = "btn btn-secondary";
            document.getElementById("sim-status").textContent = "Running";
            document.getElementById("sim-status").style.background = "rgba(16, 185, 129, 0.2)";
            document.getElementById("sim-status").style.color = "#34d399";
            
            lastUpdateTime = performance.now();
            lastSpawnTime = performance.now();
            updateSimulation();
        }
    });
    
    // Reset
    document.getElementById("btn-reset").addEventListener("click", () => {
        isRunning = false;
        btnStart.textContent = "Start Simulation";
        btnStart.className = "btn btn-primary";
        document.getElementById("sim-status").textContent = "Paused";
        document.getElementById("sim-status").style.background = "rgba(245, 158, 11, 0.2)";
        document.getElementById("sim-status").style.color = "#fbbf24";
        
        // Clean up agents
        agents.forEach(agent => agent.cleanup());
        agents = [];
        totalSpawns = 0;
        
        // Reset panels crossing data
        panels.forEach(panel => {
            panel.crossedAgents.clear();
            const badge = document.querySelector(`#item-${panel.id} .panel-crossing-badge`);
            if (badge) badge.textContent = "0";
        });
        
        document.getElementById("stat-total-spawns").textContent = "0";
        document.getElementById("stat-active-agents").textContent = "0";
        document.getElementById("unique-cross-count").textContent = "0";
    });
    
    // Floor Switching Button selectors
    const floorBtns = document.querySelectorAll(".floor-btn");
    floorBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            floorBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            
            const prevFloor = activeFloor;
            activeFloor = btn.getAttribute("data-floor");
            
            // Toggle Leaflet geojson overlays
            if (floorLayers[prevFloor]) map.removeLayer(floorLayers[prevFloor]);
            if (floorLayers[activeFloor]) map.addLayer(floorLayers[activeFloor]);
            
            // Re-render graph overlay links matching the floor level
            renderGraphOverlay();
            
            // Update panel marker display
            updatePanelMarkersVisibility();
        });
    });
    
    // Configuration Sliders
    
    // Simulation speed
    const simSpeedSlider = document.getElementById("input-sim-speed");
    simSpeedSlider.addEventListener("input", () => {
        simSpeedMultiplier = parseInt(simSpeedSlider.value);
        document.getElementById("val-sim-speed").textContent = `${simSpeedMultiplier}x`;
    });
    
    // Max Agents
    const maxAgentsSlider = document.getElementById("input-max-agents");
    maxAgentsSlider.addEventListener("input", () => {
        maxActiveAgents = parseInt(maxAgentsSlider.value);
        document.getElementById("val-max-agents").textContent = maxActiveAgents;
    });
    
    // Spawn Rate
    const spawnRateSlider = document.getElementById("input-spawn-rate");
    spawnRateSlider.addEventListener("input", () => {
        spawnRatePerMin = parseInt(spawnRateSlider.value);
        document.getElementById("val-spawn-rate").textContent = spawnRatePerMin;
    });
    
    // Walking Speed
    const walkSpeedSlider = document.getElementById("input-walk-speed");
    walkSpeedSlider.addEventListener("input", () => {
        baseWalkSpeedMS = parseFloat(walkSpeedSlider.value);
        document.getElementById("val-walk-speed").textContent = `${baseWalkSpeedMS.toFixed(1)} m/s`;
    });
    
    // Toggle Walk paths line render
    const chkPaths = document.getElementById("chk-show-paths");
    chkPaths.addEventListener("change", () => {
        showPaths = chkPaths.checked;
    });
    
    // Toggle Graph overlay links
    const chkGraph = document.getElementById("chk-show-graph");
    chkGraph.addEventListener("change", () => {
        showGraph = chkGraph.checked;
        if (showGraph) {
            map.addLayer(graphLayer);
        } else {
            map.removeLayer(graphLayer);
        }
    });
    
    // Attractiveness destination Weights sliders
    const wtSliders = [
        { id: "wt-farmers", cat: "farmers", labelId: "val-wt-farmers" },
        { id: "wt-davidjones", cat: "davidjones", labelId: "val-wt-davidjones" },
        { id: "wt-hm", cat: "hm", labelId: "val-wt-hm" },
        { id: "wt-woolworths", cat: "woolworths", labelId: "val-wt-woolworths" },
        { id: "wt-jbhifi", cat: "jbhifi", labelId: "val-wt-jbhifi" },
        { id: "wt-foodcourt", cat: "foodcourt", labelId: "val-wt-foodcourt" },
        { id: "wt-specialty", cat: "specialty", labelId: "val-wt-specialty" }
    ];
    
    wtSliders.forEach(slider => {
        const el = document.getElementById(slider.id);
        el.addEventListener("input", () => {
            const val = parseInt(el.value);
            categoryWeights[slider.cat] = val / 100.0;
            document.getElementById(slider.labelId).textContent = `${val}%`;
        });
    });
}

// App Initialization Entry Point
window.addEventListener("DOMContentLoaded", () => {
    initMap();
    loadGeoJSON();
    loadGraph();
    loadPanels().then(() => {
        bindUIEvents();
    });
});
