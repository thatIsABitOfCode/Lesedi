from django.urls import path

from . import views

app_name = "guardian"

urlpatterns = [
    path("", views.guardian_page, name="page"),
    path("ack/<str:token>/", views.ack_page, name="ack"),
]
