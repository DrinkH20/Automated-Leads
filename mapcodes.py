from geopy.geocoders import GoogleV3
from geopy.geocoders import Nominatim
from shapely.geometry import Point, Polygon
import xml.etree.ElementTree as ET
import json
from opencage.geocoder import OpenCageGeocode
from geopy.geocoders import GoogleV3
import re
# latitude, longitude = 0, 0


def get_city_from_coordinates_google(latitude, longitude):
    # Replace with your Google Maps API key
    geolocator = GoogleV3(api_key="")

    # Perform reverse geocoding
    location = geolocator.reverse((latitude, longitude), exactly_one=True)

    if location:
        # Iterate through the address components
        for component in location.raw['address_components']:
            if 'locality' in component['types']:
                return component['long_name']
            if 'administrative_area_level_2' in component['types']:  # County level if city not found
                return component['long_name']
            if 'administrative_area_level_1' in component['types']:  # State level
                return component['long_name']

    return "Unknown location"


def geocode_address_google(address, api_key):
    geolocator = GoogleV3(api_key=api_key)
    location = geolocator.geocode(address)
    if location:
        city = get_city_from_coordinates_google(location.latitude, location.longitude)
        print(city, "THIS IS THE ADDY")
        return location.latitude, location.longitude, city
    else:
        return None


# Next step
def geocode_address(address):
    geolocator = Nominatim(user_agent="geoapiExercises")
    location = geolocator.geocode(address)
    if location:
        print(get_city_from_coordinates_google(location.latitude, location.longitude), "THIS IS THE ADDY")
        return location.latitude, location.longitude
    else:
        return None


def parse_kml_elementtree(kml_content):
    namespaces = {'kml': 'http://www.opengis.net/kml/2.2'}
    tree = ET.ElementTree(ET.fromstring(kml_content))
    zones = []

    # Find all Placemark elements
    for placemark in tree.findall('.//kml:Placemark', namespaces):
        name = placemark.find('kml:name', namespaces).text
        polygon_element = placemark.find('.//kml:Polygon', namespaces)
        if polygon_element is not None:
            coords_text = polygon_element.find('.//kml:coordinates', namespaces).text.strip()
            coords = [tuple(map(float, coord.split(',')))[:2] for coord in coords_text.split()]
            polygon = Polygon(coords)
            zones.append({
                'name': name,
                'polygon': polygon
            })

    return zones


def is_point_in_zone(zones, lat, lon):
    point = Point(lon, lat)  # Shapely uses (longitude, latitude)
    for zone in zones:
        if zone['polygon'].contains(point):
            return zone['name']
    return None

def get_zone(address, mrkt, api_key=""):
    city = "city"
    if address:
        if mrkt == "PDX":
            with open('zones_output.json', 'r') as f:
                zones = json.load(f)
        else:
            with open('dfw_zones_output.json', 'r') as f:
                zones = json.load(f)

        latitude, longitude = 0, 0

        location = geocode_address_google(address, api_key)

        if location:
            latitude, longitude, city = location
            # print(f"The geocoded coordinates are: Latitude = {latitude}, Longitude = {longitude}")
        else:
            print("Address could not be geocoded.")

        # Convert the list of coordinates back into Polygon objects
        for zone in zones:
            zone['polygon'] = Polygon(zone['polygon'])

        revised_zone_number = 0
        if location:
            zone_name = is_point_in_zone(zones, latitude, longitude)

            if zone_name:
                # Remove 'far' (case-insensitive) and trim whitespace
                cleaned_zone = re.sub(r'(?i)\bfar\b', '', zone_name).strip()

                # Extract first integer from the zone name
                match = re.search(r'\d+', cleaned_zone)
                if match:
                    revised_zone_number = int(match.group())
                else:
                    revised_zone_number = "NA"
                    print(f"Zone name found but no number extracted: '{zone_name}'")
            else:
                revised_zone_number = "NA"
                print(f"The address is not in any defined zone.")
        else:
            print("Address could not be geocoded.")

        return revised_zone_number, city
    return "No Address Found"
