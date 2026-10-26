import json

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, PasswordResetView
from django.http import HttpResponse
from django.shortcuts import redirect, render

from audit.services import record
from core.ratelimit import client_ip, hit

from .forms import DeleteAccountForm, EmailLoginForm, ProfileForm, RegisterForm
from .models import Role, User


def register(request):
    if request.user.is_authenticated:
        return redirect("core:dashboard")
    form = RegisterForm(request.POST or None)
    if request.method == "POST":
        if not hit(f"register:{client_ip(request)}", limit=10, window=3600):
            return HttpResponse("Too many attempts. Please try again later.", status=429)
        if form.is_valid():
            d = form.cleaned_data
            # Anti-enumeration: the response is identical whether or not the email already exists.
            if not User.objects.filter(email=d["email"]).exists():
                user = User.objects.create_user(
                    d["email"], d["password1"], display_name=d["display_name"], role=Role.SURVIVOR
                )
                record("account.registered", actor=user)
            messages.success(request, "Thank you. If this email can be used, your account is ready. Please log in.")
            return redirect("accounts:login")
    return render(request, "accounts/register.html", {"form": form})


class RateLimitedLoginView(LoginView):
    form_class = EmailLoginForm
    template_name = "accounts/login.html"
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        ip = client_ip(request)
        email = (request.POST.get("username") or "").strip().lower()
        ok_ip = hit(f"login-ip:{ip}", limit=60, window=900)
        ok_acct = hit(f"login-acct:{ip}:{email}", limit=10, window=900)
        if not (ok_ip and ok_acct):
            return HttpResponse("Too many sign-in attempts. Please wait a few minutes and try again.", status=429)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        record("account.login", actor=form.get_user())
        return response


class RateLimitedPasswordResetView(PasswordResetView):
    """Same response whether or not the email has an account; limited so it cannot be used to spam a mailbox."""

    def post(self, request, *args, **kwargs):
        if not hit(f"pwreset:{client_ip(request)}", limit=5, window=3600):
            return HttpResponse("Too many attempts. Please try again later.", status=429)
        return super().post(request, *args, **kwargs)


@login_required
def security(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your profile was saved.")
        return redirect("accounts:security")
    return render(request, "accounts/security.html", {"form": form, "delete_form": DeleteAccountForm()})


@login_required
def export_data(request):
    """Machine-readable copy of the user's own account data (evidence file contents are not included)."""
    from evidence.models import EvidenceItem, Incident
    from safety.models import SafetyPlan, TrustedContact

    u = request.user
    payload = {
        "account": {"email": u.email, "display_name": u.display_name, "phone": u.phone, "language": u.preferred_language},
        "plans": list(SafetyPlan.objects.filter(owner=u).values(
            "title", "is_active", "emergency_instructions", "safe_destination", "transport_notes",
            "essential_documents", "checkin_method", "comms_failure_contingency", "review_date", "version")),
        "contacts": list(TrustedContact.objects.filter(owner=u).values("name", "phone", "email", "status")),
        "incidents": list(Incident.objects.filter(owner=u).values("title", "description", "occurred_at")),
        "evidence_items": list(EvidenceItem.objects.filter(owner=u).values(
            "kind", "title", "note_text", "original_filename", "sha256", "event_time", "uploaded_at")),
    }
    record("account.data_exported", actor=u)
    resp = HttpResponse(json.dumps(payload, indent=2, default=str), content_type="application/json")
    resp["Content-Disposition"] = 'attachment; filename="lesedi-my-data.json"'
    return resp


@login_required
def delete_account(request):
    if request.method != "POST":
        return redirect("accounts:security")
    form = DeleteAccountForm(request.POST)
    if form.is_valid() and request.user.check_password(form.cleaned_data["password"]):
        user = request.user
        record("account.deleted", actor=None, metadata={"role": user.role})
        logout(request)
        user.delete()  # cascades; evidence files are removed by a post_delete signal
        messages.success(request, "Your account and its data were deleted.")
        return redirect("core:landing")
    messages.error(request, "We could not confirm that. Check your password and tick the box.")
    return redirect("accounts:security")
