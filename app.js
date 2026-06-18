// Westfield Newmarket Pedestrian Gravity Simulation Engine (Headless Mode with Map Overlays)

// Constants
const LAT_DEG_TO_M = 111000.0;
const LON_DEG_TO_M = 88800.0; // at Auckland latitude

// Global Simulation & Map State
let map;
let geojsonData;
let graphData;
let nodesMap = {};
let adjacencyList = {};
let distanceMatrix = {}; // sourceNodeId -> { targetNodeId: distance }
let pathCache = {}; // sourceNodeId -> { targetNodeId: pathArray }
let panels = [];

// Similarity State
let selectedReferencePanel = null;
let selectedSimilarityMetric = "jaccard";


// Map Layer groups
let floorLayers = { "1": L.featureGroup(), "2": L.featureGroup(), "3": L.featureGroup() };
let graphLayer = L.layerGroup();
let panelLayer = L.layerGroup();
let coneLayer = L.layerGroup();
let activeFloor = "1";
let showGraph = false;

// UI Configuration Parameters
let totalAgentsToSimulate = 50000;
let minShopVisits = 2;
let maxShopVisits = 4;
let baseWalkSpeedMS = 1.3;
let decayExponent = 1.3;
let maxViewingDistance = 15.0;
let viewingConeAngle = 60.0;

// let categoryWeights = {
//     farmers: 0.9,
//     davidjones: 0.9,
//     hm: 0.7,
//     woolworths: 0.8,
//     jbhifi: 0.85,
//     foodcourt: 0.95,
//     noelleeming: 0.4,
//     archiebrothers: 0.35,
//     rebelsport: 0.4,
//     specialty: 0.3
// };

let categoryWeights = {
    farmers: 0.45,
    davidjones: .16,
    hm: 0.26,
    woolworths: 0.70,
    jbhifi: 0.30,
    foodcourt: 0.78,
    noelleeming: 0.4,
    archiebrothers: 0.35,
    rebelsport: 0.4,
    specialty: 0.5
};


// Simulation Execution Statistics
let simulatedAgentsData = [];
let shopCategoryVisits = {
    farmers: 0,
    davidjones: 0,
    hm: 0,
    woolworths: 0,
    jbhifi: 0,
    foodcourt: 0,
    noelleeming: 0,
    archiebrothers: 0,
    rebelsport: 0,
    specialty: 0
};
let floorDetections = {
    "1": new Set(),
    "2": new Set(),
    "3": new Set()
};

// Chart instances
let storeVisitsChart = null;
let floorCrossingsChart = null;

// Search & Filter Setup Screen
let currentSearchQuery = "";

// Helper: Distance in meters
function distanceM(p1, p2) {
    const dx = (p1[0] - p2[0]) * LON_DEG_TO_M;
    const dy = (p1[1] - p2[1]) * LAT_DEG_TO_M;
    return Math.hypot(dx, dy);
}

// Simple Priority Queue for Dijkstra
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

// Parse CSV Helper
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
    
    // Add default layers to map
    floorLayers["1"].addTo(map);
    panelLayer.addTo(map);
    coneLayer.addTo(map);
    
    // Ensure Leaflet layout updates sizes correctly
    setTimeout(() => {
        map.invalidateSize();
    }, 200);
}

