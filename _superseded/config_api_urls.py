from django.urls import path

from apps.guardian import api as guardian_api
from apps.safety_plans import api as plan_api

app_name = "api"

urlpatterns = [
    path("plan/health/", plan_api.PlanHealthAPI.as_view(), name="plan_health"),
    path("guardian/activations/", guardian_api.ActivationListCreateAPI.as_view(), name="activations"),
    path("guardian/activations/<uuid:pk>/", guardian_api.ActivationDetailAPI.as_view(), name="activation_detail"),
]
