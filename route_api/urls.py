from django.urls import path
from route_api.views import FuelRouteView

urlpatterns = [
    path('route/', FuelRouteView.as_view(), name='fuel-route'),
]