"""Quick visual check: where are the default sensors placed on the map?

Not part of the core library -- just a throwaway debug script. Run it and
open the generated HTML file(s) in a browser.

Usage:
    python visualize_sensors.py
"""

from __future__ import annotations

import folium

from core.regions import load_region
from core.sensors import default_sensor_layout


def build_sensor_map(region_key: str) -> folium.Map:
    region = load_region(region_key)
    sensors = default_sensor_layout(region)

    fmap = folium.Map(location=list(region.center), zoom_start=region.default_zoom)

    # Region boundary -- same style as app.py's main map.
    folium.Polygon(
        locations=region.bbox, color="#d7191c", weight=2, fill=False,
        popup="Region boundary",
    ).add_to(fmap)

    # Line-of-sight centerline, so you can see where the river/fairway is
    # relative to the sensors.
    if region.los:
        folium.PolyLine(
            locations=region.los, color="#5bc8f5", weight=2, dash_array="5,5",
            popup="Line of sight (fairway centerline)",
        ).add_to(fmap)

    # Sensors -- bright, distinct markers.
    for s in sensors:
        folium.CircleMarker(
            location=(s.lat, s.lon),
            radius=9,
            color="#000000",
            weight=2,
            fill=True,
            fill_color="#ffcc00",
            fill_opacity=1.0,
            popup=folium.Popup(f"{s.sensor_id}<br>{s.lat:.5f}, {s.lon:.5f}", max_width=200),
        ).add_to(fmap)
        folium.map.Marker(
            location=(s.lat, s.lon),
            icon=folium.DivIcon(html=f"""<div style="font-size:11px;font-weight:bold;
                transform:translate(10px,-6px);">{s.sensor_id}</div>"""),
        ).add_to(fmap)

    return fmap


if __name__ == "__main__":
    for key in ("rheinhafen", "cuxhaven"):
        out_path = f"{key}_sensors_map.html"
        build_sensor_map(key).save(out_path)
        print(f"Wrote {out_path} -- open it in a browser to view.")