// Load and Render Westfield Newmarket GeoJSON layouts
function loadGeoJSON() {
    console.log("Fetching mall topology GeoJSON...");
    return fetch('Westfield_NewMarket_topology_4326.geojson')
        .then(response => {
            if (!response.ok) {
                throw new Error(`Failed to load GeoJSON topology: HTTP ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            geojsonData = data;
            console.log(`Loaded GeoJSON topology. Total features: ${data.features ? data.features.length : 0}`);
            
            L.geoJSON(geojsonData, {
                pointToLayer: function(feature, latlng) {
                    // Render Point features (entrances/exits) as small circle markers to bypass CDN marker image loading issues
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
                            fillColor: '#334155', // slate-700 for distinct contrast
                            fillOpacity: 0.35,
                            color: 'rgba(255, 255, 255, 0.12)',
                            weight: 1,
                            dashArray: '3, 5'
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
                            weight: 1.5
                        };
                    } else {
                        // Regular shop: beautiful premium glowing design
                        return {
                            fillColor: '#0f172a', // slate-900 (deep dark blue-grey)
                            fillOpacity: 0.75,
                            color: 'rgba(99, 102, 241, 0.35)', // Sleek Indigo border (high contrast & premium look)
                            weight: 1.2
                        };
                    }
                },
                onEachFeature: function(feature, layer) {
                    const props = feature.properties || {};
                    const level = props.level || "1";
                    
                    // Bind tooltips for shop names
                    if (props.name && props.indoor === "room") {
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
                map.fitBounds(bounds, { padding: [10, 10] });
            }
        })
        .catch(err => {
            console.error("Error rendering GeoJSON:", err);
            throw err;
        });
}

// Load Network Graph and build connectivity lists
function loadGraph() {
    console.log("Fetching newmarket network graph JSON...");
    return fetch('newmarket_graph.json')
        .then(response => {
            if (!response.ok) {
                throw new Error(`Failed to load graph JSON: HTTP ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            graphData = data;
            console.log(`Loaded network graph. Nodes: ${data.nodes.length}, Edges: ${data.edges.length}`);
            
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
            
            renderGraphOverlay();
        })
        .catch(err => {
            console.error("Error loading network graph:", err);
            throw err;
        });
}

// Draw the network graph links faintly on the map
function renderGraphOverlay() {
    if (typeof L === 'undefined' || !map) return;
    graphLayer.clearLayers();
    if (!graphData) return;
    
    graphData.edges.forEach(edge => {
        const sNode = nodesMap[edge.source];
        const tNode = nodesMap[edge.target];
        if (!sNode || !tNode) return;
        
        const isTransit = sNode.level !== tNode.level;
        const matchesLevel = sNode.level === activeFloor || tNode.level === activeFloor;
        
        if (matchesLevel) {
            const color = isTransit ? '#c084fc' : '#8b5cf6';
            const weight = isTransit ? 1.5 : 0.8;
            const dashArray = isTransit ? '3, 5' : '1';
            const opacity = isTransit ? 0.5 : 0.12;
            
            const line = L.polyline(
                [[sNode.y, sNode.x], [tNode.y, tNode.x]],
                { color: color, weight: weight, opacity: opacity, dashArray: dashArray }
            );
            graphLayer.addLayer(line);
        }
    });
    
    if (showGraph) {
        if (!map.hasLayer(graphLayer)) map.addLayer(graphLayer);
    } else {
        if (map.hasLayer(graphLayer)) map.removeLayer(graphLayer);
    }
}

// Load panel locations from CSV
function loadPanels() {
    console.log("Fetching panel locations CSV...");
    return fetch('panel_locations_with_floor.csv')
        .then(response => {
            if (!response.ok) {
                throw new Error(`Failed to load panels CSV: HTTP ${response.status}`);
            }
            return response.text();
        })
        .then(csvText => {
            const parsed = parseCSV(csvText);
            panels = parsed.map(row => ({
                id: row.panel_id,
                name: `Panel ${row.panel_id}`,
                lon: parseFloat(row.longitude),
                lat: parseFloat(row.latitude),
                floor: row.floor.trim(),
                orientation: parseFloat(row.orientation),
                crossedAgents: new Set(),
                marker: null
            }));
            console.log(`Loaded ${panels.length} panels from CSV.`);
            renderPanelsSelectionGrid();
            renderPanelMarkers();
            renderPanelCones();
            populateComparisonDropdowns();
        })
        .catch(err => {
            console.error("Error loading CSV panels:", err);
            throw err;
        });
}

// Draw panel markers on Leaflet map
function renderPanelMarkers() {
    if (typeof L === 'undefined' || !map) return;
    panelLayer.clearLayers();
    
    panels.forEach(panel => {
        // Check checkbox state (setup selection or results screen selection)
        const isChecked = document.getElementById(`chk-result-${panel.id}`)?.checked ?? document.getElementById(`chk-${panel.id}`)?.checked ?? true;
        
        // Custom HTML Icon
        const customIcon = L.divIcon({
            html: `<div class="panel-marker-inner ${isChecked ? '' : 'inactive-marker'}" id="marker-inner-${panel.id}"></div>`,
            className: 'panel-map-marker',
            iconSize: [16, 16]
        });
        
        const marker = L.marker([panel.lat, panel.lon], { icon: customIcon });
        
        // Tooltip text
        let tooltipContent = `<b>${panel.name}</b><br>Floor: L${panel.floor}<br>Orient: ${panel.orientation}°`;
        if (panel.crossedAgents.size > 0) {
            tooltipContent += `<br>Unique Crossed: <b>${panel.crossedAgents.size.toLocaleString()}</b>`;
        }
        
        // If a reference panel is selected, append similarity details to tooltip
        if (selectedReferencePanel) {
            if (panel.id === selectedReferencePanel.id) {
                tooltipContent += `<br><strong style="color: #fbbf24;">(Selected Reference Panel)</strong>`;
            } else if (panel.crossedAgents.size > 0 || selectedReferencePanel.crossedAgents.size > 0) {
                const score = getPanelSimilarity(selectedReferencePanel, panel, selectedSimilarityMetric);
                let formattedScore = "";
                if (selectedSimilarityMetric === "jaccard") {
                    formattedScore = `${(score * 100).toFixed(1)}% (Jaccard)`;
                } else if (selectedSimilarityMetric === "cosine") {
                    formattedScore = `${(score * 100).toFixed(1)}% (Cosine)`;
                } else {
                    formattedScore = `${score.toLocaleString()} agents (Overlap)`;
                }
                tooltipContent += `<br><span style="color: #c084fc; font-weight: 600;">Similarity: ${formattedScore}</span>`;
            }
        }
        
        marker.bindTooltip(tooltipContent, { direction: 'top' });
        
        // Map click selecting reference
        marker.on('click', () => {
            selectReferencePanel(panel.id);
        });
        
        // Keep similarity colors updated when marker is re-added
        marker.on('add', () => {
            setTimeout(() => {
                updateMapSimilarityColoring();
            }, 0);
        });
        
        panel.marker = marker;
        
        // Show marker only if on active floor
        if (panel.floor === activeFloor) {
            panelLayer.addLayer(marker);
        }
    });
}

// Draw the visual viewing corridor wedges (L.polygon sectors) on the Leaflet map
function renderPanelCones() {
    if (typeof L === 'undefined' || !map) return;
    coneLayer.clearLayers();
    
    panels.forEach(panel => {
        if (panel.floor !== activeFloor) return;
        
        const isChecked = document.getElementById(`chk-result-${panel.id}`)?.checked ?? document.getElementById(`chk-${panel.id}`)?.checked ?? true;
        if (!isChecked) return; // Hide cone if panel is unselected
        
        const centerLat = panel.lat;
        const centerLon = panel.lon;
        const orient = panel.orientation;
        
        // Generate wedge vertices starting with center point
        const points = [[centerLat, centerLon]];
        
        const startAngle = orient - viewingConeAngle;
        const endAngle = orient + viewingConeAngle;
        
        // Sample every 5 degrees for a smooth arc
        for (let a = startAngle; a <= endAngle; a += 5) {
            const aRad = (a * Math.PI) / 180.0;
            const latOffset = (maxViewingDistance * Math.cos(aRad)) / LAT_DEG_TO_M;
            const lonOffset = (maxViewingDistance * Math.sin(aRad)) / LON_DEG_TO_M;
            points.push([centerLat + latOffset, centerLon + lonOffset]);
        }
        
        // Close the wedge polygon
        points.push([centerLat, centerLon]);
        
        // Determine color based on similarity if a reference panel is selected
        let coneColor = '#ec4899'; // default pink
        let coneFillOpacity = 0.08;
        let coneColorBorder = 'rgba(236, 72, 153, 0.35)';
        
        if (selectedReferencePanel) {
            if (panel.id === selectedReferencePanel.id) {
                coneColor = '#fbbf24'; // gold
                coneFillOpacity = 0.25;
                coneColorBorder = 'rgba(251, 191, 36, 0.6)';
            } else {
                const score = getPanelSimilarity(selectedReferencePanel, panel, selectedSimilarityMetric);
                const normalized = normalizeScore(score, selectedSimilarityMetric, selectedReferencePanel);
                
                if (normalized > 0.0001) {
                    const rgb = getSimilarityColor(normalized);
                    coneColor = rgb;
                    coneFillOpacity = 0.05 + 0.25 * normalized; // higher opacity for higher similarity
                    coneColorBorder = rgb.replace("rgb", "rgba").replace(")", ", 0.5)");
                } else {
                    coneColor = '#4b5563'; // neutral grey for 0 similarity
                    coneFillOpacity = 0.02;
                    coneColorBorder = 'rgba(75, 85, 99, 0.2)';
                }
            }
        }
        
        const wedge = L.polygon(points, {
            color: coneColorBorder,
            weight: 1,
            fillColor: coneColor,
            fillOpacity: coneFillOpacity,
            interactive: false
        });
        
        coneLayer.addLayer(wedge);
    });
}

// Refresh panel markers and cones visual layout
function updatePanelMapVisuals() {
    if (typeof L === 'undefined' || !map) return;
    renderPanelMarkers();
    renderPanelCones();
}

// Run Dijkstra to find shortest path distances/prev nodes from a start node to all nodes
function dijkstraAll(startNodeId) {
    const dist = {};
    const prev = {};
    const queue = new PriorityQueue();
    
    for (const nodeId in nodesMap) {
        dist[nodeId] = Infinity;
        prev[nodeId] = null;
    }
    dist[startNodeId] = 0;
    queue.enqueue(startNodeId, 0);
    
    while (!queue.isEmpty()) {
        const u = queue.dequeue();
        const uDist = dist[u];
        
        const neighbors = adjacencyList[u];
        if (!neighbors) continue;
        
        for (const edge of neighbors) {
            const v = edge.target;
            const alt = uDist + edge.weight;
            if (alt < dist[v]) {
                dist[v] = alt;
                prev[v] = u;
                queue.enqueue(v, alt);
            }
        }
    }
    
    // Reconstruct paths for all nodes
    const paths = {};
    for (const targetNodeId in nodesMap) {
        const path = [];
        let curr = targetNodeId;
        if (prev[curr] !== null || curr === startNodeId) {
            while (curr !== null) {
                path.unshift(curr);
                curr = prev[curr];
            }
        }
        paths[targetNodeId] = path;
    }
    
    return { distances: dist, paths: paths };
}

// Precompute paths and distances between all entrance & shop decision nodes
function precomputePaths() {
    const decisionNodes = Object.values(nodesMap).filter(n => n.type === "mall_entrance" || n.type === "shop_entry");
    
    decisionNodes.forEach(node => {
        const result = dijkstraAll(node.id);
        distanceMatrix[node.id] = result.distances;
        pathCache[node.id] = result.paths;
    });
    console.log(`Precomputed shortest paths for ${decisionNodes.length} source nodes.`);
}

// Get store category helper
function getStoreCategory(name) {
    if (!name) return "specialty";
    const nameLower = name.toLowerCase();
    
    if (nameLower.includes("farmers")) return "farmers";
    if (nameLower.includes("davidjones") || nameLower.includes("david jones")) return "davidjones";
    if (nameLower.includes("handm") || nameLower.includes("h&m") || nameLower.includes("hm")) return "hm";
    if (nameLower.includes("woolworths") || nameLower.includes("countdown")) return "woolworths";
    if (nameLower.includes("jbhifi") || nameLower.includes("jb hifi") || nameLower.includes("jb hi-fi") || nameLower.includes("jb_hifi")) return "jbhifi";
    if (nameLower.includes("food_court") || nameLower.includes("foodcourt")) return "foodcourt";
    if (nameLower.includes("noelleeming") || nameLower.includes("noel leeming") || nameLower.includes("noel_leeming")) return "noelleeming";
    if (nameLower.includes("archiebrothers") || nameLower.includes("archie brothers") || nameLower.includes("archie_brothers")) return "archiebrothers";
    if (nameLower.includes("rebelsport") || nameLower.includes("rebel sport") || nameLower.includes("rebel_sport")) return "rebelsport";
    
    return "specialty";
}

// Select target destination shop based on Huff's Gravity Model using precomputed graph distance
function selectNextShopGravity(currentNodeId, lastVisitedShopId) {
    const shopNodes = Object.values(nodesMap).filter(n => n.type === "shop_entry");
    if (shopNodes.length === 0) return null;
    
    const candidates = [];
    let totalWeight = 0;
    
    shopNodes.forEach(node => {
        if (node.id === lastVisitedShopId) return;
        
        const cat = getStoreCategory(node.name);
        let baseWt = categoryWeights[cat] || 0.3;
        baseWt = Math.max(0.001, baseWt); 
        
        let dist = distanceMatrix[currentNodeId][node.id];
        
        if (dist === undefined || dist === Infinity) {
            return;
        }
        
        const distFactor = Math.max(2.0, dist);
        const wt = baseWt / Math.pow(distFactor, decayExponent);
        
        candidates.push({ node, weight: wt });
        totalWeight += wt;
    });
    
    if (totalWeight === 0) return shopNodes[Math.floor(Math.random() * shopNodes.length)];
    
    let r = Math.random() * totalWeight;
    for (const cand of candidates) {
        r -= cand.weight;
        if (r <= 0) return cand.node;
    }
    
    return candidates[candidates.length - 1].node;
}

// Check if agent crosses a panel at (x, y) along a segment
function checkPanelCrossing(x, y, floor, n1, n2, agentId, activePanelIds) {
    const sameFloorPanels = panels.filter(p => p.floor === floor);
    
    sameFloorPanels.forEach(panel => {
        if (!activePanelIds.has(panel.id)) return;
        if (panel.crossedAgents.has(agentId)) return;
        
        // 1. Distance check
        const dx = (x - panel.lon) * LON_DEG_TO_M;
        const dy = (y - panel.lat) * LAT_DEG_TO_M;
        const dist = Math.hypot(dx, dy);
        
        if (dist > maxViewingDistance) return; 
        
        // 2. Position angle check
        const thetaRad = (panel.orientation * Math.PI) / 180.0;
        const panelNormalX = Math.sin(thetaRad);
        const panelNormalY = Math.cos(thetaRad);
        
        const p2aX = dx / dist;
        const p2aY = dy / dist;
        
        const dotProductPosition = p2aX * panelNormalX + p2aY * panelNormalY;
        const cosCone = Math.cos((viewingConeAngle * Math.PI) / 180.0);
        
        if (dotProductPosition < cosCone) return; 
        
        // 3. Heading check
        const hx = (n2.x - n1.x) * LON_DEG_TO_M;
        const hy = (n2.y - n1.y) * LAT_DEG_TO_M;
        const headingDist = Math.hypot(hx, hy);
        
        if (headingDist > 0.0001) { 
            const headingX = hx / headingDist;
            const headingY = hy / headingDist;
            
            const a2pX = -p2aX;
            const a2pY = -p2aY;
            
            const dotProductHeading = headingX * a2pX + headingY * a2pY;
            if (dotProductHeading < cosCone) return; 
        }
        
        // Detected! Register crossing
        panel.crossedAgents.add(agentId);
        floorDetections[floor].add(agentId);
    });
}

// Simulate a single agent from start to exit
function simulateAgent(agentIndex, activePanelIds) {
    const agentId = `agent_${agentIndex}`;
    
    // Spawn
    const spawnNodes = Object.values(nodesMap).filter(n => n.type === "mall_entrance");
    const startNode = spawnNodes[Math.floor(Math.random() * spawnNodes.length)];
    
    let currentNodeId = startNode.id;
    let lastVisitedShopId = null;
    
    const visitsCount = minShopVisits + Math.floor(Math.random() * (maxShopVisits - minShopVisits + 1));
    let totalDistTraveled = 0;
    
    // Visits
    for (let v = 0; v < visitsCount; v++) {
        const targetShop = selectNextShopGravity(currentNodeId, lastVisitedShopId);
        if (!targetShop) break;
        
        const path = pathCache[currentNodeId][targetShop.id];
        if (!path || path.length <= 1) {
            currentNodeId = targetShop.id;
            lastVisitedShopId = targetShop.id;
            continue;
        }
        
        const cat = getStoreCategory(targetShop.name);
        shopCategoryVisits[cat]++;
        
        for (let i = 0; i < path.length - 1; i++) {
            const uId = path[i];
            const vId = path[i + 1];
            const n1 = nodesMap[uId];
            const n2 = nodesMap[vId];
            
            const segmentDist = distanceM([n1.x, n1.y], [n2.x, n2.y]);
            totalDistTraveled += segmentDist;
            
            const stepMeters = 1.0;
            const numSteps = Math.max(1, Math.floor(segmentDist / stepMeters));
            
            for (let s = 0; s <= numSteps; s++) {
                const t = s / numSteps;
                const x = n1.x + t * (n2.x - n1.x);
                const y = n1.y + t * (n2.y - n1.y);
                
                checkPanelCrossing(x, y, n1.level, n1, n2, agentId, activePanelIds);
            }
        }
        
        currentNodeId = targetShop.id;
        lastVisitedShopId = targetShop.id;
    }
    
    // Exit
    const exitNodes = Object.values(nodesMap).filter(n => n.type === "mall_entrance");
    const exitNode = exitNodes[Math.floor(Math.random() * exitNodes.length)];
    
    const pathExit = pathCache[currentNodeId][exitNode.id];
    if (pathExit && pathExit.length > 1) {
        for (let i = 0; i < pathExit.length - 1; i++) {
            const uId = pathExit[i];
            const vId = pathExit[i + 1];
            const n1 = nodesMap[uId];
            const n2 = nodesMap[vId];
            
            const segmentDist = distanceM([n1.x, n1.y], [n2.x, n2.y]);
            totalDistTraveled += segmentDist;
            
            const stepMeters = 1.0;
            const numSteps = Math.max(1, Math.floor(segmentDist / stepMeters));
            
            for (let s = 0; s <= numSteps; s++) {
                const t = s / numSteps;
                const x = n1.x + t * (n2.x - n1.x);
                const y = n1.y + t * (n2.y - n1.y);
                
                checkPanelCrossing(x, y, n1.level, n1, n2, agentId, activePanelIds);
            }
        }
    }
    
    return {
        id: agentId,
        distance: totalDistTraveled,
        visits: visitsCount
    };
}

// Execute the simulation using frame-by-frame batching
function runSimulation() {
    readUIParameters();
    
    setUIControlsState(true);
    
    // Switch Inner Cards visible layout
    document.getElementById("state-setup-stats").style.display = "none";
    document.getElementById("state-setup-list").style.display = "none";
    document.getElementById("state-results-summary").style.display = "none";
    document.getElementById("state-results-details").style.display = "none";
    document.getElementById("state-running").style.display = "flex";
    
    // Reset stats
    panels.forEach(p => p.crossedAgents.clear());
    simulatedAgentsData = [];
    for (const cat in shopCategoryVisits) {
        shopCategoryVisits[cat] = 0;
    }
    floorDetections["1"].clear();
    floorDetections["2"].clear();
    floorDetections["3"].clear();
    
    // Build active panels set
    const activePanelIds = new Set();
    panels.forEach(p => {
        const checkbox = document.getElementById(`chk-${p.id}`);
        if (checkbox && checkbox.checked) {
            activePanelIds.add(p.id);
        }
    });
    
    let currentAgentCount = 0;
    const batchSize = 1500; 
    const startTime = performance.now();
    
    const circle = document.getElementById("running-progress-circle");
    const radius = circle.r.baseVal.value;
    const circumference = radius * 2 * Math.PI;
    circle.style.strokeDasharray = `${circumference} ${circumference}`;
    
    function setProgress(percent) {
        const offset = circumference - (percent / 100) * circumference;
        circle.style.strokeDashoffset = offset;
        document.getElementById("running-progress-percent").textContent = `${Math.round(percent)}%`;
    }
    
    document.getElementById("running-status-text").textContent = "Preparing pedestrian graphs...";
    setProgress(0);
    
    setTimeout(() => {
        if (Object.keys(distanceMatrix).length === 0) {
            precomputePaths();
        }
        
        document.getElementById("running-status-text").textContent = "Simulating gravity choices...";
        
        function processBatch() {
            const startBatchIndex = currentAgentCount;
            const endBatchIndex = Math.min(totalAgentsToSimulate, startBatchIndex + batchSize);
            
            for (let i = startBatchIndex; i < endBatchIndex; i++) {
                const data = simulateAgent(i + 1, activePanelIds);
                simulatedAgentsData.push(data);
            }
            
            currentAgentCount = endBatchIndex;
            const percent = (currentAgentCount / totalAgentsToSimulate) * 100;
            setProgress(percent);
            document.getElementById("running-substats").textContent = `Simulated: ${currentAgentCount.toLocaleString()} / ${totalAgentsToSimulate.toLocaleString()}`;
            
            if (currentAgentCount < totalAgentsToSimulate) {
                requestAnimationFrame(processBatch);
            } else {
                // Completed!
                const endTime = performance.now();
                const elapsedTimeMs = Math.round(endTime - startTime);
                
                // Show completed state cards
                document.getElementById("state-running").style.display = "none";
                document.getElementById("state-results-summary").style.display = "flex";
                document.getElementById("state-results-details").style.display = "block";
                
                // Populate stats
                renderResultsMetrics(elapsedTimeMs);
                renderCharts();
                renderLeaderboardTable();
                
                // Populate dropdown lists and refresh similarity values
                populateComparisonDropdowns();
                updateDetailedComparison();
                updateReferencePanelUI();
                
                // Refresh Map Visual overlays with counts in tooltips
                updatePanelMapVisuals();
                
                // Re-enable inputs
                setUIControlsState(false);
                document.getElementById("btn-reset").removeAttribute("disabled");
            }
        }
        
        requestAnimationFrame(processBatch);
    }, 100);
}

// Read parameters from sliders/inputs
function readUIParameters() {
    totalAgentsToSimulate = parseInt(document.getElementById("input-total-agents").value);
    minShopVisits = parseInt(document.getElementById("input-min-visits").value);
    maxShopVisits = parseInt(document.getElementById("input-max-visits").value);
    baseWalkSpeedMS = parseFloat(document.getElementById("input-walk-speed").value);
    decayExponent = parseFloat(document.getElementById("input-decay-exponent").value);
    maxViewingDistance = parseFloat(document.getElementById("input-view-dist").value);
    viewingConeAngle = parseFloat(document.getElementById("input-cone-angle").value);
    
    // Attractiveness weights
    categoryWeights.farmers = parseInt(document.getElementById("wt-farmers").value) / 100.0;
    categoryWeights.davidjones = parseInt(document.getElementById("wt-davidjones").value) / 100.0;
    categoryWeights.hm = parseInt(document.getElementById("wt-hm").value) / 100.0;
    categoryWeights.woolworths = parseInt(document.getElementById("wt-woolworths").value) / 100.0;
    categoryWeights.jbhifi = parseInt(document.getElementById("wt-jbhifi").value) / 100.0;
    categoryWeights.foodcourt = parseInt(document.getElementById("wt-foodcourt").value) / 100.0;
    categoryWeights.noelleeming = parseInt(document.getElementById("wt-noelleeming").value) / 100.0;
    categoryWeights.archiebrothers = parseInt(document.getElementById("wt-archiebrothers").value) / 100.0;
    categoryWeights.rebelsport = parseInt(document.getElementById("wt-rebelsport").value) / 100.0;
    categoryWeights.specialty = parseInt(document.getElementById("wt-specialty").value) / 100.0;
}

// Enable/Disable side controls
function setUIControlsState(disabled) {
    const inputs = document.querySelectorAll(".sidebar input, .sidebar button");
    inputs.forEach(el => {
        if (el.id === "btn-reset") return; 
        if (disabled) {
            el.setAttribute("disabled", "true");
        } else {
            el.removeAttribute("disabled");
        }
    });
}

// Render summary cards in results view
function renderResultsMetrics(elapsedTimeMs) {
    document.getElementById("res-total-agents").textContent = totalAgentsToSimulate.toLocaleString();
    
    let totalDetections = 0;
    panels.forEach(p => {
        const isChecked = document.getElementById(`chk-result-${p.id}`)?.checked ?? document.getElementById(`chk-${p.id}`)?.checked ?? true;
        if (isChecked) {
            totalDetections += p.crossedAgents.size;
        }
    });
    document.getElementById("res-total-crossings").textContent = totalDetections.toLocaleString();
    
    recalculateCoverage();
    
    const speedThroughput = Math.round(totalAgentsToSimulate / (elapsedTimeMs / 1000.0));
    document.getElementById("res-speed-throughput").textContent = `${speedThroughput.toLocaleString()} agents/s`;
    document.getElementById("res-elapsed-time").textContent = `${elapsedTimeMs.toLocaleString()}ms`;
}

// Recalculate unique agents crossed and update coverage text (Results Screen)
function recalculateCoverage() {
    const uniqueAgents = new Set();
    let totalDetections = 0;
    
    panels.forEach(p => {
        const checkbox = document.getElementById(`chk-result-${p.id}`);
        const isChecked = checkbox ? checkbox.checked : (document.getElementById(`chk-${p.id}`)?.checked ?? true);
        
        if (isChecked) {
            p.crossedAgents.forEach(agentId => {
                uniqueAgents.add(agentId);
            });
            totalDetections += p.crossedAgents.size;
        }
        
        const tr = document.getElementById(`row-${p.id}`);
        if (tr) {
            if (isChecked) {
                tr.classList.remove("inactive-row");
            } else {
                tr.classList.add("inactive-row");
            }
        }
    });
    
    document.getElementById("unique-cross-count").textContent = uniqueAgents.size.toLocaleString();
    document.getElementById("res-total-crossings").textContent = totalDetections.toLocaleString();
    
    const coveragePercent = ((uniqueAgents.size / totalAgentsToSimulate) * 100).toFixed(2);
    document.getElementById("coverage-rate").textContent = `${coveragePercent}%`;
}

// Draw Chart.js diagrams
function renderCharts() {
    if (typeof Chart === 'undefined') {
        const containers = document.querySelectorAll(".chart-container");
        containers.forEach(container => {
            if (!container.querySelector(".offline-chart-notice")) {
                container.innerHTML = `
                    <div class="offline-chart-notice" style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: #64748b; font-size: 11px; text-align: center; border: 1px dashed rgba(255,255,255,0.05); border-radius: 6px;">
                        <span>📊</span>
                        <p style="margin-top: 4px;">Charts offline (Chart.js CDN blocked)</p>
                    </div>
                `;
            }
        });
        return;
    }
    
    if (storeVisitsChart) storeVisitsChart.destroy();
    if (floorCrossingsChart) floorCrossingsChart.destroy();
    
    // Store category Chart
    const ctxStore = document.getElementById("chart-store-visits").getContext("2d");
    const categoryLabels = {
        farmers: "Farmers",
        davidjones: "David Jones",
        hm: "H&M",
        woolworths: "Woolworths",
        jbhifi: "JB Hi-Fi",
        foodcourt: "Food Court",
        noelleeming: "Noel Leeming",
        archiebrothers: "Archie Brothers",
        rebelsport: "Rebel Sport",
        specialty: "Specialty"
    };
    
    const labels = Object.keys(shopCategoryVisits).map(k => categoryLabels[k] || k);
    const dataVisits = Object.values(shopCategoryVisits);
    
    storeVisitsChart = new Chart(ctxStore, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Visits',
                data: dataVisits,
                backgroundColor: [
                    'rgba(6, 182, 212, 0.45)', // Farmers
                    'rgba(139, 92, 246, 0.45)', // David Jones
                    'rgba(236, 72, 153, 0.45)', // H&M
                    'rgba(16, 185, 129, 0.45)', // Woolworths
                    'rgba(245, 158, 11, 0.45)', // JB Hi-Fi
                    'rgba(239, 68, 68, 0.45)',  // Food Court
                    'rgba(14, 165, 233, 0.45)', // Noel Leeming
                    'rgba(244, 63, 94, 0.45)',  // Archie Brothers
                    'rgba(132, 204, 22, 0.45)', // Rebel Sport
                    'rgba(148, 163, 184, 0.45)' // Specialty
                ],
                borderColor: [
                    '#06b6d4',
                    '#8b5cf6',
                    '#ec4899',
                    '#10b981',
                    '#f59e0b',
                    '#ef4444',
                    '#0ea5e9',
                    '#f43f5e',
                    '#84cc16',
                    '#94a3b8'
                ],
                borderWidth: 1.5,
                borderRadius: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#0c111d',
                    titleColor: '#ffffff',
                    bodyColor: '#cbd5e1',
                    borderColor: 'rgba(255,255,255,0.08)',
                    borderWidth: 1,
                    padding: 8,
                    bodyFont: { family: 'Inter', size: 11 }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { color: '#64748b', font: { family: 'Inter', size: 10 } }
                },
                y: {
                    grid: { color: 'rgba(255, 255, 255, 0.03)' },
                    ticks: { color: '#64748b', font: { family: 'JetBrains Mono', size: 9 } }
                }
            }
        }
    });
    
    // Floor Doughnut chart
    const ctxFloor = document.getElementById("chart-floor-crossings").getContext("2d");
    const floorUniqueCounts = { "1": 0, "2": 0, "3": 0 };
    ["1", "2", "3"].forEach(f => {
        const floorAgents = new Set();
        panels.forEach(p => {
            if (p.floor === f) {
                const isChecked = document.getElementById(`chk-result-${p.id}`)?.checked ?? document.getElementById(`chk-${p.id}`)?.checked ?? true;
                if (isChecked) {
                    p.crossedAgents.forEach(aId => floorAgents.add(aId));
                }
            }
        });
        floorUniqueCounts[f] = floorAgents.size;
    });
    
    const floorLabels = ["Level 1", "Level 2", "Level 3"];
    const dataFloors = [floorUniqueCounts["1"], floorUniqueCounts["2"], floorUniqueCounts["3"]];
    
    floorCrossingsChart = new Chart(ctxFloor, {
        type: 'doughnut',
        data: {
            labels: floorLabels,
            datasets: [{
                data: dataFloors,
                backgroundColor: [
                    'rgba(59, 130, 246, 0.45)', // L1
                    'rgba(16, 185, 129, 0.45)', // L2
                    'rgba(245, 158, 11, 0.45)'  // L3
                ],
                borderColor: [
                    '#3b82f6',
                    '#10b981',
                    '#f59e0b'
                ],
                borderWidth: 1.5,
                hoverOffset: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        color: '#94a3b8',
                        font: { family: 'Inter', size: 10 },
                        padding: 10
                    }
                },
                tooltip: {
                    backgroundColor: '#0c111d',
                    titleColor: '#ffffff',
                    bodyColor: '#cbd5e1',
                    borderColor: 'rgba(255,255,255,0.08)',
                    borderWidth: 1,
                    padding: 8,
                    bodyFont: { family: 'Inter', size: 11 }
                }
            },
            cutout: '60%'
        }
    });
}

