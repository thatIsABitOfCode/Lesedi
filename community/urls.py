from django.urls import path

from . import views

app_name = "community"

urlpatterns = [
    path("", views.feed, name="feed"),
    path("new/", views.report_new, name="report_new"),
    path("mine/", views.mine, name="mine"),
    path("witness/", views.witness, name="witness"),
    path("moderation/", views.mod_queue, name="mod_queue"),
    path("moderation/witness/", views.mod_witness, name="mod_witness"),
    path("moderation/<uuid:pk>/", views.mod_report, name="mod_report"),
    path("comment/<uuid:pk>/flag/", views.flag_comment, name="flag_comment"),
    path("<uuid:pk>/", views.report_detail, name="report"),
    path("<uuid:pk>/comment/", views.comment_add, name="comment"),
    path("<uuid:pk>/flag/", views.flag_report, name="flag"),
    path("<uuid:pk>/appeal/", views.appeal_view, name="appeal"),
]
