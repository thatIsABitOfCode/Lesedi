import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.notifications.models import NotificationDelivery
from apps.safety_plans import services as plan_services
from apps.safety_plans.models import ResponderRole, SafetyPlan

from . import services
from .models import OPEN_STATES, GuardianActivation, State

REFRESH_SECONDS = 10


def _open_activation(user):
    return GuardianActivation.objects.filter(owner=user, state__in=OPEN_STATES).first()


@login_required
def home(request):
    activation = _open_activation(request.user)
    if activation:
        return redirect("guardian:detail", pk=activation.pk)
    plan = SafetyPlan.objects.filter(owner=request.user, is_active=True).first()
    context = {
        "plan": plan,
        "idempotency_key": uuid.uuid4().hex,
        "scope_note": services.SCOPE_NOTE,
        "recent": GuardianActivation.objects.filter(owner=request.user)[:5],
    }
    if plan:
        primaries, primaries_skipped = services.authorised_responders(plan, ResponderRole.PRIMARY)
        backups, backups_skipped = services.authorised_responders(plan, ResponderRole.BACKUP)
        findings = plan_services.assess_plan_health(plan)
        context.update(
            primaries=primaries,
            primaries_skipped=primaries_skipped,
            backups=backups,
            backups_skipped=backups_skipped,
            attention=[f for f in findings if f.severity == "attention"],
        )
    return render(request, "guardian/home.html", context)


@login_required
@require_POST
def activate(request):
    try:
        activation, created = services.activate(request.user, request.POST.get("idempotency_key", ""))
    except services.AlreadyActive as exc:
        messages.info(request, "Guardian Mode is already active. Here is where things stand.")
        return redirect("guardian:detail", pk=exc.activation.pk)
    except services.NoActivePlan as exc:
        messages.error(request, str(exc))
        return redirect("plans:edit")
    return redirect("guardian:detail", pk=activation.pk)


@login_required
def detail(request, pk):
    activation = get_object_or_404(
        GuardianActivation.objects.select_related("plan"), pk=pk, owner=request.user
    )
    deliveries = (
        NotificationDelivery.objects.filter(action__activation=activation)
        .select_related("contact", "action")
        .order_by("queued_at")
    )
    is_open = activation.is_open
    refresh = 0 if (not is_open or request.user.low_data_mode) else REFRESH_SECONDS
    return render(
        request,
        "guardian/detail.html",
        {
            "activation": activation,
            "events": activation.events.all(),
            "deliveries": deliveries,
            "acknowledgements": activation.acknowledgements.select_related("contact"),
            "is_open": is_open,
            "refresh": refresh,
            "can_escalate": is_open
            and activation.backup_contacted_at is None
            and activation.state
            in (State.ALERTS_PENDING, State.AWAITING_ACKNOWLEDGEMENT, State.ESCALATION_REQUIRED),
            "can_skip_wait": activation.simulated
            and activation.state in (State.AWAITING_ACKNOWLEDGEMENT, State.BACKUP_CONTACTED),
            "scope_note": services.SCOPE_NOTE,
            "simulation_note": services.SIMULATION_NOTE,
        },
    )


def _back(activation_id):
    return redirect("guardian:detail", pk=activation_id)


@login_required
@require_POST
def escalate(request, pk):
    try:
        done = services.manual_escalate(pk, request.user)
    except GuardianActivation.DoesNotExist:
        return redirect("guardian:home")
    except services.GuardianError as exc:
        messages.error(request, str(exc))
    else:
        if done:
            messages.success(request, "Your backup responder has been queued for an alert. See the timeline for what happens next.")
        else:
            messages.info(request, "No further contact could be queued. The timeline explains why.")
    return _back(pk)


@login_required
@require_POST
def close(request, pk):
    outcome = request.POST.get("outcome")
    new_state = {"resolve": State.RESOLVED, "cancel": State.CANCELLED}.get(outcome)
    if new_state is None:
        messages.error(request, "Choose whether to mark this as resolved or cancel it.")
        return _back(pk)
    try:
        services.close_activation(pk, request.user, new_state, request.POST.get("note", ""))
    except GuardianActivation.DoesNotExist:
        return redirect("guardian:home")
    except services.GuardianError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Guardian Mode has ended. Your contacts were not told; you may want to let them know.")
    return _back(pk)


@login_required
@require_POST
def simulate_time(request, pk):
    try:
        services.simulate_time_passing(pk, request.user)
    except GuardianActivation.DoesNotExist:
        return redirect("guardian:home")
    except services.GuardianError as exc:
        messages.error(request, str(exc))
    return _back(pk)


@login_required
@require_POST
def simulate_receipts(request, pk):
    try:
        count = services.simulate_delivery_receipts(pk, request.user)
    except GuardianActivation.DoesNotExist:
        return redirect("guardian:home")
    except services.GuardianError as exc:
        messages.error(request, str(exc))
    else:
        messages.info(request, f"Simulated delivery receipts recorded for {count} message(s).")
    return _back(pk)
