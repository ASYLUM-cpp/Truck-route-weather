"""HTTP endpoints. Views validate input and delegate to the services layer."""

from __future__ import annotations

import logging

from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.views import exception_handler as drf_exception_handler

from .serializers import HeatmapRequestSerializer, PlanRequestSerializer, PointSerializer
from .services import tomtom, weather
from .services.heatmap import corridor_heatmap
from .services.planner import TripRequest, plan_trip

logger = logging.getLogger(__name__)


def exception_handler(exc, context):
    """Map upstream failures to clear JSON errors; everything else uses DRF's defaults."""
    if isinstance(exc, tomtom.NoRouteFound):
        return Response({"detail": str(exc)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
    if isinstance(exc, (tomtom.TomTomError, weather.WeatherError)):
        return Response({"detail": str(exc)}, status=status.HTTP_502_BAD_GATEWAY)
    return drf_exception_handler(exc, context)


class HealthView(APIView):
    throttle_classes: list = []

    def get(self, request):
        return Response({"status": "ok", "version": settings.APP_VERSION})


class ConfigView(APIView):
    throttle_classes: list = []

    def get(self, request):
        return Response(
            {
                "truck_tare_lb": settings.TRUCK_TARE_LB,
                "max_load_lb": settings.MAX_LOAD_LB,
                "max_departure_days": settings.MAX_DEPARTURE_DAYS,
            }
        )


class PlaceSearchView(APIView):
    throttle_scope = "places"

    def get(self, request):
        query = request.query_params.get("q", "").strip()
        if len(query) < 2:
            return Response({"results": []})
        return Response({"results": tomtom.search_places(query[:120])})


class ReverseGeocodeView(APIView):
    throttle_scope = "places"

    def get(self, request):
        s = PointSerializer(data=request.query_params)
        s.is_valid(raise_exception=True)
        place = tomtom.reverse_geocode(s.validated_data["lat"], s.validated_data["lon"])
        return Response({"result": place})


class PlanView(APIView):
    throttle_scope = "plan"

    def post(self, request):
        s = PlanRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        trip = TripRequest(
            origin=(data["origin"]["lat"], data["origin"]["lon"]),
            destination=(data["destination"]["lat"], data["destination"]["lon"]),
            departure=data["departure"],
            load_lb=data["load_lb"],
        )
        return Response(plan_trip(trip))


class HeatmapView(APIView):
    throttle_scope = "heatmap"

    def post(self, request):
        s = HeatmapRequestSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        data = s.validated_data
        paths = [[(lat, lon) for lon, lat in path] for path in data["paths"]]
        return Response(corridor_heatmap(paths, data["departure"], data["load_lb"]))
