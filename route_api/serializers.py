from rest_framework import serializers
from route_api.models import TruckStop


class TruckStopSerializer(serializers.ModelSerializer):
    class Meta:
        model = TruckStop
        fields = ['id', 'name', 'address', 'city', 'state',
                  'retail_price', 'latitude', 'longitude']


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(max_length=200, allow_blank=False)
    finish = serializers.CharField(max_length=200, allow_blank=False)