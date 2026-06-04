import json
import math

# Coordinate translation helpers (meters per degree at Auckland latitude)
LAT_DEG_TO_M = 111000.0
LON_DEG_TO_M = 88800.0  # at -36.87 deg lat

def get_centroid(geom):
    coords = geom.get("coordinates", [])
    if not coords:
        return [0, 0]
    xs, ys = [], []
    def rec(lst):
        for item in lst:
            if isinstance(item, list):
                if len(item) == 2 and isinstance(item[0], (int, float)):
                    xs.append(item[0])
                    ys.append(item[1])
                else:
                    rec(item)
    rec(coords)
    if not xs:
        return [0, 0]
    return [sum(xs)/len(xs), sum(ys)/len(ys)]

def point_in_polygon(x, y, polygon_coords):
    # polygon_coords is a list of rings (exterior, holes...)
    if not polygon_coords:
        return False
        
    # Check exterior ring
    exterior = polygon_coords[0]
    inside = False
    n = len(exterior)
    if n < 3:
        return False
    p1x, p1y = exterior[0]
    for i in range(n + 1):
        p2x, p2y = exterior[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y
        
    if not inside:
        return False
        
    # Check holes (if inside a hole, the point is outside)
    if len(polygon_coords) > 1:
        for hole in polygon_coords[1:]:
            hole_inside = False
            n_hole = len(hole)
            if n_hole < 3:
                continue
            p1x, p1y = hole[0]
            for i in range(n_hole + 1):
                p2x, p2y = hole[i % n_hole]
                if y > min(p1y, p2y):
                    if y <= max(p1y, p2y):
                        if x <= max(p1x, p2x):
                            if p1y != p2y:
                                xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                            if p1x == p2x or x <= xinters:
                                hole_inside = not hole_inside
                p1x, p1y = p2x, p2y
            if hole_inside:
                return False
                
    return True

# Line segment intersection check (ccw test)
def ccw(A, B, C):
    return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])

def segments_intersect(A, B, C, D):
    # Returns True if segment AB intersects segment CD
    # Ignore if they share endpoints
    if A == C or A == D or B == C or B == D:
        return False
    return ccw(A, C, D) != ccw(B, C, D) and ccw(A, B, C) != ccw(A, B, D)

def segment_crosses_boundaries(A, B, polygon_coords):
    # Check if segment AB intersects any boundary segment of the polygon (exterior + holes)
    for ring in polygon_coords:
        n = len(ring)
        for i in range(n):
            C = ring[i]
            D = ring[(i + 1) % n]
            if segments_intersect(A, B, C, D):
                return True
    return False

def distance_m(p1, p2):
    dx = (p1[0] - p2[0]) * LON_DEG_TO_M
    dy = (p1[1] - p2[1]) * LAT_DEG_TO_M
    return math.hypot(dx, dy)

# Bounding box of coordinates
def get_bbox(coords):
    xs, ys = [], []
    def rec(lst):
        for item in lst:
            if isinstance(item, list):
                if len(item) == 2 and isinstance(item[0], (int, float)):
                    xs.append(item[0])
                    ys.append(item[1])
                else:
                    rec(item)
    rec(coords)
    if not xs:
        return 0, 0, 0, 0
    return min(xs), min(ys), max(xs), max(ys)

