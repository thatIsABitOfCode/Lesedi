from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.decorators.http import require_POST

from apps import audit

from . import ratelimit, services
from .forms import EmailAuthenticationForm, RegistrationForm, SettingsForm
from .models import DataDeletionRequest, User, UserConsent

GENERIC_REGISTRATION_MESSAGE = (
    "Thank you. If this email address can be used, your account is ready. Please sign in. "
    "If you cannot sign in, use 'Forgot your password?'."
)


@ratelimit.throttle("register", limit=10, window=3600)
def register(request):
    if request.user.is_authenticated:
        return redirect("dashboard:home")
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        # Same response whether or not the address is already registered, so the
        # form cannot be used to discover who has an account.
        if not User.objects.filter(email__iexact=email).exists():
            try:
                user = User.objects.create_user(
                    email=email,
                    password=form.cleaned_data["password1"],
                    display_name=form.cleaned_data["display_name"],
                )
            except IntegrityError:
                user = None
            if user:
                UserConsent.objects.create(
                    user=user, kind=UserConsent.Kind.TERMS_AND_DISCLAIMER, version=settings.POLICY_DRAFT_VERSION
                )
                audit.record(user, "account.registered")
        messages.success(request, GENERIC_REGISTRATION_MESSAGE)
        return redirect("accounts:login")
    return render(request, "accounts/register.html", {"form": form})


class LesediLoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = EmailAuthenticationForm
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        identifier = (request.POST.get("username") or "").strip().lower()
        ip_ok = ratelimit.allow(f"login-ip:{ratelimit.client_ip(request)}", 30, 900)
        id_ok = ratelimit.allow(f"login-id:{identifier}", 8, 900)
        if not (ip_ok and id_ok):
            return ratelimit.too_many(request)
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        audit.record(form.get_user(), "account.login")
        return response


password_reset_view = ratelimit.throttle("pwreset", limit=5, window=3600)(
    auth_views.PasswordResetView.as_view(
        template_name="accounts/password_reset_form.html",
        email_template_name="accounts/password_reset_email.txt",
        subject_template_name="accounts/password_reset_subject.txt",
        success_url=reverse_lazy("accounts:password_reset_done"),
    )
)


@login_required
def settings_view(request):
    form = SettingsForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit.record(request.user, "account.settings_changed")
        messages.success(request, "Your settings were saved.")
        return redirect("accounts:settings")
    return render(request, "accounts/settings.html", {"form": form})


@login_required
def security(request):
    pending = DataDeletionRequest.objects.filter(user=request.user, status="pending").first()
    return render(
        request,
        "accounts/security.html",
        {"pending_deletion": pending, "grace_days": services.DELETION_GRACE_DAYS},
    )


@login_required
@require_POST
def sign_out_everywhere(request):
    user = request.user
    user.session_version += 1
    user.save(update_fields=["session_version"])
    request.session["sv"] = user.session_version  # keep this device signed in
    audit.record(user, "account.sessions_revoked")
    messages.success(request, "All your other devices and browsers have been signed out.")
    return redirect("accounts:security")


@login_required
def export_data(request):
    payload = services.export_user_data(request.user)
    response = JsonResponse(payload, json_dumps_params={"indent": 2})
    response["Content-Disposition"] = 'attachment; filename="lesedi-data-export.json"'
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_POST
def request_deletion(request):
    req = services.request_deletion(request.user)
    messages.success(
        request,
        f"Deletion requested. Your account and data will be permanently deleted after "
        f"{req.execute_after:%d %B %Y}. You can cancel before then.",
    )
    return redirect("accounts:security")


@login_required
@require_POST
def cancel_deletion(request):
    services.cancel_deletion(request.user)
    messages.success(request, "Your deletion request was cancelled.")
    return redirect("accounts:security")