// Render Panel selection checklist in Setup view
function renderPanelsSelectionGrid() {
    const grid = document.getElementById("panels-selection-grid");
    grid.innerHTML = "";
    
    const filteredPanels = panels.filter(panel => {
        return panel.id.toLowerCase().includes(currentSearchQuery.toLowerCase()) || 
               panel.orientation.toString().includes(currentSearchQuery);
    });
    
    if (filteredPanels.length === 0) {
        grid.innerHTML = `<div class="loading-placeholder"><p>No panels match search.</p></div>`;
        return;
    }
    
    filteredPanels.forEach(panel => {
        const card = document.createElement("label");
        card.className = "panel-card-select";
        card.setAttribute("for", `chk-${panel.id}`);
        
        let flClass = "fl-1";
        if (panel.floor === "2") flClass = "fl-2";
        if (panel.floor === "3") flClass = "fl-3";
        
        card.innerHTML = `
            <input type="checkbox" id="chk-${panel.id}" checked />
            <div class="panel-card-info">
                <div class="panel-card-id">${panel.name}</div>
                <div class="panel-card-meta">
                    <span class="panel-card-floor-badge ${flClass}">L${panel.floor}</span> 
                    Orient: ${panel.orientation}°
                </div>
            </div>
        `;
        
        card.querySelector("input").addEventListener("change", () => {
            updateSelectedPanelsHeaderCount();
            updatePanelMapVisuals();
        });
        grid.appendChild(card);
    });
    
    updateSelectedPanelsHeaderCount();
}

