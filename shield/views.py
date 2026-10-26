from django import forms
from django.contrib import messages
from django.shortcuts import redirect, render

from core.decorators import survivor_required

from .models import ShieldSelfReport
from .services import LIMITS, assess, get_report


class SelfReportForm(forms.ModelForm):
    class Meta:
        model = ShieldSelfReport
        fields = ["shared_account_access", "shared_device", "previews_visible", "location_always_shared", "suspects_monitoring"]


@survivor_required
def shield_page(request):
    report = get_report(request.user)
    form = SelfReportForm(request.POST or None, instance=report)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your answers were saved.")
        return redirect("shield:page")
    return render(request, "shield/shield.html", {"form": form, "findings": assess(request.user), "limits": LIMITS})
