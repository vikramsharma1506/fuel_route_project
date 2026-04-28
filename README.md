# ⛽ Fuel Route API

Engineered a high-performance REST API that computes optimal fuel stops across any US driving route, querying 8,151 real stations from a PostgreSQL database to identify the cheapest refueling points within range. Optimized response time to under 3 seconds through spatial indexing, local geocoding with zero external API dependency, and smart waypoint sampling — making exactly one routing API call per request.

---

## 🎯 What It Does

Given a **start** and **finish** location anywhere in the USA, the API:

1. Converts both locations to GPS coordinates.
2. Gets the full driving route with **one single API call**
3. Scans **8,151 real fuel stations** from the provided dataset
4. Finds the **cheapest station** every 450 miles along the route
5. Returns the complete trip cost breakdown

---

## 🚀 Live Demo

**Endpoint:** `POST /api/route/`

**Request:**
```json
{
    "start": "New York, NY",
    "finish": "Los Angeles, CA"
}
```

**Response:**
```json
{
    "route": {
        "start": {
            "name": "New York, NY",
            "latitude": 40.7128,
            "longitude": -74.0060
        },
        "finish": {
            "name": "Los Angeles, CA",
            "latitude": 34.0522,
            "longitude": -118.2437
        },
        "distance_miles": 2794.52,
        "map_geometry": "encoded_polyline_string..."
    },
    "fuel_stops": [
        {
            "id": 423,
            "name": "PILOT TRAVEL CENTER #148",
            "address": "I-70, EXIT 301",
            "city": "Salina",
            "state": "KS",
            "retail_price": "2.98900",
            "latitude": 38.8402,
            "longitude": -97.6114
        }
    ],
    "fuel_stops_count": 5,
    "fuel_cost": {
        "total_gallons": 279.45,
        "total_cost_usd": 843.28,
        "gallons_per_stop": 55.89,
        "stops_count": 5
    },
    "vehicle_assumptions": {
        "max_range_miles": 500,
        "mpg": 10,
        "tank_size_gallons": 50,
        "refuel_interval_miles": 450
    },
    "performance": {
        "total_seconds": 1.8,
        "geocoding_seconds": 0.001,
        "routing_seconds": 1.7,
        "db_search_seconds": 0.05,
        "routing_api_calls": 1
    }
}
```

---

## 🛠️ Tech Stack

| Technology | Purpose |
|---|---|
| **Django 5** | Web framework |
| **Django REST Framework** | API building |
| **PostgreSQL 16** | Database for 8,151 fuel stations |
| **psycopg2** | PostgreSQL connector |
| **OpenRouteService API** | Driving route (1 call per request) |
| **uscities.csv** | Local US city geocoding (0 API calls) |
| **Python 3.11+** | Language |

---

## ⚡ Performance Design

The API is optimized for speed at every step:

| Step | Strategy | Time |
|---|---|---|
| Geocoding start/finish | Local CSV dict lookup — O(1) | ~0.001s |
| Getting the route | Single ORS API call | ~1.5–2s |
| Finding fuel stops | Raw SQL with spatial index | ~0.05s |
| **Total response** | | **~1.5–3s** |

### Key Optimizations
- **Local geocoding** — 30,000+ US cities loaded into memory at startup, zero API calls for city lookups
- **Waypoint sampling** — only checks ~200 points along the route instead of 10,000+
- **Raw SQL queries** — bounding box filter with composite index `(latitude, longitude, retail_price)` makes each stop search instant
- **Bulk operations** — CSV loading uses `bulk_create` with batch size 500
- **Exactly 1 routing API call** per request — meets the brief requirement

---

## 📁 Project Structure

```
fuel_route_project/
├── fuel_project/
│   ├── settings.py          ← Database config, installed apps
│   └── urls.py              ← Main URL router
├── route_api/
│   ├── migrations/
│   │   ├── 0001_initial.py
│   │   └── 0002_add_speed_indexes.py   ← Composite spatial index
│   ├── management/
│   │   └── commands/
│   │       ├── load_fuel_data.py       ← Imports fuelprices.csv
│   │       └── geocode_stops.py        ← Adds GPS coords from uscities.csv
│   ├── models.py            ← TruckStop database model
│   ├── serializers.py       ← Request/response formatting
│   ├── views.py             ← API endpoint logic
│   ├── urls.py              ← App-level URL patterns
│   └── route_logic.py       ← Core: geocoding, routing, fuel stop finder
├── fuelprices.csv           ← 8,151 US fuel stations (provided dataset)
├── manage.py
└── README.md
```

