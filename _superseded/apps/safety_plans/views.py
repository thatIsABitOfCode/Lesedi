from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import services
from .forms import ResponderForm, SafetyPlanForm
from .models import ResponderAssignment, SafetyPlan


def _active_plan(user):
    return SafetyPlan.objects.filter(owner=user, is_active=True).first()


@login_required
def plan_edit(request):
    plan = _active_plan(request.user)
    form = SafetyPlanForm(request.POST or None, instance=plan)
    if request.method == "POST" and form.is_valid():
        plan = services.save_plan(request.user, plan, form.cleaned_data)
        messages.success(request, "Your plan was saved. A copy of this version is kept in your history.")
        return redirect("plans:health")
    return render(request, "plans/plan_form.html", {"form": form, "plan": plan})


@login_required
def plan_health(request):
    plan = _active_plan(request.user)
    if plan is None:
        return render(request, "plans/health.html", {"plan": None, "findings": []})
    findings = services.assess_plan_health(plan)
    return render(
        request,
        "plans/health.html",
        {
            "plan": plan,
            "findings": findings,
            "attention": [f for f in findings if f.severity == "attention"],
            "suggestions": [f for f in findings if f.severity == "suggestion"],
        },
    )


@login_required
def plan_history(request):
    plan = _active_plan(request.user) or SafetyPlan.objects.filter(owner=request.user).order_by("-updated_at").first()
    versions = plan.versions.select_related("changed_by") if plan else []
    return render(request, "plans/history.html", {"plan": plan, "versions": versions})


@login_required
def responders(request):
    plan = _active_plan(request.user)
    if plan is None:
        messages.info(request, "Create your plan first, then choose who should respond.")
        return redirect("plans:edit")
    form = ResponderForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        try:
            services.assign_responder(request.user, plan, form.cleaned_data["contact"], form.cleaned_data["role"])
        except services.ResponderError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Responder added. Check that they have permission to receive alerts.")
            return redirect("plans:responders")
    assignments = plan.responders.select_related("contact")
    return render(request, "plans/responders.html", {"plan": plan, "form": form, "assignments": assignments})


@login_required
@require_POST
def responder_remove(request, pk):
    plan = _active_plan(request.user)
    assignment = get_object_or_404(ResponderAssignment, pk=pk, plan=plan) if plan else None
    if assignment is None:
        return redirect("plans:responders")
    services.remove_responder(request.user, plan, assignment)
    messages.success(request, "Responder removed from your plan.")
    return redirect("plans:responders")


@login_required
@require_POST
def plan_review(request):
    plan = _active_plan(request.user)
    if plan:
        services.mark_reviewed(request.user, plan)
        messages.success(request, "Marked as reviewed. Your next review is set for 90 days from now.")
    return redirect("plans:health")


@login_required
@require_POST
def plan_deactivate(request):
    plan = _active_plan(request.user)
    if plan:
        services.deactivate(request.user, plan)
        messages.success(request, "Your plan was deactivated. Guardian Mode will not work until you create or reactivate one.")
    return redirect("dashboard:home")
