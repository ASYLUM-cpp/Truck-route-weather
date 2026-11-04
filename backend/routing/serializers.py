"""Request validation."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from .domain.geo import haversine_mi

# Planning allows a short grace period so a form left open for a few minutes still works.
PLAN_DEPARTURE_GRACE = timedelta(minutes=10)
# The corridor forecast is requested after a plan and may be retried later, so it accepts older departures.
HEATMAP_DEPARTURE_GRACE = timedelta(hours=12)
MAX_PATH_POINTS = 6000


def _check_departure(value, grace: timedelta):
    now = timezone.now()
    if value < now - grace:
        raise serializers.ValidationError("Departure time is in the past.")
    if value > now + timedelta(days=settings.MAX_DEPARTURE_DAYS):
        raise serializers.ValidationError(
            f"Choose a departure within the next {settings.MAX_DEPARTURE_DAYS} days, "
            "the range covered by hourly forecasts."
        )
    return value


def validate_plan_departure(value):
    return _check_departure(value, PLAN_DEPARTURE_GRACE)


def validate_heatmap_departure(value):
    return _check_departure(value, HEATMAP_DEPARTURE_GRACE)


def validate_load(value):
    if value > settings.MAX_LOAD_LB:
        raise serializers.ValidationError(f"Cargo weight cannot exceed {settings.MAX_LOAD_LB:,} lb.")
    return value


class PointSerializer(serializers.Serializer):
    lat = serializers.FloatField(min_value=-90, max_value=90)
    lon = serializers.FloatField(min_value=-180, max_value=180)


class PlanRequestSerializer(serializers.Serializer):
    origin = PointSerializer()
    destination = PointSerializer()
    departure = serializers.DateTimeField(validators=[validate_plan_departure])
    load_lb = serializers.FloatField(min_value=0, validators=[validate_load])

    def validate(self, attrs):
        o, d = attrs["origin"], attrs["destination"]
        if haversine_mi((o["lat"], o["lon"]), (d["lat"], d["lon"])) < 1:
            raise serializers.ValidationError(
                {"destination": "Origin and destination must be at least 1 mile apart."}
            )
        return attrs


class CoordinateField(serializers.ListField):
    child = serializers.FloatField()
    min_length = 2
    max_length = 2


class HeatmapRequestSerializer(serializers.Serializer):
    paths = serializers.ListField(
        child=serializers.ListField(child=CoordinateField(), min_length=2, max_length=MAX_PATH_POINTS),
        min_length=1,
        max_length=3,
    )
    departure = serializers.DateTimeField(validators=[validate_heatmap_departure])
    load_lb = serializers.FloatField(min_value=0, validators=[validate_load])

    def validate_paths(self, paths):
        for path in paths:
            for lon, lat in path:
                if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                    raise serializers.ValidationError("Coordinates must be [lon, lat] in degrees.")
        return paths
