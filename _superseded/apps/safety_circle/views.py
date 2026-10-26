from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps import audit
from apps.accounts import ratelimit
from apps.guardian import services as guardian_services
from apps.guardian.models import EmergencyAction
from apps.notifications.channels import Channel

from . import services
from .forms import ContactForm, PermissionsForm
from .models import ACTIVE_PERMISSIONS, ContactPermission, Permission, TrustedContact


def _own_contact(request, pk):
    return get_object_or_404(TrustedContact, pk=pk, owner=request.user, removed_at__isnull=True)


@login_required
def circle_list(request):
    contacts = (
        TrustedContact.objects.filter(owner=request.user, removed_at__isnull=True)
        .prefetch_related(
            Prefetch(
                "permissions",
                queryset=ContactPermission.objects.filter(revoked_at__isnull=True),
                to_attr="active_perms",
            )
        )
    )
    labels = dict(Permission.choices)
    rows = [
        {"contact": c, "permissions": [labels[p.permission] for p in c.active_perms]} for c in contacts
    ]
    return render(request, "circle/list.html", {"rows": rows})


@login_required
def contact_add(request):
    form = ContactForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        contact = form.save(commit=False)
        contact.owner = request.user
        contact.save()
        audit.record(request.user, "circle.contact_added", contact)
        messages.success(request, f"{contact.name} was added. They cannot see or do anything yet; choose their permissions next.")
        return redirect("circle:contact_permissions", pk=contact.pk)
    return render(request, "circle/contact_form.html", {"form": form, "title": "Add a trusted contact"})


@login_required
def contact_edit(request, pk):
    contact = _own_contact(request, pk)
    form = ContactForm(request.POST or None, instance=contact)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit.record(request.user, "circle.contact_edited", contact)
        messages.success(request, "Contact details saved.")
        return redirect("circle:list")
    return render(request, "circle/contact_form.html", {"form": form, "title": f"Edit {contact.name}", "contact": contact})


@login_required
def contact_permissions(request, pk):
    contact = _own_contact(request, pk)
    initial = {"permissions": services.active_permissions(contact)}
    form = PermissionsForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        services.set_permissions(contact, form.cleaned_data["permissions"], request.user)
        messages.success(request, "Permissions updated. Changes apply immediately.")
        return redirect("circle:list")
    not_active_yet = [p.label for p in Permission if p not in ACTIVE_PERMISSIONS]
    return render(
        request,
        "circle/permissions.html",
        {"form": form, "contact": contact, "not_active_yet": not_active_yet},
    )


@login_required
@require_POST
def contact_invite(request, pk):
    contact = _own_contact(request, pk)
    if not ratelimit.allow(f"invite:{request.user.pk}", 10, 3600):
        return ratelimit.too_many(request)
    token = services.create_invitation(contact, request.user)
    link = request.build_absolute_uri(f"/circle/invite/{token}/")
    return render(request, "circle/invite_created.html", {"contact": contact, "link": link})


@login_required
@require_POST
def contact_remove(request, pk):
    contact = _own_contact(request, pk)
    services.remove_contact(contact, request.user)
    messages.success(request, f"{contact.name} was removed and all their access was revoked.")
    return redirect("circle:list")


@login_required
def invite_accept(request, token):
    if not ratelimit.allow(f"invite-accept:{ratelimit.client_ip(request)}", 20, 3600):
        return ratelimit.too_many(request)
    try:
        invitation = services.get_valid_invitation(token)
    except services.InvitationError:
        return render(request, "circle/invite_invalid.html", status=404)
    if request.method == "POST":
        try:
            services.accept_invitation(token, request.user)
        except services.InvitationError:
            return render(request, "circle/invite_invalid.html", status=404)
        messages.success(request, "You are now a trusted contact. You will only see what the person has chosen to allow.")
        return redirect("circle:alerts")
    return render(request, "circle/invite_accept.html", {"invitation": invitation})


@login_required
def alerts(request):
    """What a trusted contact can see: only alerts addressed to them, only while
    they still hold the permission, and only the survivor's display name plus the
    instruction the survivor approved. Nothing else about the survivor."""
    actions = (
        EmergencyAction.objects.filter(
            contact__linked_user=request.user,
            contact__removed_at__isnull=True,
            contact__permissions__permission=Permission.RECEIVE_ALERT,
            contact__permissions__revoked_at__isnull=True,
        )
        .select_related("activation__owner", "activation__plan", "contact")
        .distinct()
        .order_by("-created_at")[:20]
    )
    items = []
    for action in actions:
        activation = action.activation
        is_open = activation.is_open
        items.append(
            {
                "activation": activation,
                "contact": action.contact,
                "is_open": is_open,
                "can_acknowledge": is_open and services.has_permission(action.contact, Permission.ACKNOWLEDGE_ALERT),
                "acknowledged": activation.acknowledgements.filter(contact=action.contact).exists(),
                "instruction": (
                    activation.plan.emergency_instructions
                    if is_open and services.has_permission(action.contact, Permission.RECEIVE_INSTRUCTION)
                    else ""
                ),
            }
        )
    return render(request, "circle/alerts.html", {"items": items})


@login_required
@require_POST
def acknowledge(request, activation_id):
    try:
        guardian_services.acknowledge(activation_id, request.user)
    except guardian_services.GuardianError:
        messages.error(request, "This alert can no longer be acknowledged.")
    else:
        messages.success(
            request,
            "Thank you. Your acknowledgement was recorded. It tells them you have seen the alert; "
            "it does not tell them you are on your way.",
        )
    return redirect("circle:alerts")
