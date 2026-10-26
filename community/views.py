from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from . import services
from .forms import (AppealForm, CommentForm, FlagForm, ModerationForm, ReportForm, UpdateForm, WitnessForm,
                    WitnessReviewForm)
from .models import Category, CommunityComment, CommunityReport, WitnessConcern
from .permissions import is_moderator, moderator_required


def _fail(request, error):
    messages.error(request, str(error))


# --- feed ----------------------------------------------------------------------------------------------------

@login_required
def feed(request):
    reports = services.public_reports()
    category = request.GET.get("category", "")
    area = request.GET.get("area", "").strip()
    if category in Category.values:
        reports = reports.filter(category=category)
    if area:
        reports = reports.filter(area__icontains=area)
    page = Paginator(reports.order_by("-published_at"), 20).get_page(request.GET.get("page"))
    return render(request, "community/feed.html", {
        "page": page, "categories": Category.choices, "category": category, "area": area})


@login_required
def report_new(request):
    form = ReportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.submit_report(request.user, **form.cleaned_data)
        except services.CommunityError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Thank you. A moderator will review your report before anything is shown to "
                                      "other people. Your name is never shown.")
            return redirect("community:mine")
    return render(request, "community/report_form.html", {"form": form})


@login_required
def report_detail(request, pk):
    report = get_object_or_404(CommunityReport, pk=pk)
    if not services.can_view(request.user, report):
        raise Http404  # do not reveal that a private report exists
    comments = report.comments.filter(is_hidden=False).select_related("author") if report.is_public else []
    return render(request, "community/report_detail.html", {
        "report": report, "is_author": report.author_id == request.user.pk, "is_mod": is_moderator(request.user),
        "updates": report.updates.all() if report.is_public else [], "comments": comments,
        "commenting_open": services.commenting_open(report), "comment_form": CommentForm(),
        "flag_form": FlagForm(), "appeal_form": AppealForm()})


@login_required
@require_POST
def comment_add(request, pk):
    report = get_object_or_404(CommunityReport, pk=pk)
    if not services.can_view(request.user, report):
        raise Http404
    form = CommentForm(request.POST)
    if form.is_valid():
        try:
            services.add_comment(request.user, report, form.cleaned_data["body"])
            messages.success(request, "Your comment was added.")
        except services.CommunityError as error:
            _fail(request, error)
    else:
        messages.error(request, "Please write a comment of up to 500 characters.")
    return redirect("community:report", pk=report.pk)


@login_required
@require_POST
def flag_report(request, pk):
    report = get_object_or_404(CommunityReport, pk=pk)
    if not services.can_view(request.user, report):
        raise Http404
    form = FlagForm(request.POST)
    if form.is_valid():
        try:
            created = services.flag(request.user, form.cleaned_data["reason"], report=report)
            messages.success(request, "Thank you. A moderator will look at this." if created
                             else "You have already flagged this.")
        except services.CommunityError as error:
            _fail(request, error)
    return redirect("community:report", pk=report.pk)


@login_required
@require_POST
def flag_comment(request, pk):
    comment = get_object_or_404(CommunityComment, pk=pk, is_hidden=False)
    if not services.can_view(request.user, comment.report):
        raise Http404
    form = FlagForm(request.POST)
    if form.is_valid():
        try:
            created = services.flag(request.user, form.cleaned_data["reason"], comment=comment)
            messages.success(request, "Thank you. A moderator will look at this." if created
                             else "You have already flagged this.")
        except services.CommunityError as error:
            _fail(request, error)
    return redirect("community:report", pk=comment.report_id)


@login_required
@require_POST
def appeal_view(request, pk):
    report = get_object_or_404(CommunityReport, pk=pk, author=request.user)  # 404 for anyone else
    form = AppealForm(request.POST)
    if form.is_valid():
        try:
            services.appeal(report, request.user, form.cleaned_data["text"])
            messages.success(request, "Your appeal was sent. A moderator will look at it again.")
        except services.CommunityError as error:
            _fail(request, error)
    return redirect("community:report", pk=report.pk)


@login_required
def mine(request):
    return render(request, "community/mine.html", {
        "reports": CommunityReport.objects.filter(author=request.user),
        "concerns": WitnessConcern.objects.filter(author=request.user)})


# --- Witness Mode --------------------------------------------------------------------------------------------

@login_required
def witness(request):
    form = WitnessForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.submit_witness(request.user, **form.cleaned_data)
        except services.CommunityError as error:
            form.add_error(None, str(error))
        else:
            messages.success(request, "Your concern was received privately. LESEDI has not contacted anyone about it.")
            return redirect("community:mine")
    return render(request, "community/witness_form.html", {"form": form})


# --- moderation ----------------------------------------------------------------------------------------------

@moderator_required
def mod_queue(request):
    needs_action, flagged = services.moderation_queue()
    return render(request, "community/mod_queue.html", {
        "needs_action": needs_action, "flagged": flagged,
        "new_concerns": WitnessConcern.objects.filter(status=WitnessConcern.Status.NEW).count()})


@moderator_required
def mod_report(request, pk):
    report = get_object_or_404(CommunityReport, pk=pk)
    initial = {"public_summary": report.public_summary or ("" if report.is_sensitive else report.description)}
    status_form, update_form = ModerationForm(initial=initial), UpdateForm()
    if request.method == "POST":
        action = request.POST.get("do")
        try:
            if action == "status":
                status_form = ModerationForm(request.POST)
                if status_form.is_valid():
                    data = status_form.cleaned_data
                    services.transition(report, data["status"], request.user, note=data["note"],
                                        public_summary=data["public_summary"])
                    messages.success(request, "Saved.")
                    return redirect("community:mod_report", pk=report.pk)
            elif action == "update":
                update_form = UpdateForm(request.POST)
                if update_form.is_valid():
                    services.add_update(report, request.user, update_form.cleaned_data["body"],
                                        update_form.cleaned_data["kind"])
                    messages.success(request, "The update is now shown on the report.")
                    return redirect("community:mod_report", pk=report.pk)
            elif action == "dismiss":
                services.dismiss_flags(report, request.user)
                messages.success(request, "Flags dismissed.")
                return redirect("community:mod_report", pk=report.pk)
            elif action == "hide_comment":
                comment = get_object_or_404(CommunityComment, pk=request.POST.get("comment"), report=report)
                services.hide_comment(comment, request.user, request.POST.get("note", ""))
                messages.success(request, "Comment hidden.")
                return redirect("community:mod_report", pk=report.pk)
        except services.CommunityError as error:
            _fail(request, error)
    report.refresh_from_db()
    return render(request, "community/mod_report.html", {
        "report": report, "status_form": status_form, "update_form": update_form,
        "actions": report.moderation_actions.select_related("moderator"),
        "comments": report.comments.all(),
        "open_flags": report.flags.filter(resolved_at__isnull=True),
        "duplicates": report.possible_duplicates.all()})


@moderator_required
def mod_witness(request):
    if request.method == "POST":
        concern = get_object_or_404(WitnessConcern, pk=request.POST.get("concern"))
        form = WitnessReviewForm(request.POST)
        if form.is_valid():
            try:
                services.review_witness(concern, request.user, form.cleaned_data["status"], form.cleaned_data["note"])
                messages.success(request, "Saved.")
            except services.CommunityError as error:
                _fail(request, error)
        else:
            messages.error(request, "Choose reviewed or closed.")
        return redirect("community:mod_witness")
    return render(request, "community/mod_witness.html", {
        "concerns": WitnessConcern.objects.exclude(status=WitnessConcern.Status.CLOSED)
        .order_by("-seems_urgent", "created_at")})
