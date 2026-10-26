from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("resources/", views.resources, name="resources"),
    path("offline/", views.offline, name="offline"),
    path("healthz", views.healthz, name="healthz"),
    path("sw.js", views.service_worker, name="sw"),
]