---

## 🗄️ Database Model

```python
class TruckStop(models.Model):
    opis_id       = IntegerField()       # Station ID
    name          = CharField()          # Station name
    address       = CharField()          # Street address
    city          = CharField()          # City
    state         = CharField()          # State abbreviation
    rack_id       = IntegerField()       # Rack ID
    retail_price  = DecimalField()       # Price per gallon
    latitude      = FloatField()         # GPS latitude  (added via geocode)
    longitude     = FloatField()         # GPS longitude (added via geocode)
```

---

## 🔧 Local Setup

### Prerequisites
- Python 3.11+
- PostgreSQL 16
- Git

### 1. Clone the repository
```bash
git clone https://github.com/YOUR_USERNAME/fuel-route-api.git
cd fuel-route-api
```

### 2. Create virtual environment
```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac/Linux
```

### 3. Install dependencies
```bash
pip install django djangorestframework psycopg2-binary requests python-dotenv
```

### 4. Create PostgreSQL database
```sql
CREATE DATABASE fuel_route_db;
CREATE USER fuel_user WITH PASSWORD 'yourpassword';
GRANT ALL PRIVILEGES ON DATABASE fuel_route_db TO fuel_user;
\c fuel_route_db
GRANT ALL ON SCHEMA public TO fuel_user;
ALTER SCHEMA public OWNER TO fuel_user;
```

### 5. Create .env file
```env
DB_NAME=fuel_route_db
DB_USER=fuel_user
DB_PASSWORD=yourpassword
DB_HOST=localhost
DB_PORT=5432
ORS_API_KEY=your_openrouteservice_key
```

### 6. Download uscities.csv
Download the free US cities dataset from [simplemaps.com/data/us-cities](https://simplemaps.com/data/us-cities) and place `uscities.csv` in the project root.

### 7. Run setup commands
```bash
python manage.py migrate
python manage.py load_fuel_data
python manage.py geocode_stops
python manage.py runserver
```

### 8. Test the API
```bash
POST http://127.0.0.1:8000/api/route/
Content-Type: application/json

{
    "start": "Chicago, IL",
    "finish": "Houston, TX"
}
```

---

## 🔑 API Reference

### POST /api/route/

**Request Body**

| Field | Type | Required | Example |
|---|---|---|---|
| `start` | string | ✅ Yes | `"New York, NY"` |
| `finish` | string | ✅ Yes | `"Los Angeles, CA"` |

**Response Fields**

| Field | Type | Description |
|---|---|---|
| `route.distance_miles` | float | Total driving distance |
| `route.map_geometry` | string | Encoded polyline for map rendering |
| `fuel_stops` | array | Cheapest stations along the route |
| `fuel_stops_count` | integer | Number of stops needed |
| `fuel_cost.total_cost_usd` | float | Total fuel cost in USD |
| `fuel_cost.total_gallons` | float | Total gallons needed |
| `performance.total_seconds` | float | API response time |
| `performance.routing_api_calls` | integer | Always 1 |

**Status Codes**

| Code | Meaning |
|---|---|
| `200 OK` | Success |
| `400 Bad Request` | Invalid or empty input |
| `500 Internal Server Error` | Routing API error |

---

## 🚗 Vehicle Assumptions

As specified in the assessment brief:

| Parameter | Value |
|---|---|
| Maximum range | 500 miles |
| Fuel efficiency | 10 MPG |
| Tank size | 50 gallons |
| Refuel interval | Every 450 miles (50-mile safety buffer) |
| Search radius | 35 miles off-route per stop |

---

## 📊 Fuel Data

- **Source:** Provided assessment dataset (`fuelprices.csv`)
- **Total stations:** 8,151
- **Coverage:** All US states
- **Price format:** Retail price per gallon (USD)

---

## 🗺️ Routing API

- **Provider:** [OpenRouteService](https://openrouteservice.org/) (free tier)
- **Calls per request:** Exactly **1** (POST /v2/directions/driving-car)
- **Free tier:** 2,000 requests/day

---

## 👤 Author

-Vikram Krishna Sharma
