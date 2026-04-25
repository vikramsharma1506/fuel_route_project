import time
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from route_api.serializers import RouteRequestSerializer
from route_api import route_logic


class FuelRouteView(APIView):
    """
    POST /api/route/

    Request body:
        { "start": "New York, NY", "finish": "Los Angeles, CA" }

    Response:
        {
            "route":             { start, finish, distance_miles, map_geometry },
            "fuel_stops":        [ array of cheapest stops along the route ],
            "fuel_stops_count":  integer,
            "fuel_cost":         { total_gallons, total_cost_usd, ... },
            "vehicle":           { assumptions },
            "performance":       { time_taken_seconds }
        }

    Speed design:
        - geocode_location()  → O(1) dict lookup (local CSV, loaded once at startup)
        - get_route()         → exactly 1 ORS API call
        - find_optimal_*()    → raw SQL bounding-box query per stop, ~200 waypoint samples
        - Total response time → typically 1–3 seconds
    """

    def post(self, request):
        t_start = time.perf_counter()

        # ── 1. Validate input ─────────────────────────────────────────────
        serializer = RouteRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {'error': 'Invalid input.', 'details': serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        start_name  = serializer.validated_data['start']
        finish_name = serializer.validated_data['finish']

        try:
            # ── 2. Geocode both locations (local CSV — no API call) ───────
            t0 = time.perf_counter()
            start_coords  = route_logic.geocode_location(start_name)
            finish_coords = route_logic.geocode_location(finish_name)
            t_geocode = round(time.perf_counter() - t0, 3)

            # ── 3. Get driving route — ONE ORS API call ───────────────────
            t0 = time.perf_counter()
            route_data = route_logic.get_route(start_coords, finish_coords)
            t_routing  = round(time.perf_counter() - t0, 3)


            t0 = time.perf_counter()
            fuel_stops = route_logic.find_optimal_fuel_stops(
                route_data['waypoints'],
                route_data['distance_miles'],
            )
            t_stops = round(time.perf_counter() - t0, 3)

            # ── 5. Calculate cost ─────────────────────────────────────────
            cost_info = route_logic.calculate_fuel_cost(
                fuel_stops,
                route_data['distance_miles'],
            )

            total_time = round(time.perf_counter() - t_start, 3)

            # ── 6. Build response ─────────────────────────────────────────
            return Response(
                {
                    'route': {
                        'start': {
                            'name':      start_name,
                            'latitude':  start_coords[0],
                            'longitude': start_coords[1],
                        },
                        'finish': {
                            'name':      finish_name,
                            'latitude':  finish_coords[0],
                            'longitude': finish_coords[1],
                        },
                        'distance_miles': route_data['distance_miles'],
                        'map_geometry':   route_data['geometry'],
                    },
                    'fuel_stops':       fuel_stops,
                    'fuel_stops_count': len(fuel_stops),
                    'fuel_cost':        cost_info,
                    'vehicle': {
                        'max_range_miles':      500,
                        'mpg':                  10,
                        'tank_size_gallons':    50,
                        'refuel_interval_miles': 450,
                    },
                    'performance': {
                        'total_seconds':   total_time,
                        'geocoding_seconds': t_geocode,
                        'routing_seconds':   t_routing,
                        'db_search_seconds': t_stops,
                        'routing_api_calls': 1,
                    },
                },
                status=status.HTTP_200_OK,
            )

        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            return Response(
                {'error': 'Server error.', 'details': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
