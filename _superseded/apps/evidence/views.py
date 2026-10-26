import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_POST

from apps import audit

from . import services
from .forms import EntryForm, IncidentForm, ShareForm, UploadForm
from .models import EvidenceAccessEvent, EvidenceItem, EvidenceShare, Incident


def _own_incident(request, pk):
    return get_object_or_404(Incident, pk=pk, owner=request.user)


def _own_item(request, pk):
    return get_object_or_404(
        EvidenceItem.objects.select_related("incident"),
        pk=pk,
        incident__owner=request.user,
        deleted_at__isnull=True,
    )


def _file_response(item, data):
    response = HttpResponse(data, content_type=item.content_type)
    response["Content-Disposition"] = content_disposition_header(True, item.display_name)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def home(request):
    query = request.GET.get("q", "").strip()[:100]
    incidents = Incident.objects.filter(owner=request.user)
    if query:
        incidents = incidents.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(entries__note__icontains=query)
            | Q(items__display_name__icontains=query, items__deleted_at__isnull=True)
        ).distinct()
    return render(request, "vault/home.html", {"incidents": incidents, "form": IncidentForm(), "query": query})


@login_required
@require_POST
def incident_create(request):
    form = IncidentForm(request.POST)
    if not form.is_valid():
        incidents = Incident.objects.filter(owner=request.user)
        return render(request, "vault/home.html", {"incidents": incidents, "form": form, "query": ""})
    incident = form.save(commit=False)
    incident.owner = request.user
    incident.save()
    audit.record(request.user, "evidence.incident_created", incident)
    messages.success(request, "Incident record created. It is private to you.")
    return redirect("vault:incident", pk=incident.pk)


def _incident_context(request, incident, entry_form=None, upload_form=None, share_form=None):
    entries = list(incident.entries.all())
    items = list(incident.items.filter(deleted_at__isnull=True))
    for entry in entries:
        entry.visible_items = [i for i in items if i.entry_id == entry.id]
    loose_items = [i for i in items if i.entry_id is None]
    timeline = [{"when": e.occurred_at, "entry": e, "item": None} for e in entries]
    timeline += [{"when": i.uploaded_at, "entry": None, "item": i} for i in loose_items]
    timeline.sort(key=lambda row: row["when"])
    shares = {}
    for share in EvidenceShare.objects.filter(
        item__incident=incident, revoked_at__isnull=True
    ).select_related("shared_with"):
        shares.setdefault(share.item_id, []).append(share)
    for item in items:
        item.active_shares = shares.get(item.id, [])
    return {
        "incident": incident,
        "timeline": timeline,
        "entry_form": entry_form or EntryForm(),
        "upload_form": upload_form or UploadForm(incident=incident),
        "share_form": share_form or ShareForm(user=request.user),
        "has_records": bool(entries or items),
    }


@login_required
def incident_detail(request, pk):
    incident = _own_incident(request, pk)
    return render(request, "vault/incident.html", _incident_context(request, incident))


@login_required
@require_POST
def entry_add(request, pk):
    incident = _own_incident(request, pk)
    form = EntryForm(request.POST)
    if not form.is_valid():
        return render(request, "vault/incident.html", _incident_context(request, incident, entry_form=form))
    entry = form.save(commit=False)
    entry.incident = incident
    entry.save()
    audit.record(request.user, "evidence.entry_added", entry)
    messages.success(request, "Note added to the timeline.")
    return redirect("vault:incident", pk=incident.pk)


@login_required
@require_POST
def upload(request, pk):
    incident = _own_incident(request, pk)
    form = UploadForm(request.POST, request.FILES, incident=incident)
    if form.is_valid():
        try:
            services.add_file(incident, request.user, form.cleaned_data["file"], form.cleaned_data["entry"])
        except services.UploadRejected as exc:
            form.add_error("file", str(exc))
        else:
            messages.success(
                request,
                "File saved and encrypted. LESEDI recorded its fingerprint (SHA-256) at upload time.",
            )
            return redirect("vault:incident", pk=incident.pk)
    return render(request, "vault/incident.html", _incident_context(request, incident, upload_form=form))


@login_required
def download(request, pk):
    item = _own_item(request, pk)
    data, intact = services.open_item(item)
    if data is None:
        messages.error(request, "This file could not be read. It may be missing or may have been altered.")
        return redirect("vault:incident", pk=item.incident_id)
    services.record_access(item, request.user, EvidenceAccessEvent.Action.DOWNLOAD)
    audit.record(request.user, "evidence.downloaded", item)
    return _file_response(item, data)


@login_required
@require_POST
def item_delete(request, pk):
    item = _own_item(request, pk)
    services.delete_item(request.user, item)
    messages.success(request, "The file was deleted from storage. Any shares of it were revoked.")
    return redirect("vault:incident", pk=item.incident_id)


@login_required
@require_POST
def share(request, pk):
    item = _own_item(request, pk)
    form = ShareForm(request.POST, user=request.user)
    if form.is_valid():
        try:
            services.share_item(request.user, item, form.cleaned_data["contact"])
        except services.ShareError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request,
                "Shared. Only that person, signed in to their own account, can open this item. "
                "You can revoke it at any time; a copy they already downloaded cannot be taken back.",
            )
    else:
        messages.error(request, "Choose a contact who has accepted an invitation.")
    return redirect("vault:incident", pk=item.incident_id)


@login_required
@require_POST
def share_revoke(request, pk):
    share_obj = get_object_or_404(
        EvidenceShare.objects.select_related("item__incident"), pk=pk, item__incident__owner=request.user
    )
    services.revoke_share(request.user, share_obj)
    messages.success(request, "Access revoked. They can no longer open this item.")
    return redirect("vault:incident", pk=share_obj.item.incident_id)


@login_required
@require_POST
def export(request, pk):
    incident = _own_incident(request, pk)

    def _ids(name):
        out = []
        for raw in request.POST.getlist(name):
            try:
                out.append(uuid.UUID(raw))
            except ValueError:
                continue
        return out

    entry_ids, item_ids = _ids("entry"), _ids("item")
    entries = incident.entries.all()
    items = incident.items.filter(deleted_at__isnull=True)
    if entry_ids or item_ids:
        entries = entries.filter(pk__in=entry_ids)
        items = items.filter(pk__in=item_ids)
    payload, filename = services.build_pack(request.user, incident, list(entries), list(items))
    response = HttpResponse(payload, content_type="application/zip")
    response["Content-Disposition"] = content_disposition_header(True, filename)
    response["Cache-Control"] = "private, no-store"
    return response


# ---- what a trusted contact can see: only items explicitly shared with them ----

@login_required
def shared_list(request):
    shares = services.shares_visible_to(request.user).order_by("-created_at")
    return render(request, "vault/shared.html", {"shares": shares})


@login_required
def shared_download(request, pk):
    share_obj = get_object_or_404(services.shares_visible_to(request.user), pk=pk)
    item = share_obj.item
    data, _ = services.open_item(item)
    if data is None:
        messages.error(request, "This file could not be read.")
        return redirect("vault:shared_list")
    services.record_access(item, request.user, EvidenceAccessEvent.Action.SHARED_DOWNLOAD)
    audit.record(request.user, "evidence.shared_downloaded", item)
    return _file_response(item, data)
