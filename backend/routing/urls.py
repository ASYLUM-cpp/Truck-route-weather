from django.urls import path

from . import views

urlpatterns = [
    path("health", views.HealthView.as_view(), name="health"),
    path("config", views.ConfigView.as_view(), name="config"),
    path("places", views.PlaceSearchView.as_view(), name="places"),
    path("plan", views.PlanView.as_view(), name="plan"),
    path("heatmap", views.HeatmapView.as_view(), name="heatmap"),
]
