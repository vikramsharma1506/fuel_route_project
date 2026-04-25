import csv
import os
from django.core.management.base import BaseCommand
from route_api.models import TruckStop


class Command(BaseCommand):
    help = 'Load fuel data from CSV'

    def handle(self, *args, **options):
        base_dir = os.path.dirname(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(__file__)
                )
            )
        )
        csv_path = os.path.join(base_dir, 'fuelprices.csv')

        if not os.path.exists(csv_path):
            self.stderr.write(f'CSV not found at: {csv_path}')
            return

        TruckStop.objects.all().delete()
        stops = []
        skipped = 0

        with open(csv_path, newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    stops.append(TruckStop(
                        opis_id=int(row['OPIS Truckstop ID']),
                        name=row['Truckstop Name'].strip(),
                        address=row['Address'].strip(),
                        city=row['City'].strip(),
                        state=row['State'].strip(),
                        rack_id=int(row['Rack ID']),
                        retail_price=float(row['Retail Price']),
                    ))
                except (ValueError, KeyError):
                    skipped += 1

        TruckStop.objects.bulk_create(stops, batch_size=500)
        self.stdout.write(self.style.SUCCESS(
            f'✅ Loaded {len(stops)} stops. Skipped {skipped}.'
        ))