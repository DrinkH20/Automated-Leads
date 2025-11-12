# INSTRUCTIONS

# DOWNLOAD MAP AS KML
# GO TO mapshaper.org AND EXPORT AS TOPOJSON
# PUT IN ON THE BOTTOM OF THE CODE AND CHOOSE A UNIQUE MAP NAME
# RUN AND CHANGE NAME IN THE MAPECODES.PY file

import json


def decode_arcs(arcs, transform):
    scale_x, scale_y = transform["scale"]
    translate_x, translate_y = transform["translate"]

    coordinates = []
    for arc in arcs:
        points = []
        x = y = 0
        for dx, dy in arc:
            x += dx
            y += dy
            lon = x * scale_x + translate_x
            lat = y * scale_y + translate_y
            points.append([lon, lat])
        coordinates.append(points)
    return coordinates


def convert_topojson_to_zones(topojson_path, output_path):
    with open(topojson_path, "r", encoding="utf-8") as f:
        topo = json.load(f)

    transform = topo["transform"]
    arcs = topo["arcs"]
    objects = topo["objects"]

    # Use first object in "objects" dict
    object_data = list(objects.values())[0]
    geometries = object_data["geometries"]

    zones = []

    for geom in geometries:
        zone_name = geom["properties"].get("name", "Unnamed Zone")
        arc_indices = geom["arcs"]

        # Handle MultiPolygon (2D list) vs Polygon (1D list)
        if isinstance(arc_indices[0], list):
            flat_arcs = [arcs[i if i >= 0 else ~i] for i in arc_indices[0]]
        else:
            flat_arcs = [arcs[i if i >= 0 else ~i] for i in arc_indices]

        coords = decode_arcs(flat_arcs, transform)

        # Only use the outer ring for now (first polygon)
        polygon = coords[0]

        zones.append({
            "name": zone_name,
            "polygon": polygon
        })

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(zones, f, indent=2)

    print(f"Converted {len(zones)} zones to '{output_path}'")


# Example usage
convert_topojson_to_zones("DRAFT DFW MAP (1).json", "dfw_zones_output.json")






