import os
import csv
import math
import time
import requests
from functools import lru_cache
from django.db import connection

# ═══════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════
MAX_RANGE_MILES   = 500    # Full tank range
MPG               = 10     # Miles per gallon
TANK_GALLONS      = MAX_RANGE_MILES / MPG   # 50 gallons
REFUEL_INTERVAL   = 450    # Refuel every 450 miles (50-mile safety buffer)
SEARCH_RADIUS     = 35     # Miles off-route to search for a station

ORS_API_KEY = os.getenv('ORS_API_KEY', '')
ORS_BASE    = 'https://api.openrouteservice.org'

# ═══════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL CACHE  (loaded ONCE when Django starts, reused every request)
# ═══════════════════════════════════════════════════════════════════════════
_city_cache: dict = {}   # "new york,ny" → (lat, lon)
_cache_loaded: bool = False


def _load_city_cache() -> None:
    """
    Load uscities.csv into memory ONE time at server startup.
    After that every geocode lookup is a simple dict key lookup — O(1), instant.
    """
    global _city_cache, _cache_loaded
    if _cache_loaded:
        return

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    csv_path = os.path.join(base_dir, 'uscities.csv')

    if not os.path.exists(csv_path):
        _cache_loaded = True
        return

    with open(csv_path, newline='', encoding='utf-8-sig') as f:
        for row in csv.DictReader(f):
            try:
                city  = row['city'].strip().lower()
                state = row['state_id'].strip().upper()
                lat   = float(row['lat'])
                lon   = float(row['lng'])
                _city_cache[f"{city},{state}"] = (lat, lon)


                sname = row.get('state_name', '').strip().lower()
                if sname:
                    _city_cache[f"{city},{sname}"] = (lat, lon)
            except (ValueError, KeyError):
                continue

    _cache_loaded = True


# ═══════════════════════════════════════════════════════════════════════════
# FAST GEOCODING  — local CSV first, ORS API only as last resort
# ═══════════════════════════════════════════════════════════════════════════
def geocode_location(place_name: str) -> tuple:
    """
    Convert 'Chicago, IL' → (41.878, -87.629)

    Speed strategy:
      1. O(1) dict lookup in local city cache  (instant, 0 API calls)
      2. Only falls back to ORS if city truly not in CSV
    """
    _load_city_cache()

   
    parts = [p.strip() for p in place_name.split(',')]
    city  = parts[0].lower()

    if len(parts) >= 2:
        state = parts[1].strip()
        # Try "city,STATE_ABBR"  then  "city,state full name"
        for state_key in (state.upper(), state.lower()):
            coords = _city_cache.get(f"{city},{state_key}")
            if coords:
                return coords

    # Partial match — city only (first hit wins)
    prefix = city + ','
    for key, coords in _city_cache.items():
        if key.startswith(prefix):
            return coords

    # ── Last resort: ORS Geocoding API (1 extra call) ────────────────────
    if not ORS_API_KEY:
        raise ValueError(
            f"'{place_name}' not found in local city database. "
            "Add ORS_API_KEY to .env for fallback geocoding."
        )

    resp = requests.get(
        f'{ORS_BASE}/geocode/search',
        params={
            'api_key': ORS_API_KEY,
            'text': place_name + ', USA',
            'size': 1,
            'boundary.country': 'US',
        },
        timeout=10,
    )
    resp.raise_for_status()
    features = resp.json().get('features', [])
    if not features:
        raise ValueError(
            f"Location not found: '{place_name}'. "
            "Try 'City, ST' format, e.g. 'Chicago, IL'."
        )
    c = features[0]['geometry']['coordinates']
    return (c[1], c[0])   # (lat, lon)


# ═══════════════════════════════════════════════════════════════════════════
# ROUTING  — exactly ONE call to ORS Directions
# ═══════════════════════════════════════════════════════════════════════════
def get_route(start_coords: tuple, end_coords: tuple) -> dict:
    """
    ONE call to ORS driving-car directions.
    Returns distance_miles, sampled waypoints, and encoded geometry.

    Waypoint sampling: we only keep every Nth point so downstream
    fuel-stop search loops over ~200 points instead of 10,000+.
    """
    resp = requests.post(
        f'{ORS_BASE}/v2/directions/driving-car',
        headers={
            'Authorization': ORS_API_KEY,
            'Content-Type': 'application/json',
        },
        json={
            'coordinates': [
                [start_coords[1], start_coords[0]],   # ORS wants [lon, lat]
                [end_coords[1],   end_coords[0]],
            ],
            'geometry':     True,
            'instructions': False,
        },
        timeout=20,
    )
    resp.raise_for_status()

    route          = resp.json()['routes'][0]
    distance_miles = route['summary']['distance'] / 1609.34
    geometry       = route['geometry']

    # Decode full polyline
    all_waypoints = _decode_polyline(geometry)

    # ── Smart sampling ────────────────────────────────────────────────────
    # Keep only every Nth point so we have ~200 checkpoints maximum.
    # This makes the fuel-stop loop 50× faster on long routes.
    n = max(1, len(all_waypoints) // 200)
    sampled = all_waypoints[::n]
    # Always include the last point
    if sampled[-1] != all_waypoints[-1]:
        sampled.append(all_waypoints[-1])

    return {
        'distance_miles': round(distance_miles, 2),
        'waypoints':      sampled,
        'geometry':       geometry,
    }


# ═══════════════════════════════════════════════════════════════════════════
# POLYLINE DECODER
# ═══════════════════════════════════════════════════════════════════════════
def _decode_polyline(encoded: str) -> list:
    """Standard Google encoded-polyline decoder → list of (lat, lon)."""
    points = []
    index = lat = lng = 0
    while index < len(encoded):
        for is_lng in (False, True):
            shift = result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1f) << shift
                shift  += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if (result & 1) else (result >> 1)
            if is_lng:
                lng += delta
            else:
                lat += delta
        points.append((lat / 1e5, lng / 1e5))
    return points


