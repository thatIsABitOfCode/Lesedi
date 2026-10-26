from django.urls import path

from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.landing, name="landing"),
    path("home/", views.home, name="home"),
    path("recognise/", views.recognise, name="recognise"),
    path("support/", views.support, name="support"),
    path("privacy/", views.privacy, name="privacy"),
    path("offline/", views.offline, name="offline"),
    path("healthz/", views.healthz, name="healthz"),
    path("sw.js", views.service_worker, name="service_worker"),
    path("manifest.webmanifest", views.manifest, name="manifest"),
]
