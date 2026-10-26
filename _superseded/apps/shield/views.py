from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps import audit

from . import services
from .forms import ShieldAnswersForm


@login_required
def assess(request):
    answers = services.get_answers(request.user)
    form = ShieldAnswersForm(request.POST or None, instance=answers)
    if request.method == "POST" and form.is_valid():
        form.save()
        audit.record(request.user, "shield.answers_saved")
        messages.success(request, "Your answers were saved and the check below was refreshed.")
        return redirect("shield:assess")
    findings = services.assess(request.user)
    return render(
        request,
        "shield/assess.html",
        {
            "form": form,
            "findings": findings,
            "counts": services.summarise(findings),
            "limitations": services.LIMITATIONS,
        },
    )
