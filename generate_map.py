import pandas as pd
import folium
from shapely.wkt import loads
import os

def create_map():
    csv_path = "panel_locations.csv"
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found.")
        return

    # Try reading as comma-separated first; fallback to tab-separated if columns are collapsed
    df = pd.read_csv(csv_path)
    if len(df.columns) <= 1:
        df = pd.read_csv(csv_path, sep='\t')
    
    print("Columns in CSV:", df.columns.tolist())
    print("Number of rows:", len(df))

    # Calculate average lat/lon to center the map
    mean_lat = df['latitude'].mean()
    mean_lon = df['longitude'].mean()
    print(f"Map center: lat={mean_lat}, lon={mean_lon}")

    # Create folium map
    m = folium.Map(location=[mean_lat, mean_lon], zoom_start=18, max_zoom=22)

    # Add satellite imagery option
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri',
        name='Esri World Imagery',
        overlay=False,
        control=True
    ).add_to(m)
    folium.LayerControl().add_to(m)

    for idx, row in df.iterrows():
        panel_id = row['panel_id']
        site_id = row['site_id']
        lat = row['latitude']
        lon = row['longitude']
        orientation = row.get('orientation', 'N/A')
        width = row.get('panel_width', 'N/A')
        height = row.get('panel_height', 'N/A')
        vc_wkt = row['vc']

        popup_html = f"""
        <div style="font-family: Arial, sans-serif; font-size: 12px;">
            <b>Panel ID:</b> {panel_id}<br/>
            <b>Site ID:</b> {site_id}<br/>
            <b>Latitude:</b> {lat:.6f}<br/>
            <b>Longitude:</b> {lon:.6f}<br/>
            <b>Orientation:</b> {orientation}<br/>
            <b>Dimensions:</b> {width}m x {height}m
        </div>
        """

        # Add Marker at the center coordinate
        folium.Marker(
            location=[lat, lon],
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"Panel {panel_id}"
        ).add_to(m)

        # Draw orientation arrow pointing from center instead of drawing vc polygon
        try:
            if not pd.isnull(orientation):
                import math
                # Convert orientation (degrees) to radians
                # 0 is North (up/y-positive), 90 is East (right/x-positive)
                angle_rad = math.radians(orientation)

                # Length of the arrow shaft (e.g., 3 meters)
                arrow_length = 3.0
                
                # Calculate delta lat/lon for the end point
                delta_lat = (arrow_length * math.cos(angle_rad)) / 111111.0
                delta_lon = (arrow_length * math.sin(angle_rad)) / (111111.0 * math.cos(math.radians(lat)))
                
                end_lat = lat + delta_lat
                end_lon = lon + delta_lon

                # Draw the arrow shaft
                folium.PolyLine(
                    locations=[[lat, lon], [end_lat, end_lon]],
                    color='#FF3D00',
                    weight=4,
                    opacity=0.9,
                    popup=folium.Popup(popup_html, max_width=300)
                ).add_to(m)

                # Calculate arrowhead coordinates (150 degrees backwards from heading direction)
                arrow_size = 0.8  # length of arrowhead wings in meters
                left_angle = angle_rad + math.radians(150)
                right_angle = angle_rad - math.radians(150)

                left_delta_lat = (arrow_size * math.cos(left_angle)) / 111111.0
                left_delta_lon = (arrow_size * math.sin(left_angle)) / (111111.0 * math.cos(math.radians(end_lat)))
                
                right_delta_lat = (arrow_size * math.cos(right_angle)) / 111111.0
                right_delta_lon = (arrow_size * math.sin(right_angle)) / (111111.0 * math.cos(math.radians(end_lat)))

                left_lat = end_lat + left_delta_lat
                left_lon = end_lon + left_delta_lon
                right_lat = end_lat + right_delta_lat
                right_lon = end_lon + right_delta_lon

                # Draw arrowhead
                folium.Polygon(
                    locations=[[end_lat, end_lon], [left_lat, left_lon], [right_lat, right_lon]],
                    color='#FF3D00',
                    fill=True,
                    fill_color='#FF3D00',
                    fill_opacity=1.0,
                    popup=folium.Popup(popup_html, max_width=300)
                ).add_to(m)

            else:
                print(f"Warning: Orientation missing for panel {panel_id}")
        except Exception as e:
            print(f"Error drawing orientation arrow for panel {panel_id}: {e}")

    output_html = "panel_locations_map.html"
    m.save(output_html)
    print(f"Map successfully saved to {output_html}")

if __name__ == "__main__":
    create_map()
