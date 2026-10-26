from django.urls import path

from . import views

app_name = "plans"

urlpatterns = [
    path("", views.plan_edit, name="edit"),
    path("health/", views.plan_health, name="health"),
    path("history/", views.plan_history, name="history"),
    path("responders/", views.responders, name="responders"),
    path("responders/<int:pk>/remove/", views.responder_remove, name="responder_remove"),
    path("review/", views.plan_review, name="review"),
    path("deactivate/", views.plan_deactivate, name="deactivate"),
]
