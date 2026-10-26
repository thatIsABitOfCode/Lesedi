from django.urls import path

from . import views

app_name = "shield"

urlpatterns = [path("", views.shield_page, name="page")]