// Update selected count indicator in setup card header
function updateSelectedPanelsHeaderCount() {
    let selected = 0;
    panels.forEach(p => {
        const chk = document.getElementById(`chk-${p.id}`);
        if (chk && chk.checked) selected++;
    });
    
    document.getElementById("panels-selected-count").textContent = selected;
    document.getElementById("panels-total-count").textContent = panels.length;
}

// Render sorted leaderboard table in Results view
function renderLeaderboardTable() {
    const tbody = document.getElementById("leaderboard-tbody");
    tbody.innerHTML = "";
    
    const searchVal = document.getElementById("leaderboard-search").value.toLowerCase();
    
    const sortedPanels = [...panels]
        .filter(p => p.id.toLowerCase().includes(searchVal) || p.floor.includes(searchVal))
        .sort((a, b) => b.crossedAgents.size - a.crossedAgents.size);
    
    if (sortedPanels.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" style="text-align:center; color:#64748b; padding:2rem;">No matching leaderboard rows.</td></tr>`;
        return;
    }
    
    sortedPanels.forEach((panel, index) => {
        const isChecked = document.getElementById(`chk-${panel.id}`)?.checked ?? true;
        const count = panel.crossedAgents.size;
        const percent = ((count / totalAgentsToSimulate) * 100).toFixed(2);
        
        let rankBadgeClass = "rank-badge";
        if (index === 0) rankBadgeClass += " top-1";
        else if (index === 1) rankBadgeClass += " top-2";
        else if (index === 2) rankBadgeClass += " top-3";
        
        const tr = document.createElement("tr");
        tr.id = `row-${panel.id}`;
        
        let trClass = "";
        if (!isChecked) trClass += "inactive-row ";
        if (selectedReferencePanel && selectedReferencePanel.id === panel.id) trClass += "reference-active";
        if (trClass) tr.className = trClass.trim();
        
        tr.innerHTML = `
            <td><div class="${rankBadgeClass}">${index + 1}</div></td>
            <td class="td-id">${panel.name}</td>
            <td>L${panel.floor}</td>
            <td>${panel.orientation}°</td>
            <td style="font-family: var(--font-mono); font-size:10px; color:#64748b;">
                ${panel.lat.toFixed(5)}, ${panel.lon.toFixed(5)}
            </td>
            <td class="td-checkbox-center">
                <input type="checkbox" id="chk-result-${panel.id}" ${isChecked ? 'checked' : ''} />
            </td>
            <td style="text-align: right; font-weight:700; font-family: var(--font-mono);" class="neon-cyan">
                ${count.toLocaleString()}
            </td>
            <td>
                <div class="exposure-bar-container">
                    <span class="exposure-percent-val">${percent}%</span>
                    <div class="exposure-bar-bg">
                        <div class="exposure-bar-fill" style="width: ${percent}%;"></div>
                    </div>
                </div>
            </td>
        `;
        
        const checkbox = tr.querySelector(`#chk-result-${panel.id}`);
        checkbox.addEventListener("change", () => {
            // Sync setup checkbox
            const setupChk = document.getElementById(`chk-${panel.id}`);
            if (setupChk) setupChk.checked = checkbox.checked;
            
            recalculateCoverage();
            renderCharts();
            updatePanelMapVisuals();
            updateSelectedPanelsHeaderCount();
        });
        
        // Select as reference on row click (if checkbox is not clicked)
        tr.addEventListener("click", (e) => {
            if (e.target.tagName === "INPUT" && e.target.type === "checkbox") {
                return;
            }
            selectReferencePanel(panel.id);
        });
        
        tbody.appendChild(tr);
    });
}

