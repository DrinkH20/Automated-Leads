# from geopy.geocoders import GoogleV3
from geopy.geocoders import Nominatim
from shapely.geometry import Point, Polygon
import xml.etree.ElementTree as ET
import json
# from opencage.geocoder import OpenCageGeocode
from geopy.geocoders import GoogleV3
# latitude, longitude = 0, 0

# Trying to make sure we do not use the city api if not needed
# # def get_city_from_coordinates_google(latitude, longitude):
# #     # Replace with your Google Maps API key
# #     geolocator = GoogleV3(api_key="AIzaSyAzF17u53V310uHFnD0RoCxabjlV0wLYjQ")
# #
# #     # Perform reverse geocoding
# #     location = geolocator.reverse((latitude, longitude), exactly_one=True)
# #
# #     if location:
# #         # Iterate through the address components
# #         for component in location.raw['address_components']:
# #             if 'locality' in component['types']:
# #                 return component['long_name']
# #             if 'administrative_area_level_2' in component['types']:  # County level if city not found
# #                 return component['long_name']
# #             if 'administrative_area_level_1' in component['types']:  # State level
# #                 return component['long_name']
# #
# #     return "Unknown location"


# Untab these if we need the city
def geocode_address_google(address, api_key):
    geolocator = GoogleV3(api_key=api_key)
    location = geolocator.geocode(address)
    if location:
        # city = get_city_from_coordinates_google(location.latitude, location.longitude)
        # print(city, "THIS IS THE ADDY")
        # return location.latitude, location.longitude, city
        return location.latitude, location.longitude
    else:
        return None


# ADD ADDRESS HERE -- This should not be untabbed
# api_key = "AIzaSyAzF17u53V310uHFnD0RoCxabjlV0wLYjQ"  # Replace with your Google API key
# address = "11955 SW Edgewood St, Portland, OR 97225"
# location = geocode_address_google(address, api_key)
#
# if location:
#     latitude, longitude = location
#     print(f"The geocoded coordinates are: Latitude = {latitude}, Longitude = {longitude}")
# else:
#     print("Address could not be geocoded.")


# Next step
def geocode_address(address):
    geolocator = Nominatim(user_agent="geoapiExercises")
    location = geolocator.geocode(address)
    if location:
        # print(get_city_from_coordinates_google(location.latitude, location.longitude), "THIS IS THE ADDY")
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

