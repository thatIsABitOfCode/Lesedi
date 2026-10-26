from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from core.decorators import survivor_required
from core.ratelimit import client_ip, hit

from . import services
from .forms import AssignResponderForm, ContactForm, PermissionsForm, PlanForm
from .health import assess_plan
from .models import ContactStatus, TrustedContact


@survivor_required
def plan_edit(request):
    plan = services.get_or_create_plan(request.user)
    form = PlanForm(request.POST or None, instance=plan)
    if request.method == "POST" and form.is_valid():
        services.save_plan(form.save(commit=False))
        messages.success(request, "Your plan was saved. Only you can see it.")
        return redirect("safety:plan")
    return render(request, "safety/plan_form.html", {"form": form, "plan": plan, "versions": plan.versions.all()[:5]})


@survivor_required
def plan_health(request):
    plan = services.get_or_create_plan(request.user)
    return render(request, "safety/plan_health.html", {"plan": plan, "findings": assess_plan(plan)})


@survivor_required
def circle(request):
    plan = services.get_or_create_plan(request.user)
    contacts = request.user.trusted_contacts.exclude(status=ContactStatus.REVOKED)
    responders = plan.responders.select_related("contact")
    return render(request, "safety/circle.html", {"plan": plan, "contacts": contacts, "responders": responders})


@survivor_required
def contact_add(request):
    form = ContactForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        contact = form.save(commit=False)
        contact.owner = request.user
        contact.save()
        messages.success(request, f"{contact.name} was added. Nothing is shared with them until they accept an invitation.")
        return redirect("safety:contact", pk=contact.pk)
    return render(request, "safety/contact_form.html", {"form": form})


@survivor_required
def contact_detail(request, pk):
    contact = get_object_or_404(TrustedContact, pk=pk, owner=request.user)  # 404 for anyone else's contact
    plan = services.get_or_create_plan(request.user)
    perm_form = PermissionsForm(initial={"permissions": list(services.active_permissions(plan, contact))})
    assign_form = AssignResponderForm()
    invite_link = None

    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "permissions":
                f = PermissionsForm(request.POST)
                if f.is_valid():
                    services.set_permissions(plan, contact, f.cleaned_data["permissions"])
                    messages.success(request, "Permissions updated.")
                    return redirect("safety:contact", pk=contact.pk)
            elif action == "assign":
                f = AssignResponderForm(request.POST)
                if f.is_valid():
                    services.assign_responder(
                        plan, contact, f.cleaned_data["rank"],
                        grant_alert_permissions=f.cleaned_data["grant_alert_permissions"])
                    messages.success(request, "Responder position saved.")
                    return redirect("safety:contact", pk=contact.pk)
                assign_form = f
            elif action == "unassign":
                services.remove_responder(plan, contact)
                messages.success(request, "Removed from your responder order. Their permissions are unchanged.")
                return redirect("safety:contact", pk=contact.pk)
            elif action == "confirm_details":
                contact.owner_confirmed_details = request.POST.get("confirmed") == "on"
                contact.save(update_fields=["owner_confirmed_details"])
                return redirect("safety:contact", pk=contact.pk)
            elif action == "invite":
                _, token = services.create_invitation(contact)
                invite_link = request.build_absolute_uri(reverse("safety:invite", args=[token]))
                messages.info(request, "SIMULATION: no message was sent. Share this link with the person yourself.")
            elif action == "revoke":
                services.revoke_contact(contact)
                messages.success(request, f"{contact.name} was removed and all their permissions revoked.")
                return redirect("safety:circle")
        except services.SafetyError as exc:
            messages.error(request, str(exc))

    return render(request, "safety/contact_detail.html", {
        "contact": contact, "plan": plan, "perm_form": perm_form, "assign_form": assign_form,
        "assignment": plan.responders.filter(contact=contact).first(), "invite_link": invite_link,
        "active_perms": services.active_permissions(plan, contact),
    })


def invite_accept(request, token):
    """Public page for the invited person. Reveals only the inviter's display name."""
    if not hit(f"invite:{client_ip(request)}", limit=30, window=3600):
        return HttpResponse("Too many requests.", status=429)
    invitation = services.load_invitation(token)
    if invitation is None:
        return render(request, "safety/invite_invalid.html", status=404)
    if request.method == "POST":
        accept = request.POST.get("decision") == "accept"
        services.respond_to_invitation(invitation, accept)
        return render(request, "safety/invite_done.html", {"accepted": accept})
    return render(request, "safety/invite_accept.html", {"inviter": invitation.contact.owner.display_name})
