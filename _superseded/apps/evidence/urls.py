from django.urls import path

from . import views

app_name = "vault"

urlpatterns = [
    path("", views.home, name="home"),
    path("incidents/new/", views.incident_create, name="incident_create"),
    path("incidents/<uuid:pk>/", views.incident_detail, name="incident"),
    path("incidents/<uuid:pk>/entry/", views.entry_add, name="entry_add"),
    path("incidents/<uuid:pk>/upload/", views.upload, name="upload"),
    path("incidents/<uuid:pk>/export/", views.export, name="export"),
    path("items/<uuid:pk>/download/", views.download, name="download"),
    path("items/<uuid:pk>/delete/", views.item_delete, name="item_delete"),
    path("items/<uuid:pk>/share/", views.share, name="share"),
    path("shares/<uuid:pk>/revoke/", views.share_revoke, name="share_revoke"),
    path("shared/", views.shared_list, name="shared_list"),
    path("shared/<uuid:pk>/download/", views.shared_download, name="shared_download"),
]
