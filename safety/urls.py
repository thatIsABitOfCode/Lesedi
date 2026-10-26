from django.urls import path

from . import views

app_name = "safety"

urlpatterns = [
    path("", views.plan_edit, name="plan"),
    path("health/", views.plan_health, name="health"),
    path("circle/", views.circle, name="circle"),
    path("circle/add/", views.contact_add, name="contact_add"),
    path("circle/<uuid:pk>/", views.contact_detail, name="contact"),
    path("invite/<str:token>/", views.invite_accept, name="invite"),
]