# Code for updating the map below
# This is code only used for updating the map
# Example usage
# kml_content = """<?xml version="1.0" encoding="UTF-8"?>
# <kml xmlns="http://www.opengis.net/kml/2.2">
#   <Document>
#     <name>testmap</name>
#     <description/>
#     <Style id="icon-1899-0288D1-nodesc-normal">
#       <IconStyle>
#         <color>ffd18802</color>
#         <scale>1</scale>
#         <Icon>
#           <href>https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png</href>
#         </Icon>
#         <hotSpot x="32" xunits="pixels" y="64" yunits="insetPixels"/>
#       </IconStyle>
#       <LabelStyle>
#         <scale>0</scale>
#       </LabelStyle>
#       <BalloonStyle>
#         <text><![CDATA[<h3>$[name]</h3>]]></text>
#       </BalloonStyle>
#     </Style>
#     <Style id="icon-1899-0288D1-nodesc-highlight">
#       <IconStyle>
#         <color>ffd18802</color>
#         <scale>1</scale>
#         <Icon>
#           <href>https://www.gstatic.com/mapspro/images/stock/503-wht-blank_maps.png</href>
#         </Icon>
#         <hotSpot x="32" xunits="pixels" y="64" yunits="insetPixels"/>
#       </IconStyle>
#       <LabelStyle>
#         <scale>1</scale>
#       </LabelStyle>
#       <BalloonStyle>
#         <text><![CDATA[<h3>$[name]</h3>]]></text>
#       </BalloonStyle>
#     </Style>
#     <StyleMap id="icon-1899-0288D1-nodesc">
#       <Pair>
#         <key>normal</key>
#         <styleUrl>#icon-1899-0288D1-nodesc-normal</styleUrl>
#       </Pair>
#       <Pair>
#         <key>highlight</key>
#         <styleUrl>#icon-1899-0288D1-nodesc-highlight</styleUrl>
#       </Pair>
#     </StyleMap>
#     <Style id="line-000000-1200-nodesc-normal">
#       <LineStyle>
#         <color>ff000000</color>
#         <width>1.2</width>
#       </LineStyle>
#       <BalloonStyle>
#         <text><![CDATA[<h3>$[name]</h3>]]></text>
#       </BalloonStyle>
#     </Style>
#     <Style id="line-000000-1200-nodesc-highlight">
#       <LineStyle>
#         <color>ff000000</color>
#         <width>1.8</width>
#       </LineStyle>
#       <BalloonStyle>
#         <text><![CDATA[<h3>$[name]</h3>]]></text>
#       </BalloonStyle>
#     </Style>
#     <StyleMap id="line-000000-1200-nodesc">
#       <Pair>
#         <key>normal</key>
#         <styleUrl>#line-000000-1200-nodesc-normal</styleUrl>
#       </Pair>
#       <Pair>
#         <key>highlight</key>
#         <styleUrl>#line-000000-1200-nodesc-highlight</styleUrl>
#       </Pair>
#     </StyleMap>
#     <Style id="poly-006064-1200-77-normal">
#       <LineStyle>
#         <color>ff646000</color>
#         <width>1.2</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>4d646000</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#     </Style>
#     <Style id="poly-006064-1200-77-highlight">
#       <LineStyle>
#         <color>ff646000</color>
#         <width>1.8</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>4d646000</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#     </Style>
#     <StyleMap id="poly-006064-1200-77">
#       <Pair>
#         <key>normal</key>
#         <styleUrl>#poly-006064-1200-77-normal</styleUrl>
#       </Pair>
#       <Pair>
#         <key>highlight</key>
#         <styleUrl>#poly-006064-1200-77-highlight</styleUrl>
#       </Pair>
#     </StyleMap>
#     <Style id="poly-01579B-1200-77-nodesc-normal">
#       <LineStyle>
#         <color>ff9b5701</color>
#         <width>1.2</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>4d9b5701</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#       <BalloonStyle>
#         <text><![CDATA[<h3>$[name]</h3>]]></text>
#       </BalloonStyle>
#     </Style>
#     <Style id="poly-01579B-1200-77-nodesc-highlight">
#       <LineStyle>
#         <color>ff9b5701</color>
#         <width>1.8</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>4d9b5701</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#       <BalloonStyle>
#         <text><![CDATA[<h3>$[name]</h3>]]></text>
#       </BalloonStyle>
#     </Style>
#     <StyleMap id="poly-01579B-1200-77-nodesc">
#       <Pair>
#         <key>normal</key>
#         <styleUrl>#poly-01579B-1200-77-nodesc-normal</styleUrl>
#       </Pair>
#       <Pair>
#         <key>highlight</key>
#         <styleUrl>#poly-01579B-1200-77-nodesc-highlight</styleUrl>
#       </Pair>
#     </StyleMap>
#     <Style id="poly-0288D1-1200-77-nodesc-normal">
#       <LineStyle>
#         <color>ffd18802</color>
#         <width>1.2</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>4dd18802</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#       <BalloonStyle>
#         <text><![CDATA[<h3>$[name]</h3>]]></text>
#       </BalloonStyle>
#     </Style>
#     <Style id="poly-0288D1-1200-77-nodesc-highlight">
#       <LineStyle>
#         <color>ffd18802</color>
#         <width>1.8</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>4dd18802</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#       <BalloonStyle>
#         <text><![CDATA[<h3>$[name]</h3>]]></text>
#       </BalloonStyle>
#     </Style>
#     <StyleMap id="poly-0288D1-1200-77-nodesc">
#       <Pair>
#         <key>normal</key>
#         <styleUrl>#poly-0288D1-1200-77-nodesc-normal</styleUrl>
#       </Pair>
#       <Pair>
#         <key>highlight</key>
#         <styleUrl>#poly-0288D1-1200-77-nodesc-highlight</styleUrl>
#       </Pair>
#     </StyleMap>
#     <Style id="poly-4E342E-1200-120-normal">
#       <LineStyle>
#         <color>ff2e344e</color>
#         <width>1.2</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>782e344e</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#     </Style>
#     <Style id="poly-4E342E-1200-120-highlight">
#       <LineStyle>
#         <color>ff2e344e</color>
#         <width>1.8</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>782e344e</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#     </Style>
#     <StyleMap id="poly-4E342E-1200-120">
#       <Pair>
#         <key>normal</key>
#         <styleUrl>#poly-4E342E-1200-120-normal</styleUrl>
#       </Pair>
#       <Pair>
#         <key>highlight</key>
#         <styleUrl>#poly-4E342E-1200-120-highlight</styleUrl>
#       </Pair>
#     </StyleMap>
#     <Style id="poly-558B2F-2201-133-normal">
#       <LineStyle>
#         <color>ff2f8b55</color>
#         <width>2.201</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>852f8b55</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#     </Style>
#     <Style id="poly-558B2F-2201-133-highlight">
#       <LineStyle>
#         <color>ff2f8b55</color>
#         <width>3.3015</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>852f8b55</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#     </Style>
#     <StyleMap id="poly-558B2F-2201-133">
#       <Pair>
#         <key>normal</key>
#         <styleUrl>#poly-558B2F-2201-133-normal</styleUrl>
#       </Pair>
#       <Pair>
#         <key>highlight</key>
#         <styleUrl>#poly-558B2F-2201-133-highlight</styleUrl>
#       </Pair>
#     </StyleMap>
#     <Style id="poly-817717-1200-77-normal">
#       <LineStyle>
#         <color>ff177781</color>
#         <width>1.2</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>4d177781</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#     </Style>
#     <Style id="poly-817717-1200-77-highlight">
#       <LineStyle>
#         <color>ff177781</color>
#         <width>1.8</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>4d177781</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#     </Style>
#     <StyleMap id="poly-817717-1200-77">
#       <Pair>
#         <key>normal</key>
#         <styleUrl>#poly-817717-1200-77-normal</styleUrl>
#       </Pair>
#       <Pair>
#         <key>highlight</key>
#         <styleUrl>#poly-817717-1200-77-highlight</styleUrl>
#       </Pair>
#     </StyleMap>
#     <Style id="poly-9C27B0-1200-77-normal">
#       <LineStyle>
#         <color>ffb0279c</color>
#         <width>1.2</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>4db0279c</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#     </Style>
#     <Style id="poly-9C27B0-1200-77-highlight">
#       <LineStyle>
#         <color>ffb0279c</color>
#         <width>1.8</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>4db0279c</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#     </Style>
#     <StyleMap id="poly-9C27B0-1200-77">
#       <Pair>
#         <key>normal</key>
#         <styleUrl>#poly-9C27B0-1200-77-normal</styleUrl>
#       </Pair>
#       <Pair>
#         <key>highlight</key>
#         <styleUrl>#poly-9C27B0-1200-77-highlight</styleUrl>
#       </Pair>
#     </StyleMap>
#     <Style id="poly-B2EBF2-1601-201-normal">
#       <LineStyle>
#         <color>fff2ebb2</color>
#         <width>1.601</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>c9f2ebb2</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#     </Style>
#     <Style id="poly-B2EBF2-1601-201-highlight">
#       <LineStyle>
#         <color>fff2ebb2</color>
#         <width>2.4015</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>c9f2ebb2</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#     </Style>
#     <StyleMap id="poly-B2EBF2-1601-201">
#       <Pair>
#         <key>normal</key>
#         <styleUrl>#poly-B2EBF2-1601-201-normal</styleUrl>
#       </Pair>
#       <Pair>
#         <key>highlight</key>
#         <styleUrl>#poly-B2EBF2-1601-201-highlight</styleUrl>
#       </Pair>
#     </StyleMap>
#     <Style id="poly-BDBDBD-1200-77-normal">
#       <LineStyle>
#         <color>ffbdbdbd</color>
#         <width>1.2</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>4dbdbdbd</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#     </Style>
#     <Style id="poly-BDBDBD-1200-77-highlight">
#       <LineStyle>
#         <color>ffbdbdbd</color>
#         <width>1.8</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>4dbdbdbd</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#     </Style>
#     <StyleMap id="poly-BDBDBD-1200-77">
#       <Pair>
#         <key>normal</key>
#         <styleUrl>#poly-BDBDBD-1200-77-normal</styleUrl>
#       </Pair>
#       <Pair>
#         <key>highlight</key>
#         <styleUrl>#poly-BDBDBD-1200-77-highlight</styleUrl>
#       </Pair>
#     </StyleMap>
#     <Style id="poly-F48FB1-1200-77-normal">
#       <LineStyle>
#         <color>ffb18ff4</color>
#         <width>1.2</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>4db18ff4</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#     </Style>
#     <Style id="poly-F48FB1-1200-77-highlight">
#       <LineStyle>
#         <color>ffb18ff4</color>
#         <width>1.8</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>4db18ff4</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#     </Style>
#     <StyleMap id="poly-F48FB1-1200-77">
#       <Pair>
#         <key>normal</key>
#         <styleUrl>#poly-F48FB1-1200-77-normal</styleUrl>
#       </Pair>
#       <Pair>
#         <key>highlight</key>
#         <styleUrl>#poly-F48FB1-1200-77-highlight</styleUrl>
#       </Pair>
#     </StyleMap>
#     <Style id="poly-F9A825-1200-77-normal">
#       <LineStyle>
#         <color>ff25a8f9</color>
#         <width>1.2</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>4d25a8f9</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#     </Style>
#     <Style id="poly-F9A825-1200-77-highlight">
#       <LineStyle>
#         <color>ff25a8f9</color>
#         <width>1.8</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>4d25a8f9</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#     </Style>
#     <StyleMap id="poly-F9A825-1200-77">
#       <Pair>
#         <key>normal</key>
#         <styleUrl>#poly-F9A825-1200-77-normal</styleUrl>
#       </Pair>
#       <Pair>
#         <key>highlight</key>
#         <styleUrl>#poly-F9A825-1200-77-highlight</styleUrl>
#       </Pair>
#     </StyleMap>
#     <Style id="poly-FF5252-1200-77-normal">
#       <LineStyle>
#         <color>ff5252ff</color>
#         <width>1.2</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>4d5252ff</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#     </Style>
#     <Style id="poly-FF5252-1200-77-highlight">
#       <LineStyle>
#         <color>ff5252ff</color>
#         <width>1.8</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>4d5252ff</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#     </Style>
#     <StyleMap id="poly-FF5252-1200-77">
#       <Pair>
#         <key>normal</key>
#         <styleUrl>#poly-FF5252-1200-77-normal</styleUrl>
#       </Pair>
#       <Pair>
#         <key>highlight</key>
#         <styleUrl>#poly-FF5252-1200-77-highlight</styleUrl>
#       </Pair>
#     </StyleMap>
#     <Style id="poly-FFEA00-1200-77-nodesc-normal">
#       <LineStyle>
#         <color>ff00eaff</color>
#         <width>1.2</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>4d00eaff</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#       <BalloonStyle>
#         <text><![CDATA[<h3>$[name]</h3>]]></text>
#       </BalloonStyle>
#     </Style>
#     <Style id="poly-FFEA00-1200-77-nodesc-highlight">
#       <LineStyle>
#         <color>ff00eaff</color>
#         <width>1.8</width>
#       </LineStyle>
#       <PolyStyle>
#         <color>4d00eaff</color>
#         <fill>1</fill>
#         <outline>1</outline>
#       </PolyStyle>
#       <BalloonStyle>
#         <text><![CDATA[<h3>$[name]</h3>]]></text>
#       </BalloonStyle>
#     </Style>
#     <StyleMap id="poly-FFEA00-1200-77-nodesc">
#       <Pair>
#         <key>normal</key>
#         <styleUrl>#poly-FFEA00-1200-77-nodesc-normal</styleUrl>
#       </Pair>
#       <Pair>
#         <key>highlight</key>
#         <styleUrl>#poly-FFEA00-1200-77-nodesc-highlight</styleUrl>
#       </Pair>
#     </StyleMap>
#     <Folder>
#       <name>Zone 1 and 2 - Washington</name>
#       <Placemark>
#         <name>Zone 1</name>
#         <description><![CDATA[98660<br>98661<br>98663<br>98665<br>98685<br>98686]]></description>
#         <styleUrl>#poly-FF5252-1200-77</styleUrl>
#         <Polygon>
#           <outerBoundaryIs>
#             <LinearRing>
#               <tessellate>1</tessellate>
#               <coordinates>
#                 -122.719737,45.7076028,0
#                 -122.700613,45.6298479,0
#                 -122.5426845,45.5969469,0
#                 -122.5645498,45.6610649,0
#                 -122.5927076,45.7061643,0
#                 -122.719737,45.7076028,0
#               </coordinates>
#             </LinearRing>
#           </outerBoundaryIs>
#         </Polygon>
#       </Placemark>
#       <Placemark>
#         <name>Zone 2</name>
#         <description><![CDATA[98607<br>98683<br>98664<br>98684<br>98682<br>98662]]></description>
#         <styleUrl>#poly-BDBDBD-1200-77</styleUrl>
#         <Polygon>
#           <outerBoundaryIs>
#             <LinearRing>
#               <tessellate>1</tessellate>
#               <coordinates>
#                 -122.5906296,45.7048213,0
#                 -122.5624446,45.6598737,0
#                 -122.5406077,45.5956039,0
#                 -122.4347276,45.5735433,0
#                 -122.3784218,45.5811129,0
#                 -122.3815117,45.6373133,0
#                 -122.439534,45.6853033,0
#                 -122.5906296,45.7048213,0
#               </coordinates>
#             </LinearRing>
#           </outerBoundaryIs>
#         </Polygon>
#       </Placemark>
#       <Placemark>
#         <name>Zone 12</name>
#       </Placemark>
#       <Placemark>
#         <name>Zone 13</name>
#       </Placemark>
#       <Placemark>
#         <name>Zone 12</name>
#         <styleUrl>#poly-FFEA00-1200-77-nodesc</styleUrl>
#         <Polygon>
#           <outerBoundaryIs>
#             <LinearRing>
#               <tessellate>1</tessellate>
#               <coordinates>
#                 -122.7506576,45.8330977,0
#                 -122.7197585,45.7076103,0
#                 -122.5927291,45.7061718,0
#                 -122.6030288,45.813479,0
#                 -122.7506576,45.8330977,0
#               </coordinates>
#             </LinearRing>
#           </outerBoundaryIs>
#         </Polygon>
#       </Placemark>
#       <Placemark>
#         <name>Zone 13</name>
#         <styleUrl>#poly-0288D1-1200-77-nodesc</styleUrl>
#         <Polygon>
#           <outerBoundaryIs>
#             <LinearRing>
#               <tessellate>1</tessellate>
#               <coordinates>
#                 -122.6030127,45.8134715,0
#                 -122.592713,45.7061643,0
#                 -122.483539,45.6921043,0
#                 -122.4543565,45.7342959,0
#                 -122.5017351,45.8094905,0
#                 -122.6030127,45.8134715,0
#               </coordinates>
#             </LinearRing>
#           </outerBoundaryIs>
#         </Polygon>
#       </Placemark>
#       <Placemark>
#         <name>938 SW Shaker Pl</name>
#         <styleUrl>#icon-1899-0288D1-nodesc</styleUrl>
#         <Point>
#           <coordinates>
#             -122.7470069,45.5126899,0
#           </coordinates>
#         </Point>
#       </Placemark>
#       <Placemark>
#         <name>97022</name>
#         <styleUrl>#icon-1899-0288D1-nodesc</styleUrl>
#         <Point>
#           <coordinates>
#             -122.3293482,45.3551259,0
#           </coordinates>
#         </Point>
#       </Placemark>
#       <Placemark>
#         <name>Point 9</name>
#         <styleUrl>#icon-1899-0288D1-nodesc</styleUrl>
#         <Point>
#           <coordinates>
#             -122.8496198,45.5745361,0
#           </coordinates>
#         </Point>
#       </Placemark>
#     </Folder>
#     <Folder>
#       <name>Zone 3, 4, 5, 6</name>
#       <Placemark>
#         <name>Zone 4 - NE Portland</name>
#         <description><![CDATA[97211<br>97218<br>97220<br>972132<br>97212<br>97232<br>97213<br>97214<br>97215<br>97216]]></description>
#         <styleUrl>#poly-558B2F-2201-133</styleUrl>
#         <Polygon>
#           <outerBoundaryIs>
#             <LinearRing>
#               <tessellate>1</tessellate>
#               <coordinates>
#                 -122.6567258,45.6204795,0
#                 -122.6639354,45.5777815,0
#                 -122.6639353,45.5653401,0
#                 -122.6642895,45.5591871,0
#                 -122.6643592,45.5561181,0
#                 -122.6642787,45.5530491,0
#                 -122.6641928,45.5400217,0
#                 -122.6643002,45.535056,0
#                 -122.6635492,45.527926,0
#                 -122.6638302,45.5220091,0
#                 -122.6569832,45.5221444,0
#                 -122.6534213,45.5220917,0
#                 -122.6496018,45.5220088,0
#                 -122.6209131,45.5219412,0
#                 -122.5621404,45.5219788,0
#                 -122.5607672,45.5324415,0
#                 -122.5414394,45.596858,0
#                 -122.6567258,45.6204795,0
#               </coordinates>
#             </LinearRing>
#           </outerBoundaryIs>
#         </Polygon>
#       </Placemark>
#       <Placemark>
#         <name>Zone 6  - SE Portland</name>
#         <description><![CDATA[97214<br>97215<br>97216<br>97202<br>97206<br>97266<br>97222]]></description>
#         <styleUrl>#poly-4E342E-1200-120</styleUrl>
#         <Polygon>
#           <outerBoundaryIs>
#             <LinearRing>
#               <tessellate>1</tessellate>
#               <coordinates>
#                 -122.5645337,45.5226502,0
#                 -122.6656851,45.5228908,0
#                 -122.6642811,45.4729187,0
#                 -122.6505482,45.4447435,0
#                 -122.5617922,45.4153788,0
#                 -122.564199,45.4712292,0
#                 -122.5645815,45.4968495,0
#                 -122.5645337,45.5226502,0
#               </coordinates>
#             </LinearRing>
#           </outerBoundaryIs>
#         </Polygon>
#       </Placemark>
#       <Placemark>
#         <name>Zone 5 - SW Portland</name>
#         <description><![CDATA[97225<br>97221<br>97239<br>97005<br>97008<br>97223<br>97219<br>97035<br>97224]]></description>
#         <styleUrl>#poly-9C27B0-1200-77</styleUrl>
#         <Polygon>
#           <outerBoundaryIs>
#             <LinearRing>
#               <tessellate>1</tessellate>
#               <coordinates>
#                 -122.7066282,45.5488624,0
#                 -122.7921167,45.5139292,0
#                 -122.7866235,45.4467678,0
#                 -122.744738,45.4200254,0
#                 -122.7450813,45.4036364,0
#                 -122.7196755,45.4036364,0
#                 -122.6547875,45.4193025,0
#                 -122.6470687,45.4433249,0
#                 -122.6515316,45.4451915,0
#                 -122.6573658,45.4575636,0
#                 -122.6654364,45.4728852,0
#                 -122.6682782,45.5057913,0
#                 -122.6709174,45.5279927,0
#                 -122.7066282,45.5488624,0
#               </coordinates>
#             </LinearRing>
#           </outerBoundaryIs>
#         </Polygon>
#       </Placemark>
#     </Folder>
#     <Folder>
#       <name>Zone 7,8,9,10,11</name>
#       <Placemark>
#         <name>Zone 8- Happy Valley</name>
#         <description><![CDATA[97266<br>97236<br>97080<br>97086<br>97015]]></description>
#         <styleUrl>#poly-F48FB1-1200-77</styleUrl>
#         <Polygon>
#           <outerBoundaryIs>
#             <LinearRing>
#               <tessellate>1</tessellate>
#               <coordinates>
#                 -122.3865355,45.4967304,0
#                 -122.5641678,45.4971282,0
#                 -122.5604875,45.3962317,0
#                 -122.5252996,45.3951476,0
#                 -122.4787826,45.396353,0
#                 -122.3998255,45.4133459,0
#                 -122.3865355,45.4967304,0
#               </coordinates>
#             </LinearRing>
#           </outerBoundaryIs>
#         </Polygon>
#       </Placemark>
#       <Placemark>
#         <name>Zone 11 Hillsboro, Aloha, Beaverton</name>
#         <description><![CDATA[97124<br>97229<br>97006<br>97007]]></description>
#         <styleUrl>#poly-B2EBF2-1601-201</styleUrl>
#         <Polygon>
#           <outerBoundaryIs>
#             <LinearRing>
#               <tessellate>1</tessellate>
#               <coordinates>
#                 -122.7851974,45.5955959,0
#                 -122.9976143,45.5390053,0
#                 -122.935815,45.4658532,0
#                 -122.859596,45.4249044,0
#                 -122.7877785,45.4476665,0
#                 -122.7920501,45.513963,0
#                 -122.7065617,45.5488962,0
#                 -122.7851974,45.5955959,0
#               </coordinates>
#             </LinearRing>
#           </outerBoundaryIs>
#         </Polygon>
#       </Placemark>
#       <Placemark>
#         <name>Zone 10 - Tigard, Tualatin, Sherwood, Newberg</name>
#         <description><![CDATA[97224<br> 97140<br> 97132]]></description>
#         <styleUrl>#poly-006064-1200-77</styleUrl>
#         <Polygon>
#           <outerBoundaryIs>
#             <LinearRing>
#               <tessellate>1</tessellate>
#               <coordinates>
#                 -122.8601052,45.4245355,0
#                 -122.9814491,45.2891331,0
#                 -122.7644688,45.3475552,0
#                 -122.7441719,45.4038051,0
#                 -122.7438286,45.4201941,0
#                 -122.785714,45.4469365,0
#                 -122.8601052,45.4245355,0
#               </coordinates>
#             </LinearRing>
#           </outerBoundaryIs>
#         </Polygon>
#       </Placemark>
#       <Placemark>
#         <name>Zone 9 - Clackamas, Gladstone, Oregon City, West Linn</name>
#         <description><![CDATA[97015<br>97045<br>97027<br>97267<br>97068<br>97062]]></description>
#         <styleUrl>#poly-F9A825-1200-77</styleUrl>
#         <Polygon>
#           <outerBoundaryIs>
#             <LinearRing>
#               <tessellate>1</tessellate>
#               <coordinates>
#                 -122.7649942,45.3470843,0
#                 -122.7937457,45.3393591,0
#                 -122.7951879,45.2892721,0
#                 -122.553834,45.3206629,0
#                 -122.5623192,45.4149305,0
#                 -122.6461072,45.4430118,0
#                 -122.6539119,45.4189291,0
#                 -122.7187994,45.403263,0
#                 -122.744205,45.403263,0
#                 -122.7649942,45.3470843,0
#               </coordinates>
#             </LinearRing>
#           </outerBoundaryIs>
#         </Polygon>
#       </Placemark>
#       <Placemark>
#         <name>Zone 7</name>
#         <description><![CDATA[97230<br>97024<br>97233<br>97030]]></description>
#         <styleUrl>#poly-817717-1200-77</styleUrl>
#         <Polygon>
#           <outerBoundaryIs>
#             <LinearRing>
#               <tessellate>1</tessellate>
#               <coordinates>
#                 -122.5646027,45.4968345,0
#                 -122.399923,45.4973117,0
#                 -122.3949455,45.5470961,0
#                 -122.5518198,45.5675264,0
#                 -122.5645547,45.5237437,0
#                 -122.5646027,45.4968345,0
#               </coordinates>
#             </LinearRing>
#           </outerBoundaryIs>
#         </Polygon>
#       </Placemark>
#       <Placemark>
#         <name>Zone 3 </name>
#         <styleUrl>#poly-01579B-1200-77-nodesc</styleUrl>
#         <Polygon>
#           <outerBoundaryIs>
#             <LinearRing>
#               <tessellate>1</tessellate>
#               <coordinates>
#                 -122.7630974,45.6453908,0
#                 -122.7678798,45.6456407,0
#                 -122.775408,45.6391697,0
#                 -122.7859971,45.6264651,0
#                 -122.7773052,45.5988952,0
#                 -122.6644018,45.5270586,0
#                 -122.6660715,45.5774255,0
#                 -122.6579217,45.6201526,0
#                 -122.7630974,45.6453908,0
#               </coordinates>
#             </LinearRing>
#           </outerBoundaryIs>
#         </Polygon>
#       </Placemark>
#       <Placemark>
#         <name>Line 7</name>
#         <styleUrl>#line-000000-1200-nodesc</styleUrl>
#         <LineString>
#           <tessellate>1</tessellate>
#           <coordinates>
#             -122.6445017,45.4454857,0
#             -122.6436917,45.4453803,0
#             -122.6431714,45.4455873,0
#           </coordinates>
#         </LineString>
#       </Placemark>
#     </Folder>
#   </Document>
# </kml>"""  # Replace with actual KML content
# zones = parse_kml_elementtree(kml_content)
# with open('zones.json', 'w') as f:
#     json.dump(zones, f)
# The code for updating the map is above


