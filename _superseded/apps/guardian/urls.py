from django.urls import path

from . import views

app_name = "guardian"

urlpatterns = [
    path("", views.home, name="home"),
    path("activate/", views.activate, name="activate"),
    path("<uuid:pk>/", views.detail, name="detail"),
    path("<uuid:pk>/escalate/", views.escalate, name="escalate"),
    path("<uuid:pk>/close/", views.close, name="close"),
    path("<uuid:pk>/simulate/time/", views.simulate_time, name="simulate_time"),
    path("<uuid:pk>/simulate/receipts/", views.simulate_receipts, name="simulate_receipts"),
]
