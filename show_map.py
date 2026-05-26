import json
import folium

with open("dfw_zones_output.json") as f:
    zones = json.load(f)

m = folium.Map(location=[32.8, -96.8], zoom_start=9)

for zone in zones:
    folium.Polygon(
        locations=[(lat, lon) for lon, lat in zone["polygon"]],
        popup=zone["name"],
        color="blue",
        fill=True
    ).add_to(m)

m.save("zones_map.html")