// Export Panel scores and metrics to CSV
function exportPanelScoresToCSV() {
    if (!panels || panels.length === 0) return;
    
    const sortedPanels = [...panels].sort((a, b) => b.crossedAgents.size - a.crossedAgents.size);
    const activePanelsCount = panels.filter(p => document.getElementById(`chk-${p.id}`)?.checked).length;
    
    const metadata = [
        `# Westfield Newmarket Pedestrian Gravity Simulation Portal - Panel Scores Report`,
        `# Export Timestamp: ${new Date().toISOString()}`,
        `#`,
        `# --- SIMULATION CONFIGURATION PARAMETERS ---`,
        `# Total Agents: ${totalAgentsToSimulate.toLocaleString()}`,
        `# Min Shop Visits: ${minShopVisits}`,
        `# Max Shop Visits: ${maxShopVisits}`,
        `# Base Walking Speed (m/s): ${baseWalkSpeedMS}`,
        `# Huff Decay Exponent (alpha): ${decayExponent}`,
        `# Max Viewing Distance (m): ${maxViewingDistance}`,
        `# Viewing Cone Angle: ${viewingConeAngle}°`,
        `# Active Sensors: ${activePanelsCount} / ${panels.length}`,
        `# Store Category Weights: ${JSON.stringify(categoryWeights)}`,
        `# -------------------------------------------`,
        `#`
    ];
    
    const headers = [
        "Rank",
        "Panel ID",
        "Floor",
        "Orientation",
        "Latitude",
        "Longitude",
        "Active",
        "Unique Crossed",
        "Exposure Efficiency (%)"
    ];
    
    const rows = sortedPanels.map((panel, index) => {
        const isChecked = document.getElementById(`chk-result-${panel.id}`)?.checked ?? true;
        const count = panel.crossedAgents.size;
        const percent = ((count / totalAgentsToSimulate) * 100).toFixed(2);
        
        return [
            index + 1,
            `"${panel.name}"`,
            `"L${panel.floor}"`,
            `${panel.orientation}`,
            `${panel.lat}`,
            `${panel.lon}`,
            `"${isChecked ? 'Yes' : 'No'}"`,
            `${count}`,
            `${percent}`
        ];
    });
    
    const csvContent = metadata.concat([headers.join(",")])
                               .concat(rows.map(row => row.join(",")))
                               .join("\n");
    
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    
    const dateStr = new Date().toISOString().slice(0, 10);
    const timeStr = new Date().toTimeString().slice(0, 8).replace(/:/g, "-");
    link.setAttribute("download", `westfield_newmarket_panel_scores_${dateStr}_${timeStr}.csv`);
    
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// Bind UI controls and events
function bindUIControls() {
    // Sliders & inputs
    const sAgents = document.getElementById("input-total-agents");
    sAgents.addEventListener("input", () => {
        document.getElementById("val-total-agents").textContent = parseInt(sAgents.value).toLocaleString();
    });
    
    const sMin = document.getElementById("input-min-visits");
    sMin.addEventListener("input", () => {
        const val = parseInt(sMin.value);
        document.getElementById("val-min-visits").textContent = val;
        const sMax = document.getElementById("input-max-visits");
        if (parseInt(sMax.value) < val) {
            sMax.value = val;
            document.getElementById("val-max-visits").textContent = val;
        }
    });
    
    const sMax = document.getElementById("input-max-visits");
    sMax.addEventListener("input", () => {
        const val = parseInt(sMax.value);
        document.getElementById("val-max-visits").textContent = val;
        const sMin = document.getElementById("input-min-visits");
        if (parseInt(sMin.value) > val) {
            sMin.value = val;
            document.getElementById("val-min-visits").textContent = val;
        }
    });
    
    const sSpeed = document.getElementById("input-walk-speed");
    sSpeed.addEventListener("input", () => {
        document.getElementById("val-walk-speed").textContent = `${parseFloat(sSpeed.value).toFixed(1)} m/s`;
    });
    
    const sDecay = document.getElementById("input-decay-exponent");
    sDecay.addEventListener("input", () => {
        document.getElementById("val-decay-exponent").textContent = parseFloat(sDecay.value).toFixed(1);
    });
    
    const sViewDist = document.getElementById("input-view-dist");
    sViewDist.addEventListener("input", () => {
        document.getElementById("val-view-dist").textContent = `${parseFloat(sViewDist.value)}m`;
        renderPanelCones();
    });
    
    const sConeAngle = document.getElementById("input-cone-angle");
    sConeAngle.addEventListener("input", () => {
        document.getElementById("val-cone-angle").textContent = `${parseFloat(sConeAngle.value)}°`;
        renderPanelCones();
    });
    
    // Graph switch
    const chkGraph = document.getElementById("chk-show-graph");
    chkGraph.addEventListener("change", () => {
        showGraph = chkGraph.checked;
        renderGraphOverlay();
    });
    
    // Shop Weights attractiveness sync
    const wtSliders = [
        { id: "wt-farmers", labelId: "val-wt-farmers" },
        { id: "wt-davidjones", labelId: "val-wt-davidjones" },
        { id: "wt-hm", labelId: "val-wt-hm" },
        { id: "wt-woolworths", labelId: "val-wt-woolworths" },
        { id: "wt-jbhifi", labelId: "val-wt-jbhifi" },
        { id: "wt-foodcourt", labelId: "val-wt-foodcourt" },
        { id: "wt-noelleeming", labelId: "val-wt-noelleeming" },
        { id: "wt-archiebrothers", labelId: "val-wt-archiebrothers" },
        { id: "wt-rebelsport", labelId: "val-wt-rebelsport" },
        { id: "wt-specialty", labelId: "val-wt-specialty" }
    ];
    wtSliders.forEach(slider => {
        const el = document.getElementById(slider.id);
        el.addEventListener("input", () => {
            document.getElementById(slider.labelId).textContent = `${el.value}%`;
        });
    });
    
    // Panel Search
    const panelSearch = document.getElementById("panel-search");
    panelSearch.addEventListener("input", () => {
        currentSearchQuery = panelSearch.value;
        renderPanelsSelectionGrid();
    });
    
    // Bulk actions
    document.getElementById("btn-select-all").addEventListener("click", () => {
        panels.forEach(p => {
            const chk = document.getElementById(`chk-${p.id}`);
            if (chk) chk.checked = true;
        });
        updateSelectedPanelsHeaderCount();
        updatePanelMapVisuals();
    });
    
    document.getElementById("btn-select-none").addEventListener("click", () => {
        panels.forEach(p => {
            const chk = document.getElementById(`chk-${p.id}`);
            if (chk) chk.checked = false;
        });
        updateSelectedPanelsHeaderCount();
        updatePanelMapVisuals();
    });
    
    // Floor-specific selectors
    document.getElementById("btn-select-fl1").addEventListener("click", () => {
        panels.forEach(p => {
            const chk = document.getElementById(`chk-${p.id}`);
            if (chk) chk.checked = (p.floor === "1");
        });
        updateSelectedPanelsHeaderCount();
        updatePanelMapVisuals();
    });
    document.getElementById("btn-select-fl2").addEventListener("click", () => {
        panels.forEach(p => {
            const chk = document.getElementById(`chk-${p.id}`);
            if (chk) chk.checked = (p.floor === "2");
        });
        updateSelectedPanelsHeaderCount();
        updatePanelMapVisuals();
    });
    document.getElementById("btn-select-fl3").addEventListener("click", () => {
        panels.forEach(p => {
            const chk = document.getElementById(`chk-${p.id}`);
            if (chk) chk.checked = (p.floor === "3");
        });
        updateSelectedPanelsHeaderCount();
        updatePanelMapVisuals();
    });
    
    // Map Floor Overlay Selector Buttons
    const mapFloorBtns = document.querySelectorAll(".floor-btn");
    mapFloorBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            mapFloorBtns.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            
            const prevFloor = activeFloor;
            activeFloor = btn.getAttribute("data-floor");
            
            // Toggle layer
            if (floorLayers[prevFloor]) map.removeLayer(floorLayers[prevFloor]);
            if (floorLayers[activeFloor]) map.addLayer(floorLayers[activeFloor]);
            
            renderGraphOverlay();
            renderPanelMarkers();
            renderPanelCones();
        });
    });
    
    // Run button
    document.getElementById("btn-run").addEventListener("click", runSimulation);
    
    // Reset button
    document.getElementById("btn-reset").addEventListener("click", () => {
        // Toggle card visual elements back
        document.getElementById("state-results-summary").style.display = "none";
        document.getElementById("state-results-details").style.display = "none";
        document.getElementById("state-setup-stats").style.display = "flex";
        document.getElementById("state-setup-list").style.display = "block";
        
        document.getElementById("btn-reset").setAttribute("disabled", "true");
        
        // Reset tabs
        const tabCoverage = document.getElementById("btn-tab-coverage");
        const tabSimilarity = document.getElementById("btn-tab-similarity");
        const contentCoverage = document.getElementById("tab-content-coverage");
        const contentSimilarity = document.getElementById("tab-content-similarity");
        if (tabCoverage && tabSimilarity) {
            tabCoverage.classList.add("active");
            tabSimilarity.classList.remove("active");
            contentCoverage.style.display = "block";
            contentSimilarity.style.display = "none";
        }
        
        // Clear similarity reference
        clearReferencePanel();
        const compA = document.getElementById("compare-panel-a");
        const compB = document.getElementById("compare-panel-b");
        if (compA) compA.value = "";
        if (compB) compB.value = "";
        updateDetailedComparison();
        
        // Clear counts
        panels.forEach(p => p.crossedAgents.clear());
        
        // Reset Visuals
        renderPanelsSelectionGrid();
        updatePanelMapVisuals();
    });
    
    // Leaderboard search
    const leadSearch = document.getElementById("leaderboard-search");
    leadSearch.addEventListener("input", renderLeaderboardTable);

    // Export CSV
    const btnExport = document.getElementById("btn-export-csv");
    if (btnExport) {
        btnExport.addEventListener("click", exportPanelScoresToCSV);
    }
    
    // Leaderboard bulk actions
    document.getElementById("btn-leaderboard-select-all").addEventListener("click", () => {
        panels.forEach(p => {
            const chk = document.getElementById(`chk-result-${p.id}`);
            if (chk) chk.checked = true;
            const setupChk = document.getElementById(`chk-${p.id}`);
            if (setupChk) setupChk.checked = true;
        });
        recalculateCoverage();
        renderCharts();
        updatePanelMapVisuals();
        updateSelectedPanelsHeaderCount();
    });
    
    document.getElementById("btn-leaderboard-select-none").addEventListener("click", () => {
        panels.forEach(p => {
            const chk = document.getElementById(`chk-result-${p.id}`);
            if (chk) chk.checked = false;
            const setupChk = document.getElementById(`chk-${p.id}`);
            if (setupChk) setupChk.checked = false;
        });
        recalculateCoverage();
        renderCharts();
        updatePanelMapVisuals();
        updateSelectedPanelsHeaderCount();
    });
    
    // Tab switching listeners
    const tabCoverage = document.getElementById("btn-tab-coverage");
    const tabSimilarity = document.getElementById("btn-tab-similarity");
    const contentCoverage = document.getElementById("tab-content-coverage");
    const contentSimilarity = document.getElementById("tab-content-similarity");
    
    if (tabCoverage && tabSimilarity) {
        tabCoverage.addEventListener("click", () => {
            tabCoverage.classList.add("active");
            tabSimilarity.classList.remove("active");
            contentCoverage.style.display = "block";
            contentSimilarity.style.display = "none";
        });
        
        tabSimilarity.addEventListener("click", () => {
            tabSimilarity.classList.add("active");
            tabCoverage.classList.remove("active");
            contentCoverage.style.display = "none";
            contentSimilarity.style.display = "flex";
        });
    }
    
    // Similarity metric change listener
    const metricSelect = document.getElementById("similarity-metric-select");
    if (metricSelect) {
        metricSelect.addEventListener("change", (e) => {
            selectedSimilarityMetric = e.target.value;
            updateMapSimilarityColoring();
            renderPanelCones();
        });
    }
    
    // Detailed Comparison dropdowns change listeners
    const compareA = document.getElementById("compare-panel-a");
    const compareB = document.getElementById("compare-panel-b");
    if (compareA) {
        compareA.addEventListener("change", () => {
            updateDetailedComparison();
        });
    }
    if (compareB) {
        compareB.addEventListener("change", () => {
            updateDetailedComparison();
        });
    }
    
    // JSON Profile Configuration Listeners
    const btnExportConfig = document.getElementById("btn-export-config");
    if (btnExportConfig) {
        btnExportConfig.addEventListener("click", exportConfigJSON);
    }
    
    const btnImportConfigTrigger = document.getElementById("btn-import-config-trigger");
    const fileInput = document.getElementById("input-import-config");
    if (btnImportConfigTrigger && fileInput) {
        btnImportConfigTrigger.addEventListener("click", () => {
            fileInput.click();
        });
        fileInput.addEventListener("change", importConfigJSON);
    }
    
    // Raw Vector Export Listener
    const btnExportVectors = document.getElementById("btn-export-vectors");
    if (btnExportVectors) {
        btnExportVectors.addEventListener("click", exportInteractionVectors);
    }
}

