import io

from django.contrib import messages
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.decorators import survivor_required
from core.ratelimit import client_ip, hit

from . import services
from .forms import IncidentForm, NoteForm, ShareForm, UploadForm
from .models import EvidenceAccessEvent, EvidenceItem, EvidenceShare, Incident


@survivor_required
def incident_list(request):
    qs = Incident.objects.filter(owner=request.user)
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(title__icontains=q) | Q(description__icontains=q) | Q(items__title__icontains=q)
            | Q(items__note_text__icontains=q) | Q(items__original_filename__icontains=q)).distinct()
    return render(request, "evidence/incident_list.html", {"incidents": qs, "q": q})


@survivor_required
def incident_create(request):
    form = IncidentForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        incident = form.save(commit=False)
        incident.owner = request.user
        incident.save()
        messages.success(request, "Incident record created. It is private to you.")
        return redirect("evidence:incident", pk=incident.pk)
    return render(request, "evidence/incident_form.html", {"form": form})


def _own_incident(request, pk):
    return get_object_or_404(Incident, pk=pk, owner=request.user)  # 404 (not 403) for other people's records


@survivor_required
def incident_detail(request, pk):
    incident = _own_incident(request, pk)
    items = incident.items.prefetch_related("shares")
    return render(request, "evidence/incident_detail.html", {
        "incident": incident, "items": items, "note_form": NoteForm(), "upload_form": UploadForm(),
        "share_form": ShareForm(), "access_events": EvidenceAccessEvent.objects.filter(item__incident=incident)[:15],
    })


@survivor_required
@require_POST
def add_note(request, pk):
    incident = _own_incident(request, pk)
    form = NoteForm(request.POST)
    if form.is_valid():
        d = form.cleaned_data
        try:
            services.add_note(incident=incident, user=request.user, text=d["note_text"], title=d["title"], event_time=d["event_time"])
            messages.success(request, "Note saved.")
        except services.EvidenceError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, "Please check the note and try again.")
    return redirect("evidence:incident", pk=incident.pk)


@survivor_required
@require_POST
def upload(request, pk):
    incident = _own_incident(request, pk)
    form = UploadForm(request.POST, request.FILES)
    if form.is_valid():
        d = form.cleaned_data
        try:
            services.add_file(incident=incident, user=request.user, upload=d["file"], title=d["title"], event_time=d["event_time"])
            messages.success(request, "File stored privately and encrypted.")
        except services.EvidenceError as exc:
            messages.error(request, str(exc))
    else:
        messages.error(request, "Please choose a file and try again.")
    return redirect("evidence:incident", pk=incident.pk)


@survivor_required
def download(request, pk):
    item = get_object_or_404(EvidenceItem, pk=pk, owner=request.user)
    try:
        data = services.read_bytes(item)
    except services.EvidenceError as exc:
        messages.error(request, str(exc))
        return redirect("evidence:incident", pk=item.incident_id)
    services.log_access(item, request.user, "download")
    return _file_response(item, data)


def _file_response(item, data):
    resp = FileResponse(io.BytesIO(data), as_attachment=True, filename=item.original_filename or "evidence",
                        content_type=item.content_type or "application/octet-stream")
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Cache-Control"] = "no-store, private"
    resp["Referrer-Policy"] = "no-referrer"
    return resp


@survivor_required
@require_POST
def delete_item(request, pk):
    item = get_object_or_404(EvidenceItem, pk=pk, owner=request.user)
    incident_id = item.incident_id
    services.delete_item(item, request.user)
    messages.success(request, "Deleted. Any share links to it no longer work.")
    return redirect("evidence:incident", pk=incident_id)


@survivor_required
@require_POST
def export_pack(request, pk):
    incident = _own_incident(request, pk)
    ids = request.POST.getlist("item")
    items = list(incident.items.filter(pk__in=ids)) if ids else []
    if not items:
        messages.error(request, "Tick at least one record to include in the pack.")
        return redirect("evidence:incident", pk=incident.pk)
    try:
        blob = services.build_pack(user=request.user, incident=incident, items=items)
    except services.EvidenceError as exc:
        messages.error(request, str(exc))
        return redirect("evidence:incident", pk=incident.pk)
    resp = HttpResponse(blob, content_type="application/zip")
    resp["Content-Disposition"] = 'attachment; filename="lesedi-evidence-pack.zip"'
    resp["Cache-Control"] = "no-store, private"
    return resp


@survivor_required
@require_POST
def share_create(request, pk):
    item = get_object_or_404(EvidenceItem, pk=pk, owner=request.user)
    form = ShareForm(request.POST)
    if form.is_valid():
        share, token = services.create_share(
            item=item, user=request.user, label=form.cleaned_data["recipient_label"], hours=form.cleaned_data["hours"])
        link = request.build_absolute_uri(reverse("evidence:shared", args=[token]))
        messages.info(request, f"Share link (shown once - copy it now; revoke it any time below): {link}")
    else:
        messages.error(request, "Please give a label and a number of hours.")
    return redirect("evidence:incident", pk=item.incident_id)


@survivor_required
@require_POST
def share_revoke(request, pk):
    share = get_object_or_404(EvidenceShare, pk=pk, owner=request.user)
    services.revoke_share(share, request.user)
    messages.success(request, "That link has been revoked. It stops working immediately.")
    return redirect("evidence:incident", pk=share.item.incident_id)


def shared_download(request, token):
    """Public, token-gated download of ONE item. Expiry and revocation are checked on every request."""
    if not hit(f"share:{client_ip(request)}", limit=30, window=900):
        return HttpResponse("Too many requests.", status=429)
    share = services.find_active_share(token)
    if share is None:
        raise Http404
    item = share.item
    try:
        if item.kind == "file":
            data = services.read_bytes(item)
            services.record_share_access(share)
            return _file_response(item, data)
        services.record_share_access(share)
        resp = HttpResponse(item.note_text, content_type="text/plain; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="note.txt"'
        resp["Cache-Control"] = "no-store, private"
        resp["Referrer-Policy"] = "no-referrer"
        return resp
    except services.EvidenceError:
        raise Http404
