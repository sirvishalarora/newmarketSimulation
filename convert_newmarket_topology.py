import json
import math

def reproject_point(x, y):
    # Convert EPSG:3857 to EPSG:4326 (longitude and latitude)
    lon = (x / 20037508.34) * 180.0
    # Y conversion
    lat = (y / 20037508.34) * 180.0
    lat = 180.0 / math.pi * (2.0 * math.atan(math.exp(lat * math.pi / 180.0)) - math.pi / 2.0)
    return [lon, lat]

def reproject_coordinates(coords, geom_type):
    if geom_type == "Point":
        return reproject_point(coords[0], coords[1])
    elif geom_type in ["LineString", "MultiPoint"]:
        return [reproject_point(p[0], p[1]) for p in coords]
    elif geom_type in ["Polygon", "MultiLineString"]:
        return [[reproject_point(p[0], p[1]) for p in ring] for ring in coords]
    elif geom_type == "MultiPolygon":
        return [[[reproject_point(p[0], p[1]) for p in ring] for ring in poly] for poly in coords]
    return coords

def get_centroid(coords):
    # Get flat list of vertices
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

with open("Westfield_NewMarket_topology.geojson", "r") as f:
    data = json.load(f)

new_features = []

for f in data.get("features", []):
    props = f.get("properties", {})
    geom = f.get("geometry", {})
    geom_type = geom.get("type")
    zone_type = props.get("zone_type")
    zone_name = props.get("zone_name")
    floor_level = str(props.get("floor_level"))
    
    # Reproject coordinates
    new_geom = {
        "type": geom_type,
        "coordinates": reproject_coordinates(geom.get("coordinates", []), geom_type)
    }
    
    # Map properties to Albany style
    new_props = {
        "@id": f"way/{props.get('fid')}",
        "level": floor_level,
        "name": zone_name
    }
    
    if zone_type == "corridor":
        new_props["indoor"] = "corridor"
    elif zone_type == "shops":
        new_props["indoor"] = "room"
        new_props["shop"] = "yes"
    elif zone_type == "food_court":
        new_props["indoor"] = "room"
        new_props["amenity"] = "food_court"
    elif zone_type == "office":
        new_props["indoor"] = "room"
        new_props["office"] = "yes"
    elif zone_type == "seats":
        new_props["indoor"] = "room"
        new_props["amenity"] = "bench"
    elif zone_type == "parking":
        new_props["indoor"] = "room"
        new_props["amenity"] = "parking"
    elif zone_type == "elevator":
        new_props["indoor"] = "room"
        new_props["highway"] = "elevator"
        new_props["room"] = "elevator"
    elif zone_type == "escalator":
        new_props["indoor"] = "room"
        new_props["highway"] = "steps"
        new_props["conveying"] = "yes"
    elif zone_type == "information":
        new_props["indoor"] = "room"
        new_props["amenity"] = "information"
    elif zone_type == "entry_exit":
        # Check if it is a mall entry/exit (starts with entry_exit)
        # Or a shop entry/exit
        if zone_name.startswith("entry_exit"):
            # Convert mall entrance to a Point feature at the centroid
            centroid_3857 = get_centroid(geom.get("coordinates", []))
            centroid_4326 = reproject_point(centroid_3857[0], centroid_3857[1])
            
            new_geom = {
                "type": "Point",
                "coordinates": centroid_4326
            }
            new_props = {
                "@id": f"node/{props.get('fid')}",
                "entrance": "main" if "lv1" in zone_name else "yes",
                "level": floor_level,
                "name": zone_name
            }
        else:
            # Shop entrance
            # Convert to Point at the centroid for cleaner visualization and graph linkage
            centroid_3857 = get_centroid(geom.get("coordinates", []))
            centroid_4326 = reproject_point(centroid_3857[0], centroid_3857[1])
            
            new_geom = {
                "type": "Point",
                "coordinates": centroid_4326
            }
            new_props = {
                "@id": f"node/{props.get('fid')}",
                "entrance": "shop",
                "level": floor_level,
                "name": zone_name
            }
            
    new_feature = {
        "type": "Feature",
        "properties": new_props,
        "geometry": new_geom
    }
    new_features.append(new_feature)

output_data = {
    "type": "FeatureCollection",
    "name": "Westfield_NewMarket_topology_4326",
    "features": new_features
}

with open("Westfield_NewMarket_topology_4326.geojson", "w") as f:
    json.dump(output_data, f, indent=2)

print("Conversion complete! Saved Westfield_NewMarket_topology_4326.geojson")
print(f"Total features converted: {len(new_features)}")