// Panel Similarity Helper Functions
function getPanelSimilarity(panelA, panelB, metricType) {
    const setA = panelA.crossedAgents;
    const setB = panelB.crossedAgents;
    
    if (setA.size === 0 && setB.size === 0) return 0;
    
    // Intersection size
    let intersectionSize = 0;
    if (setA.size < setB.size) {
        for (let agentId of setA) {
            if (setB.has(agentId)) intersectionSize++;
        }
    } else {
        for (let agentId of setB) {
            if (setA.has(agentId)) intersectionSize++;
        }
    }
    
    if (metricType === "jaccard") {
        const unionSize = setA.size + setB.size - intersectionSize;
        return unionSize === 0 ? 0 : intersectionSize / unionSize;
    } else if (metricType === "cosine") {
        const denom = Math.sqrt(setA.size * setB.size);
        return denom === 0 ? 0 : intersectionSize / denom;
    } else if (metricType === "overlap") {
        return intersectionSize;
    }
    return 0;
}

function normalizeScore(score, metricType, refPanel) {
    if (metricType === "overlap") {
        if (!refPanel || refPanel.crossedAgents.size === 0) return 0;
        return score / refPanel.crossedAgents.size;
    }
    return score;
}

function getSimilarityColor(score) {
    if (score <= 0.0001) {
        return "rgb(75, 85, 99)"; // neutral grey
    }
    const r = Math.round(99 + (236 - 99) * score);
    const g = Math.round(102 + (72 - 102) * score);
    const b = Math.round(241 + (153 - 241) * score);
    return `rgb(${r}, ${g}, ${b})`;
}