def main():
    print("Loading Westfield_NewMarket_topology_4326.geojson...")
    with open("Westfield_NewMarket_topology_4326.geojson", "r") as f:
        data = json.load(f)
        
    features = data.get("features", [])
    
    # Classify features
    corridors = []
    escalators = []
    elevators = []
    mall_entrances = []
    shop_entrances = []
    
    for f in features:
        props = f.get("properties", {})
        geom = f.get("geometry", {})
        gtype = geom.get("type")
        name = props.get("name", "")
        level = props.get("level", "1")
        
        # Corridors
        if props.get("indoor") == "corridor":
            corridors.append(f)
        # Escalators
        elif props.get("highway") == "steps" and props.get("conveying") == "yes":
            escalators.append(f)
        # Elevators
        elif props.get("highway") == "elevator":
            elevators.append(f)
        # Entrances
        elif "entrance" in props:
            ent_type = props["entrance"]
            if ent_type == "main" or ent_type == "yes":
                mall_entrances.append(f)
            elif ent_type == "shop":
                shop_entrances.append(f)
                
    print(f"Found:")
    print(f"  Corridors: {len(corridors)}")
    print(f"  Escalators: {len(escalators)}")
    print(f"  Elevators: {len(elevators)}")
    print(f"  Mall Entrances: {len(mall_entrances)}")
    print(f"  Shop Entrances: {len(shop_entrances)}")
    
    # Initialize graph lists
    nodes = []
    edges = []
    node_id_counter = 0
    
    # Store nodes by level for easier linking
    level_grid_nodes = {"1": [], "2": [], "3": []}
    special_nodes_by_level = {"1": [], "2": [], "3": []}
    
    # 1. Generate grid nodes inside corridor polygons
    # Auckland step size: lat_step = 0.000045 (~5m), lon_step = 0.000056 (~5m)
    # Using slightly smaller grid spacing for dense coverage: 4 meters
    # lat_step = 4 / 111000 = 0.000036
    # lon_step = 4 / 88800 = 0.000045
    lat_step = 0.000036
    lon_step = 0.000045
    
    print("\nSampling grid nodes inside corridors...")
    for corr in corridors:
        cp = corr["properties"]
        cg = corr["geometry"]
        level = cp.get("level")
        name = cp.get("name")
        polygon_coords = cg.get("coordinates", [])
        
        bbox = get_bbox(polygon_coords)
        if bbox == (0,0,0,0):
            continue
            
        min_lon, min_lat, max_lon, max_lat = bbox
        
        # Grid loop
        lon = min_lon
        corr_node_count = 0
        while lon <= max_lon:
            lat = min_lat
            while lat <= max_lat:
                # Check if inside corridor polygon (taking care of holes)
                if point_in_polygon(lon, lat, polygon_coords):
                    # Add node
                    nid = f"grid_{node_id_counter}"
                    node_id_counter += 1
                    node_obj = {
                        "id": nid,
                        "x": lon,
                        "y": lat,
                        "level": level,
                        "type": "corridor",
                        "corridor_name": name
                    }
                    nodes.append(node_obj)
                    level_grid_nodes[level].append(node_obj)
                    corr_node_count += 1
                lat += lat_step
            lon += lon_step
        print(f"  Corridor {name} (L{level}): sampled {corr_node_count} nodes")
        
    # 2. Add Mall Entrances, Shop Entrances, Escalators, and Elevators as nodes
    print("\nAdding special nodes (entrances, transits)...")
    special_node_map = {} # map way/node id to node object
    
    # Mall entrances (Points)
    for me in mall_entrances:
        mp = me["properties"]
        mg = me["geometry"]
        level = mp.get("level")
        coords = mg.get("coordinates")
        nid = mp.get("@id")
        
        node_obj = {
            "id": nid,
            "x": coords[0],
            "y": coords[1],
            "level": level,
            "type": "mall_entrance",
            "name": mp.get("name")
        }
        nodes.append(node_obj)
        special_nodes_by_level[level].append(node_obj)
        special_node_map[nid] = node_obj
        
    # Shop entrances (Points)
    for se in shop_entrances:
        sp = se["properties"]
        sg = se["geometry"]
        level = sp.get("level")
        coords = sg.get("coordinates")
        nid = sp.get("@id")
        
        node_obj = {
            "id": nid,
            "x": coords[0],
            "y": coords[1],
            "level": level,
            "type": "shop_entry",
            "name": sp.get("name")
        }
        nodes.append(node_obj)
        special_nodes_by_level[level].append(node_obj)
        special_node_map[nid] = node_obj
        
    # Escalators (Polygons) -> Centroids
    for esc in escalators:
        ep = esc["properties"]
        eg = esc["geometry"]
        level = ep.get("level")
        nid = ep.get("@id")
        cx, cy = get_centroid(eg)
        
        node_obj = {
            "id": nid,
            "x": cx,
            "y": cy,
            "level": level,
            "type": "escalator",
            "name": ep.get("name")
        }
        nodes.append(node_obj)
        special_nodes_by_level[level].append(node_obj)
        special_node_map[nid] = node_obj
        
    # Elevators (Polygons) -> Centroids
    for el in elevators:
        elp = el["properties"]
        elg = el["geometry"]
        level = elp.get("level")
        nid = elp.get("@id")
        cx, cy = get_centroid(elg)
        
        node_obj = {
            "id": nid,
            "x": cx,
            "y": cy,
            "level": level,
            "type": "elevator",
            "name": elp.get("name")
        }
        nodes.append(node_obj)
        special_nodes_by_level[level].append(node_obj)
        special_node_map[nid] = node_obj

    # 3. Connect Grid Nodes inside Corridors
    # Connect grid nodes on the same level if they are within max_dist and doesn't cross boundary
    # Max distance: 10 meters
    max_link_dist = 10.0
    print("\nConnecting corridor grid nodes...")
    for level, gnodes in level_grid_nodes.items():
        print(f"  Level {level}: Connecting {len(gnodes)} grid nodes...")
        level_corridors = [c for c in corridors if c["properties"].get("level") == level]
        
        for i in range(len(gnodes)):
            n1 = gnodes[i]
            p1 = [n1["x"], n1["y"]]
            for j in range(i + 1, len(gnodes)):
                n2 = gnodes[j]
                p2 = [n2["x"], n2["y"]]
                
                dist = distance_m(p1, p2)
                if dist <= max_link_dist:
                    # Check if line segment intersects any corridor polygon's boundary
                    crosses = False
                    for corr in level_corridors:
                        polygon_coords = corr["geometry"].get("coordinates", [])
                        if segment_crosses_boundaries(p1, p2, polygon_coords):
                            crosses = True
                            break
                    
                    if not crosses:
                        edges.append({
                            "source": n1["id"],
                            "target": n2["id"],
                            "weight": dist,
                            "level": level,
                            "type": "corridor"
                        })
                        
    # 4. Connect Special Nodes to the nearest walkable corridor grid nodes
    print("\nConnecting entrances, escalators, and elevators to grid...")
    for level, snodes in special_nodes_by_level.items():
        gnodes = level_grid_nodes[level]
        level_corridors = [c for c in corridors if c["properties"].get("level") == level]
        
        for sn in snodes:
            sp = [sn["x"], sn["y"]]
            
            # Find closest grid node that doesn't cross corridor boundaries
            candidates = []
            for gn in gnodes:
                gp = [gn["x"], gn["y"]]
                dist = distance_m(sp, gp)
                candidates.append((gn, dist))
                
            candidates.sort(key=lambda x: x[1])
            
            connected = False
            # Check up to 10 closest grid nodes
            for gn, dist in candidates[:10]:
                gp = [gn["x"], gn["y"]]
                crosses = False
                for corr in level_corridors:
                    polygon_coords = corr["geometry"].get("coordinates", [])
                    if segment_crosses_boundaries(sp, gp, polygon_coords):
                        crosses = True
                        break
                
                # For shop entrances, if they are slightly outside the corridor boundary,
                # they might cross a boundary to connect. If they cross, we still connect them
                # if the distance is very short (< 5 meters) to ensure they are linked.
                if not crosses or dist < 5.0:
                    edges.append({
                        "source": sn["id"],
                        "target": gn["id"],
                        "weight": dist,
                        "level": level,
                        "type": "connection"
                    })
                    connected = True
                    break
                    
            if not connected and candidates:
                # Fallback: connect to closest grid node directly regardless of boundary crossing
                gn, dist = candidates[0]
                edges.append({
                    "source": sn["id"],
                    "target": gn["id"],
                    "weight": dist,
                    "level": level,
                    "type": "connection_fallback"
                })
                print(f"  Warning: Node {sn['id']} ({sn['type']} - {sn['name']}) used fallback connection to {gn['id']} (dist: {dist:.2f}m)")

    # 5. Connect Elevators and Escalators Vertically
    print("\nConnecting levels vertically...")
    
    # Matching elevators by 2D distance
    # Connect them with a vertical transit edge (vertical weight e.g. 15.0m for time delay)
    vertical_transit_weight = 15.0
    vertical_elevators_connected = 0
    
    for e1 in nodes:
        if e1["type"] != "elevator":
            continue
        p1 = [e1["x"], e1["y"]]
        
        for e2 in nodes:
            if e2["type"] != "elevator":
                continue
            if e1["id"] == e2["id"]:
                continue
            
            # Check if levels are adjacent or connect directly (e.g. L1 to L2, L2 to L3)
            # Make sure we don't connect L1 to L3 directly if there is no intermediate node
            # (or we can connect them if they represent the same elevator shaft)
            l1 = int(e1["level"])
            l2 = int(e2["level"])
            
            if l1 + 1 == l2:
                dist_2d = distance_m(p1, [e2["x"], e2["y"]])
                if dist_2d < 15.0: # Spatially aligned
                    edges.append({
                        "source": e1["id"],
                        "target": e2["id"],
                        "weight": vertical_transit_weight,
                        "level": f"{l1}-{l2}",
                        "type": "elevator"
                    })
                    vertical_elevators_connected += 1
                    
    # Matching escalators by 2D distance
    vertical_escalators_connected = 0
    for esc1 in nodes:
        if esc1["type"] != "escalator":
            continue
        p1 = [esc1["x"], esc1["y"]]
        
        for esc2 in nodes:
            if esc2["type"] != "escalator":
                continue
            if esc1["id"] == esc2["id"]:
                continue
            
            l1 = int(esc1["level"])
            l2 = int(esc2["level"])
            
            if l1 + 1 == l2:
                dist_2d = distance_m(p1, [esc2["x"], esc2["y"]])
                if dist_2d < 20.0: # Spatially aligned
                    edges.append({
                        "source": esc1["id"],
                        "target": esc2["id"],
                        "weight": vertical_transit_weight,
                        "level": f"{l1}-{l2}",
                        "type": "escalator"
                    })
                    vertical_escalators_connected += 1
                    
    print(f"Connected:")
    print(f"  Vertical Elevators: {vertical_elevators_connected} edges")
    print(f"  Vertical Escalators: {vertical_escalators_connected} edges")
    
    # Filter out isolated nodes (degree = 0)
    connected_node_ids = set()
    for edge in edges:
        connected_node_ids.add(edge["source"])
        connected_node_ids.add(edge["target"])
        
    filtered_nodes = [n for n in nodes if n["id"] in connected_node_ids]
    print(f"\nFiltered out {len(nodes) - len(filtered_nodes)} isolated nodes.")
    
    # Save Graph JSON
    graph_data = {
        "nodes": filtered_nodes,
        "edges": edges
    }
    
    output_filename = "newmarket_graph.json"
    with open(output_filename, "w") as f:
        json.dump(graph_data, f, indent=2)
        
    print(f"\nSaved graph to {output_filename} successfully!")
    print(f"Graph stats: {len(filtered_nodes)} nodes, {len(edges)} edges")

if __name__ == "__main__":
    main()