# def parse_kml_elementtree(kml_content):
#     namespaces = {'kml': 'http://www.opengis.net/kml/2.2'}
#     tree = ET.ElementTree(ET.fromstring(kml_content))
#     zones = []
#
#     # Find all Placemark elements
#     for placemark in tree.findall('.//kml:Placemark', namespaces):
#         name = placemark.find('kml:name', namespaces).text
#         polygon_element = placemark.find('.//kml:Polygon', namespaces)
#         if polygon_element is not None:
#             coords_text = polygon_element.find('.//kml:coordinates', namespaces).text.strip()
#             coords = [tuple(map(float, coord.split(',')))[:2] for coord in coords_text.split()]
#             zones.append({
#                 'name': name,
#                 'polygon': coords  # Store as a list of coordinates
#             })
#
    # return zones

# Parse the KML content (only do this once)
# zones = parse_kml_elementtree(kml_content)

# Save the parsed zones to a JSON file
# with open('zones.json', 'w') as f:
#     json.dump(zones, f)
# Code for updating the map is above
def get_zone(address, api_key="AIzaSyAzF17u53V310uHFnD0RoCxabjlV0wLYjQ"):
    city = "city"
    if address:
        with open('zones.json', 'r') as f:
            zones = json.load(f)

        latitude, longitude = 0, 0

        location = geocode_address_google(address, api_key)

        if location:
            # latitude, longitude, city = location
            latitude, longitude = location
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
                try:
                    revised_zone_number = int(zone_name[5:7])
                except ValueError:
                    revised_zone_number = int(zone_name[5:6])
                # print(f"The address '{address}' is in zone {revised_zone_number}")
            else:
                revised_zone_number = "NA"
                print(revised_zone_number)
                # print(f"The address '{address}' is not in any defined zone.")
        else:
            print("Address could not be geocoded.")

        return revised_zone_number, city
    return "No Address Found"
