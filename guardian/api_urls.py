from django.urls import path

from . import api

app_name = "guardian_api"

urlpatterns = [
    path("activate/", api.ActivateView.as_view(), name="activate"),
    path("current/", api.CurrentView.as_view(), name="current"),
    path("<uuid:pk>/", api.DetailView.as_view(), name="detail"),
    path("<uuid:pk>/resolve/", api.ActionView.as_view(action="resolve"), name="resolve"),
    path("<uuid:pk>/cancel/", api.ActionView.as_view(action="cancel"), name="cancel"),
    path("<uuid:pk>/simulate-timeout/", api.ActionView.as_view(action="simulate-timeout"), name="simulate_timeout"),
]
