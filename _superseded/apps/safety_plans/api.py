from rest_framework.response import Response
from rest_framework.views import APIView

from . import services
from .models import SafetyPlan


class PlanHealthAPI(APIView):
    """Plan health for the signed-in user only."""

    def get(self, request):
        plan = SafetyPlan.objects.filter(owner=request.user, is_active=True).first()
        if plan is None:
            return Response({"plan": None, "findings": []})
        findings = services.assess_plan_health(plan)
        return Response(
            {
                "plan": {"version": plan.version, "review_due": plan.review_due.isoformat()},
                "findings": [
                    {
                        "code": f.code,
                        "title": f.title,
                        "detail": f.detail,
                        "severity": f.severity,
                        "provenance": f.provenance,
                    }
                    for f in findings
                ],
            }
        )
