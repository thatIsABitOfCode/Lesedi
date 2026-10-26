from django.urls import path

from . import views

app_name = "evidence"

urlpatterns = [
    path("", views.incident_list, name="incidents"),
    path("new/", views.incident_create, name="incident_new"),
    path("<uuid:pk>/", views.incident_detail, name="incident"),
    path("<uuid:pk>/note/", views.add_note, name="note"),
    path("<uuid:pk>/upload/", views.upload, name="upload"),
    path("<uuid:pk>/export/", views.export_pack, name="export"),
    path("item/<uuid:pk>/download/", views.download, name="download"),
    path("item/<uuid:pk>/delete/", views.delete_item, name="delete"),
    path("item/<uuid:pk>/share/", views.share_create, name="share"),
    path("share/<uuid:pk>/revoke/", views.share_revoke, name="share_revoke"),
    path("shared/<str:token>/", views.shared_download, name="shared"),
]