# ═══════════════════════════════════════════════════════════════════════════
# DISTANCE HELPER
# ═══════════════════════════════════════════════════════════════════════════
def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance in miles between two GPS points."""
    R    = 3958.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dp   = math.radians(lat2 - lat1)
    dl   = math.radians(lon2 - lon1)
    a    = math.sin(dp / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ═══════════════════════════════════════════════════════════════════════════
# FUEL STOP FINDER  — single raw SQL query per stop (fastest possible)
# ═══════════════════════════════════════════════════════════════════════════
def _find_cheapest_stop_sql(lat: float, lon: float, radius_miles: float):
    """
    Uses a SINGLE raw SQL query to:
      1. Filter by bounding box  (uses DB index → very fast)
      2. Sort by retail_price ASC
      3. Return only the TOP 20 cheapest candidates
    Then does haversine check in Python on those 20 rows only.

    This is 100× faster than loading all candidates into Django ORM objects.
    """
    lat_d = radius_miles / 69.0
    lon_d = radius_miles / (69.0 * math.cos(math.radians(lat)))

    sql = """
        SELECT id, name, address, city, state, retail_price, latitude, longitude
        FROM truck_stops
        WHERE latitude  IS NOT NULL
          AND latitude  BETWEEN %s AND %s
          AND longitude BETWEEN %s AND %s
        ORDER BY retail_price ASC
        LIMIT 20
    """
    params = (
        lat - lat_d, lat + lat_d,
        lon - lon_d, lon + lon_d,
    )

    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()

    # Haversine filter on the tiny result set
    for row in rows:
        row_lat, row_lon = row[6], row[7]
        if haversine(lat, lon, row_lat, row_lon) <= radius_miles:
            return row   # First match is already the cheapest (ORDER BY price)

    return None


# ═══════════════════════════════════════════════════════════════════════════
# OPTIMAL FUEL STOPS
# ═══════════════════════════════════════════════════════════════════════════
def find_optimal_fuel_stops(waypoints: list, total_distance_miles: float) -> list:
    """
    Walk the (sampled) route waypoints.
    Every REFUEL_INTERVAL miles, find the cheapest nearby station using
    a single raw SQL query.

    Speed gains:
    - Sampled waypoints: ~200 points instead of 10,000+
    - Raw SQL with bounding box: single indexed query per stop
    - Returns cheapest directly from SQL ORDER BY
    """
    if total_distance_miles <= MAX_RANGE_MILES:
        return []   # Fits in one tank — no stops needed

    # Build cumulative distance list for sampled waypoints
    cumulative = [0.0]
    for i in range(1, len(waypoints)):
        d = haversine(*waypoints[i - 1], *waypoints[i])
        cumulative.append(cumulative[-1] + d)

    fuel_stops   = []
    last_fill_km = 0.0

    for i in range(1, len(waypoints) - 1):
        if cumulative[i] - last_fill_km >= REFUEL_INTERVAL:
            lat, lon = waypoints[i]
            row = _find_cheapest_stop_sql(lat, lon, SEARCH_RADIUS)

            if row:
                fuel_stops.append({
                    'id':           row[0],
                    'name':         row[1],
                    'address':      row[2],
                    'city':         row[3],
                    'state':        row[4],
                    'retail_price': float(row[5]),
                    'latitude':     row[6],
                    'longitude':    row[7],
                })
                last_fill_km = cumulative[i]

    return fuel_stops


# ═══════════════════════════════════════════════════════════════════════════
# COST CALCULATOR
# ═══════════════════════════════════════════════════════════════════════════
def calculate_fuel_cost(fuel_stops: list, total_distance_miles: float) -> dict:
    """
    Total gallons = total_miles / MPG
    Cost = gallons distributed evenly across stops × price at each stop.
    """
    total_gallons = total_distance_miles / MPG

    if not fuel_stops:
        return {
            'total_gallons':  round(total_gallons, 2),
            'total_cost_usd': None,
            'note': 'Trip under 500 miles — fits in one tank.',
        }

    gallons_per_stop = total_gallons / len(fuel_stops)
    total_cost       = sum(s['retail_price'] * gallons_per_stop for s in fuel_stops)

    return {
        'total_gallons':    round(total_gallons,    2),
        'total_cost_usd':   round(total_cost,       2),
        'gallons_per_stop': round(gallons_per_stop, 2),
        'stops_count':      len(fuel_stops),
    }
