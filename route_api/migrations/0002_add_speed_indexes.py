from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('route_api', '0001_initial'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='truckstop',
            index=models.Index(
                fields=['latitude', 'longitude', 'retail_price'],
                name='idx_lat_lon_price',
            ),
        ),
        migrations.AddIndex(
            model_name='truckstop',
            index=models.Index(
                fields=['retail_price'],
                name='idx_retail_price',
            ),
        ),
    ]