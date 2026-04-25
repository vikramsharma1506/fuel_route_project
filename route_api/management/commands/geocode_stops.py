import os
import csv
from django.core.management.base import BaseCommand
from route_api.models import TruckStop
from django.db import transaction


class Command(BaseCommand):
    """
    python manage.py geocode_stops

    Uses the local uscities.csv file — ZERO API calls.
    Completes in under 30 seconds for all 8,500+ stops.
    """
    help = 'Add GPS coordinates to all stops using local uscities.csv (no API)'

    def handle(self, *args, **options):

        # ── Find uscities.csv ─────────────────────────────────────────────
        base_dir = os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(__file__)
                )
            )
        )
        csv_path = os.path.join(base_dir, 'uscities.csv')

        if not os.path.exists(csv_path):
            self.stderr.write(self.style.ERROR(
                f'\nuscities.csv not found at: {csv_path}\n\n'
                f'Download the FREE file:\n'
                f'  1. Go to: https://simplemaps.com/data/us-cities\n'
                f'  2. Click "Download Basic (Free)"\n'
                f'  3. Extract the zip\n'
                f'  4. Copy uscities.csv into your project root folder\n'
                f'  5. Run this command again\n'
            ))
            return

        # ── Load all cities into fast lookup dict ─────────────────────────
        self.stdout.write('Loading US cities from local CSV...')
        city_lookup = {}

        with open(csv_path, newline='', encoding='utf-8-sig') as f:
            for row in csv.DictReader(f):
                try:
                    city  = row['city'].strip().lower()
                    state = row['state_id'].strip().upper()
                    lat   = float(row['lat'])
                    lon   = float(row['lng'])

                    # Primary key: "big cabin,OK"
                    city_lookup[f"{city},{state}"] = (lat, lon)

                    # Backup: full state name
                    sname = row.get('state_name', '').strip().lower()
                    if sname:
                        city_lookup[f"{city},{sname}"] = (lat, lon)
                except (ValueError, KeyError):
                    continue

        self.stdout.write(f'  Loaded {len(city_lookup):,} city records.')

        # ── Reset all coordinates ─────────────────────────────────────────
        TruckStop.objects.all().update(latitude=None, longitude=None)
        self.stdout.write('  Reset existing coordinates.')

        # ── Match stops to cities ─────────────────────────────────────────
        all_stops     = list(TruckStop.objects.all())
        total         = len(all_stops)
        updated_stops = []
        not_found     = []

        self.stdout.write(f'  Matching {total:,} stops to coordinates...')

        for stop in all_stops:
            city_key = f"{stop.city.strip().lower()},{stop.state.strip().upper()}"
            coords   = city_lookup.get(city_key)

            if not coords:
                # Fallback: try just city name (first state match)
                city_only = stop.city.strip().lower() + ','
                for k, v in city_lookup.items():
                    if k.startswith(city_only):
                        coords = v
                        break

            if coords:
                stop.latitude, stop.longitude = coords
                updated_stops.append(stop)
            else:
                not_found.append(f"{stop.city}, {stop.state}")

        # ── Bulk update all stops in ONE transaction ──────────────────────
        self.stdout.write(
            f'  Saving {len(updated_stops):,} stops to database...'
        )
        with transaction.atomic():
            TruckStop.objects.bulk_update(
                updated_stops,
                fields=['latitude', 'longitude'],
                batch_size=1000,
            )

        # ── Report ────────────────────────────────────────────────────────
        unique_missing = sorted(set(not_found))
        self.stdout.write(self.style.SUCCESS(
            f'\n✅ Geocoding complete!'
            f'\n   Total stops   : {total:,}'
            f'\n   Updated       : {len(updated_stops):,}'
            f'\n   Not found     : {len(not_found):,}'
            f'\n   Unique missing: {len(unique_missing):,}'
            f'\n   API calls used: 0'
        ))

        if unique_missing:
            self.stdout.write('\nCities without coordinates (first 20):')
            for c in unique_missing[:20]:
                self.stdout.write(f'   • {c}')
