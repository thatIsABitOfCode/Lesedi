from django.urls import path

from . import views

app_name = "circle"

urlpatterns = [
    path("", views.circle_list, name="list"),
    path("add/", views.contact_add, name="contact_add"),
    path("alerts/", views.alerts, name="alerts"),
    path("alerts/<uuid:activation_id>/acknowledge/", views.acknowledge, name="acknowledge"),
    path("invite/<str:token>/", views.invite_accept, name="invite_accept"),
    path("<uuid:pk>/", views.contact_edit, name="contact_edit"),
    path("<uuid:pk>/permissions/", views.contact_permissions, name="contact_permissions"),
    path("<uuid:pk>/invite/", views.contact_invite, name="contact_invite"),
    path("<uuid:pk>/remove/", views.contact_remove, name="contact_remove"),
]
