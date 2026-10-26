from django.urls import path

from . import views

app_name = "shield"

urlpatterns = [
    path("", views.assess, name="assess"),
]
