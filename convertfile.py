import json

with open("dfwzones.json") as f:
    geojson = json.load(f)

converted = []

for feature in geojson["features"]:
    name = feature["properties"]["name"]
    coords = feature["geometry"]["coordinates"][0]  # Unwrap one level
    converted.append({
        "name": name,
        "polygon": coords
    })

with open("dfwzones_converted.json", "w") as f:
    json.dump(converted, f, indent=2)