function updateMapSimilarityColoring() {
    panels.forEach(panel => {
        if (!panel.marker) return;
        
        const element = panel.marker.getElement();
        if (!element) return;
        
        const innerIcon = element.querySelector('.panel-marker-inner');
        if (!innerIcon) return;
        
        innerIcon.style.backgroundColor = "";
        innerIcon.style.boxShadow = "";
        innerIcon.style.border = "";
        innerIcon.classList.remove("reference-marker");
        
        let tooltipContent = `<b>${panel.name}</b><br>Floor: L${panel.floor}<br>Orient: ${panel.orientation}°<br>Unique Crossed: <b>${panel.crossedAgents.size.toLocaleString()}</b>`;
        
        if (selectedReferencePanel) {
            if (panel.id === selectedReferencePanel.id) {
                innerIcon.style.backgroundColor = "#fbbf24";
                innerIcon.style.boxShadow = "0 0 12px #fbbf24";
                innerIcon.style.border = "2px solid #ffffff";
                innerIcon.classList.add("reference-marker");
                tooltipContent += `<br><strong style="color: #fbbf24;">(Selected Reference Panel)</strong>`;
            } else {
                const score = getPanelSimilarity(selectedReferencePanel, panel, selectedSimilarityMetric);
                const normalized = normalizeScore(score, selectedSimilarityMetric, selectedReferencePanel);
                const color = getSimilarityColor(normalized);
                
                innerIcon.style.backgroundColor = color;
                innerIcon.style.boxShadow = `0 0 8px ${color}`;
                
                let formattedScore = "";
                if (selectedSimilarityMetric === "jaccard") {
                    formattedScore = `${(score * 100).toFixed(1)}% (Jaccard)`;
                } else if (selectedSimilarityMetric === "cosine") {
                    formattedScore = `${(score * 100).toFixed(1)}% (Cosine)`;
                } else {
                    formattedScore = `${score.toLocaleString()} agents (Overlap)`;
                }
                tooltipContent += `<br><span style="color: #c084fc; font-weight: 600;">Similarity: ${formattedScore}</span>`;
            }
        }
        
        panel.marker.setTooltipContent(tooltipContent);
    });
}

function selectReferencePanel(panelId) {
    const panel = panels.find(p => p.id === panelId);
    if (!panel) return;
    
    if (selectedReferencePanel && selectedReferencePanel.id === panelId) {
        clearReferencePanel();
        return;
    }
    
    selectedReferencePanel = panel;
    
    updateReferencePanelUI();
    updateMapSimilarityColoring();
    renderPanelCones();
    renderLeaderboardTable();
    
    const selectA = document.getElementById("compare-panel-a");
    if (selectA) {
        selectA.value = panelId;
        updateDetailedComparison();
    }
}

function clearReferencePanel() {
    selectedReferencePanel = null;
    
    updateReferencePanelUI();
    updateMapSimilarityColoring();
    renderPanelCones();
    renderLeaderboardTable();
}

function updateReferencePanelUI() {
    const el = document.getElementById("ref-panel-status");
    if (!el) return;
    
    if (selectedReferencePanel) {
        el.innerHTML = `
            <div class="ref-panel-details">
                <span class="ref-panel-label">Reference Panel (Panel A)</span>
                <span class="ref-panel-val">${selectedReferencePanel.id} (L${selectedReferencePanel.floor}) • ${selectedReferencePanel.crossedAgents.size.toLocaleString()} agents</span>
            </div>
            <button class="btn-clear-ref" id="btn-clear-reference">Clear</button>
        `;
        document.getElementById("btn-clear-reference").addEventListener("click", (e) => {
            e.stopPropagation();
            clearReferencePanel();
        });
    } else {
        el.innerHTML = `<span class="text-muted" style="font-size: 11px; text-align: center; width: 100%;">Click map sensor or row to select reference</span>`;
    }
}

function populateComparisonDropdowns() {
    const selectA = document.getElementById("compare-panel-a");
    const selectB = document.getElementById("compare-panel-b");
    
    if (!selectA || !selectB) return;
    
    const valA = selectA.value;
    const valB = selectB.value;
    
    selectA.innerHTML = '<option value="">Select Panel A</option>';
    selectB.innerHTML = '<option value="">Select Panel B</option>';
    
    const sortedPanels = [...panels].sort((a, b) => a.id.localeCompare(b.id));
    
    sortedPanels.forEach(panel => {
        const optA = document.createElement("option");
        optA.value = panel.id;
        optA.textContent = `Panel ${panel.id} (L${panel.floor})`;
        selectA.appendChild(optA);
        
        const optB = document.createElement("option");
        optB.value = panel.id;
        optB.textContent = `Panel ${panel.id} (L${panel.floor})`;
        selectB.appendChild(optB);
    });
    
    selectA.value = valA;
    selectB.value = valB;
}

function updateDetailedComparison() {
    const selectA = document.getElementById("compare-panel-a");
    const selectB = document.getElementById("compare-panel-b");
    const resultsContainer = document.getElementById("comparison-results");
    
    if (!selectA || !selectB || !resultsContainer) return;
    
    const idA = selectA.value;
    const idB = selectB.value;
    
    if (!idA || !idB) {
        resultsContainer.innerHTML = `<div class="no-selection-msg">Select two sensors to compare</div>`;
        return;
    }
    
    if (idA === idB) {
        resultsContainer.innerHTML = `<div class="no-selection-msg" style="color: var(--accent-red);">Select different sensors to compare</div>`;
        return;
    }
    
    const panelA = panels.find(p => p.id === idA);
    const panelB = panels.find(p => p.id === idB);
    
    if (!panelA || !panelB) return;
    
    const setA = panelA.crossedAgents;
    const setB = panelB.crossedAgents;
    
    let sharedCount = 0;
    for (let agentId of setA) {
        if (setB.has(agentId)) sharedCount++;
    }
    
    const jaccard = getPanelSimilarity(panelA, panelB, "jaccard");
    const cosine = getPanelSimilarity(panelA, panelB, "cosine");
    
    const onlyA = setA.size - sharedCount;
    const onlyB = setB.size - sharedCount;
    const totalUnique = onlyA + sharedCount + onlyB;
    
    let pctA = 0;
    let pctShared = 0;
    let pctB = 0;
    
    if (totalUnique > 0) {
        pctA = (onlyA / totalUnique) * 100;
        pctShared = (sharedCount / totalUnique) * 100;
        pctB = (onlyB / totalUnique) * 100;
    }
    
    resultsContainer.innerHTML = `
        <div class="comparison-metric-row">
            <span class="comparison-metric-label">Panel A unique agents</span>
            <span class="comparison-metric-val" style="color: #3b82f6;">${setA.size.toLocaleString()}</span>
        </div>
        <div class="comparison-metric-row">
            <span class="comparison-metric-label">Panel B unique agents</span>
            <span class="comparison-metric-val" style="color: #ec4899;">${setB.size.toLocaleString()}</span>
        </div>
        <div class="comparison-metric-row">
            <span class="comparison-metric-label">Shared agents</span>
            <span class="comparison-metric-val highlight-purple">${sharedCount.toLocaleString()}</span>
        </div>
        <div class="comparison-metric-row">
            <span class="comparison-metric-label">Jaccard Similarity</span>
            <span class="comparison-metric-val">${(jaccard * 100).toFixed(1)}%</span>
        </div>
        <div class="comparison-metric-row">
            <span class="comparison-metric-label">Cosine Similarity</span>
            <span class="comparison-metric-val">${(cosine * 100).toFixed(1)}%</span>
        </div>
        
        <div class="overlap-bar-container">
            <div class="overlap-bar-title">Audience Overlap (Unique total: ${totalUnique.toLocaleString()})</div>
            <div class="overlap-bar-wrapper">
                <div class="overlap-segment only-a" style="width: ${pctA}%;" title="Unique to A: ${onlyA.toLocaleString()} agents (${pctA.toFixed(1)}%)"></div>
                <div class="overlap-segment shared" style="width: ${pctShared}%;" title="Shared: ${sharedCount.toLocaleString()} agents (${pctShared.toFixed(1)}%)"></div>
                <div class="overlap-segment only-b" style="width: ${pctB}%;" title="Unique to B: ${onlyB.toLocaleString()} agents (${pctB.toFixed(1)}%)"></div>
            </div>
            <div class="overlap-bar-legend">
                <span class="legend-item">
                    <span class="legend-color-dot only-a"></span>
                    Only A (${onlyA.toLocaleString()})
                </span>
                <span class="legend-item">
                    <span class="legend-color-dot shared"></span>
                    Shared (${sharedCount.toLocaleString()})
                </span>
                <span class="legend-item">
                    <span class="legend-color-dot only-b"></span>
                    Only B (${onlyB.toLocaleString()})
                </span>
            </div>
        </div>
    `;
}

// Simulation configuration JSON Export/Import helpers
function exportConfigJSON() {
    const config = {
        timestamp: new Date().toISOString(),
        totalAgents: parseInt(document.getElementById("input-total-agents").value),
        minVisits: parseInt(document.getElementById("input-min-visits").value),
        maxVisits: parseInt(document.getElementById("input-max-visits").value),
        walkSpeed: parseFloat(document.getElementById("input-walk-speed").value),
        decayExponent: parseFloat(document.getElementById("input-decay-exponent").value),
        viewDist: parseFloat(document.getElementById("input-view-dist").value),
        coneAngle: parseFloat(document.getElementById("input-cone-angle").value),
        showGraph: document.getElementById("chk-show-graph").checked,
        categoryWeights: {},
        activePanelIds: []
    };
    
    // Attractiveness weights
    for (const cat in categoryWeights) {
        const slider = document.getElementById(`wt-${cat}`);
        if (slider) {
            config.categoryWeights[cat] = parseInt(slider.value) / 100.0;
        } else {
            config.categoryWeights[cat] = categoryWeights[cat];
        }
    }
    
    // Active panels checkbox state
    panels.forEach(p => {
        const chk = document.getElementById(`chk-${p.id}`);
        if (chk && chk.checked) {
            config.activePanelIds.push(p.id);
        }
    });
    
    const jsonStr = JSON.stringify(config, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    
    const dateStr = new Date().toISOString().slice(0, 10);
    const timeStr = new Date().toTimeString().slice(0, 8).replace(/:/g, "-");
    link.setAttribute("download", `westfield_newmarket_sim_config_${dateStr}_${timeStr}.json`);
    
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

function importConfigJSON(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    const reader = new FileReader();
    reader.onload = function(e) {
        try {
            const config = JSON.parse(e.target.result);
            
            // Set UI sliders & inputs
            const sAgents = document.getElementById("input-total-agents");
            if (sAgents && config.totalAgents !== undefined) {
                sAgents.value = config.totalAgents;
                sAgents.dispatchEvent(new Event("input"));
            }
            
            const sMin = document.getElementById("input-min-visits");
            if (sMin && config.minVisits !== undefined) {
                sMin.value = config.minVisits;
                sMin.dispatchEvent(new Event("input"));
            }
            
            const sMax = document.getElementById("input-max-visits");
            if (sMax && config.maxVisits !== undefined) {
                sMax.value = config.maxVisits;
                sMax.dispatchEvent(new Event("input"));
            }
            
            const sSpeed = document.getElementById("input-walk-speed");
            if (sSpeed && config.walkSpeed !== undefined) {
                sSpeed.value = config.walkSpeed;
                sSpeed.dispatchEvent(new Event("input"));
            }
            
            const sDecay = document.getElementById("input-decay-exponent");
            if (sDecay && config.decayExponent !== undefined) {
                sDecay.value = config.decayExponent;
                sDecay.dispatchEvent(new Event("input"));
            }
            
            const sDist = document.getElementById("input-view-dist");
            if (sDist && config.viewDist !== undefined) {
                sDist.value = config.viewDist;
                sDist.dispatchEvent(new Event("input"));
            }
            
            const sAngle = document.getElementById("input-cone-angle");
            if (sAngle && config.coneAngle !== undefined) {
                sAngle.value = config.coneAngle;
                sAngle.dispatchEvent(new Event("input"));
            }
            
            const chkGraph = document.getElementById("chk-show-graph");
            if (chkGraph && config.showGraph !== undefined) {
                chkGraph.checked = config.showGraph;
                chkGraph.dispatchEvent(new Event("change"));
            }
            
            // Category weights
            if (config.categoryWeights) {
                for (const cat in config.categoryWeights) {
                    const slider = document.getElementById(`wt-${cat}`);
                    if (slider) {
                        slider.value = Math.round(config.categoryWeights[cat] * 100);
                        slider.dispatchEvent(new Event("input"));
                    }
                }
            }
            
            // Active panels
            if (config.activePanelIds) {
                const activeSet = new Set(config.activePanelIds);
                panels.forEach(p => {
                    const chk = document.getElementById(`chk-${p.id}`);
                    if (chk) {
                        chk.checked = activeSet.has(p.id);
                        chk.dispatchEvent(new Event("change"));
                    }
                });
            }
            
            // Clear file input value to allow uploading same file again
            event.target.value = "";
            alert("Configuration profile imported successfully!");
            
        } catch(err) {
            console.error("Failed to parse JSON config file:", err);
            alert("Error: Invalid configuration file format.");
        }
    };
    reader.readAsText(file);
}

// Raw Exposure Vector Export
function exportInteractionVectors() {
    if (!panels || panels.length === 0) {
        alert("No panels loaded.");
        return;
    }
    
    // Check if simulation has been run (crossedAgents has data)
    const hasData = panels.some(p => p.crossedAgents.size > 0);
    if (!hasData) {
        alert("Please run the simulation first to populate agent interactions.");
        return;
    }
    
    const format = document.getElementById("select-vector-format").value;
    const numAgents = totalAgentsToSimulate;
    
    const headers = ["Panel ID", "Format", "Interaction Data"];
    const rows = [];
    
    panels.forEach(panel => {
        const set = panel.crossedAgents;
        let vectorData = "";
        
        if (format === "binary") {
            const arr = new Array(numAgents).fill('0');
            set.forEach(agentId => {
                let agentIndex;
                if (typeof agentId === 'string') {
                    agentIndex = parseInt(agentId.replace("agent_", ""), 10);
                } else {
                    agentIndex = parseInt(agentId, 10);
                }
                if (isNaN(agentIndex)) return;
                
                const idx = agentIndex - 1;
                if (idx >= 0 && idx < numAgents) {
                    arr[idx] = '1';
                }
            });
            vectorData = arr.join('');
            
        } else if (format === "base64") {
            const numBytes = Math.ceil(numAgents / 8);
            const bytes = new Uint8Array(numBytes);
            set.forEach(agentId => {
                let agentIndex;
                if (typeof agentId === 'string') {
                    agentIndex = parseInt(agentId.replace("agent_", ""), 10);
                } else {
                    agentIndex = parseInt(agentId, 10);
                }
                if (isNaN(agentIndex)) return;
                
                const idx = agentIndex - 1;
                if (idx >= 0 && idx < numAgents) {
                    const byteIdx = Math.floor(idx / 8);
                    const bitIdx = 7 - (idx % 8); // MSB-first bit order
                    bytes[byteIdx] |= (1 << bitIdx);
                }
            });
            let binaryStr = "";
            const len = bytes.byteLength;
            for (let i = 0; i < len; i++) {
                binaryStr += String.fromCharCode(bytes[i]);
            }
            vectorData = btoa(binaryStr);
            
        } else if (format === "sparse") {
            const indices = Array.from(set)
                .map(agentId => {
                    if (typeof agentId === 'string') {
                        return parseInt(agentId.replace("agent_", ""), 10);
                    }
                    return parseInt(agentId, 10);
                })
                .filter(idx => !isNaN(idx))
                .sort((a, b) => a - b);
            vectorData = indices.join(';');
        }
        
        rows.push([
            `"${panel.name}"`,
            `"${format}"`,
            `"${vectorData}"`
        ]);
    });
    
    const metadata = [
        `# Westfield Newmarket Pedestrian Gravity Simulation - Raw Exposure Vectors`,
        `# Export Date: ${new Date().toISOString()}`,
        `# Total Agents: ${numAgents.toLocaleString()}`,
        `# Vector Format: ${format}`,
        `# Note: Sparse indices are separated by semicolons (;) to preserve CSV columns.`,
        `#`
    ];
    
    const csvContent = metadata.concat([headers.join(",")])
                               .concat(rows.map(row => row.join(",")))
                               .join("\n");
                               
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    
    const dateStr = new Date().toISOString().slice(0, 10);
    const timeStr = new Date().toTimeString().slice(0, 8).replace(/:/g, "-");
    link.setAttribute("download", `westfield_newmarket_panel_vectors_${format}_${dateStr}_${timeStr}.csv`);
    
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// Initial App Entry Point
window.addEventListener("DOMContentLoaded", () => {
    // 1. Initialize Map Container & Layout controls if Leaflet is present
    const isLeafletLoaded = (typeof L !== 'undefined');
    if (isLeafletLoaded) {
        initMap();
    } else {
        const mapContainer = document.getElementById("map");
        if (mapContainer) {
            mapContainer.innerHTML = `
                <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; padding: 2rem; text-align: center; color: #94a3b8; gap: 12px;">
                    <span style="font-size: 32px;">⚠️</span>
                    <h3 style="color: #ffffff; font-family: var(--font-heading); font-size: 16px;">Map Visualizer Offline</h3>
                    <p style="font-size: 12px; max-width: 300px; line-height: 1.4;">The Leaflet mapping engine failed to load. The headless mathematical simulation remains fully operational.</p>
                </div>
            `;
        }
    }
    
    bindUIControls();
    
    // 2. Load panel list CSV and network graph asynchronously
    const promises = [loadPanels(), loadGraph()];
    if (isLeafletLoaded) {
        promises.push(loadGeoJSON());
    }
    
    Promise.all(promises).then(() => {
        console.log("Initialization Complete. Headless Engine Ready.");
        renderPanelsSelectionGrid();
        
        // Start precomputation in background so that there's no lag when running
        setTimeout(precomputePaths, 200);
    }).catch(err => {
        console.error("CRITICAL PORTAL INITIALIZATION FAILURE:", err);
        // Display user-friendly error on screen if critical data fails to load
        const listContainer = document.getElementById("panels-selection-grid");
        if (listContainer) {
            listContainer.innerHTML = `
                <div style="padding: 1.5rem; text-align: center; color: #ef4444; border: 1px dashed rgba(239, 68, 68, 0.2); border-radius: 8px;">
                    <p style="font-weight: 600;">System Failed to Initialize</p>
                    <p style="font-size: 11px; margin-top: 4px; color: #94a3b8;">${err.message || err}</p>
                </div>
            `;
        }
    });
});
