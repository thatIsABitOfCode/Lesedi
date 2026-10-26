#!/usr/bin/env bash
# LESEDI V1.6 SOS Mode installer. Targets only Compose project lesedi-v16.
# Adds a dedicated SOS page, browser location capture, activation location storage,
# and location display to authorised Guardian responders. Does NOT contact police.
set -Eeuo pipefail
IFS=$'\n\t'

PROJECT_DIR="${LESEDI_V16_DIR:-$HOME/Downloads/LESEDI/LESEDI_v1.6_Redesign_Amani/lesedi}"
COMPOSE=(docker compose -p lesedi-v16)
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="$PROJECT_DIR/backups/sos_mode_$STAMP"

log(){ printf '\n[INFO] %s\n' "$*"; }
warn(){ printf '\n[WARN] %s\n' "$*" >&2; }
die(){ printf '\n[ERROR] %s\n' "$*" >&2; exit 1; }

on_error(){ local rc=$?; warn "Stopped at line ${BASH_LINENO[0]:-unknown} (exit $rc). No database migration is automatically forced."; warn "Review project files and backup directory: $BACKUP_DIR"; exit "$rc"; }
trap on_error ERR

[[ -d "$PROJECT_DIR" ]] || die "V1.6 project directory not found: $PROJECT_DIR. Set LESEDI_V16_DIR if your path differs."
cd "$PROJECT_DIR"
[[ -f manage.py && -f docker-compose.yml ]] || die "manage.py or docker-compose.yml missing; refusing to modify this directory."
command -v docker >/dev/null 2>&1 || die "Docker is not installed or not on PATH."
docker compose version >/dev/null 2>&1 || die "Docker Compose plugin is unavailable."

# Strong isolation check: compose project must be exactly lesedi-v16.
COMPOSE_PROJECT_NAME=lesedi-v16 "${COMPOSE[@]}" config --quiet || die "Compose configuration is invalid. Fix it before continuing."
for svc in web db; do
  if ! "${COMPOSE[@]}" ps --status running --services | grep -Fxq "$svc"; then
    die "V1.6 service '$svc' is not running. Start only this project with: docker compose -p lesedi-v16 up -d"
  fi
done

log "Checking active V1.6 source files and existing Guardian integration."
for f in guardian/models.py guardian/api.py guardian/views.py guardian/urls.py guardian/services.py safety/models.py templates/base.html; do
  [[ -f "$f" ]] || die "Expected file missing: $f. This script is designed for the supplied LESEDI V1.6 structure."
done
if grep -q 'class GuardianActivation' guardian/models.py && grep -q 'class ActivateView' guardian/api.py && grep -q 'def ack_page' guardian/views.py; then :; else
  die "Guardian source does not match the expected V1.6 structure. No files changed."
fi

mkdir -p "$BACKUP_DIR/files"
backup_file(){ local f="$1"; mkdir -p "$BACKUP_DIR/files/$(dirname "$f")"; cp -a "$f" "$BACKUP_DIR/files/$f"; }
for f in guardian/models.py guardian/api.py guardian/views.py guardian/urls.py templates/guardian/ack.html; do
  [[ -f "$f" ]] && backup_file "$f"
done
if [[ -d guardian/migrations ]]; then
  cp -a guardian/migrations "$BACKUP_DIR/guardian_migrations_before"
fi
if [[ -f templates/guardian/sos.html ]]; then backup_file templates/guardian/sos.html; fi
log "Source backups saved to $BACKUP_DIR/files"

# Patch using exact, idempotent Python transformations. Abort if source differs unexpectedly.
python3 - <<'PY'
from pathlib import Path

root = Path.cwd()
def patch(path, old, new, label):
    p = root / path
    text = p.read_text()
    if new in text:
        print(f"[INFO] Already present: {label}")
        return
    if old not in text:
        raise SystemExit(f"[ERROR] Cannot safely patch {path}: expected anchor missing ({label}). No blind replacement performed.")
    p.write_text(text.replace(old, new, 1))
    print(f"[INFO] Added: {label}")

patch(
    "guardian/models.py",
    '    closed_at = models.DateTimeField(null=True, blank=True)\n    created_at = models.DateTimeField(auto_now_add=True)\n',
    '    closed_at = models.DateTimeField(null=True, blank=True)\n'
    '    # Optional device location supplied at SOS activation; private to this activation.\n'
    '    location_latitude = models.FloatField(null=True, blank=True)\n'
    '    location_longitude = models.FloatField(null=True, blank=True)\n'
    '    location_accuracy_m = models.FloatField(null=True, blank=True)\n'
    '    location_captured_at = models.DateTimeField(null=True, blank=True)\n'
    '    created_at = models.DateTimeField(auto_now_add=True)\n',
    "activation location fields")

patch(
    "guardian/api.py",
    'from django.utils import timezone\n',
    'from django.utils import timezone\n',
    "datetime parser import")

patch(
    "guardian/api.py",
    '        "ack_timeout_seconds": a.ack_timeout_seconds,\n',
    '        "ack_timeout_seconds": a.ack_timeout_seconds,\n'
    '        "location": ({"latitude": a.location_latitude, "longitude": a.location_longitude,\n'
    '                      "accuracy_m": a.location_accuracy_m, "captured_at": _iso(a.location_captured_at)}\n'
    '                     if a.location_latitude is not None and a.location_longitude is not None else None),\n',
    "location in activation API response")

patch(
    "guardian/api.py",
    '        except services.NoActivePlan as exc:\n'
    '            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)\n'
    '        return Response(serialize(a), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)\n',
    '        except services.NoActivePlan as exc:\n'
    '            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)\n'
    '        # Location is optional: an SOS must still activate if GPS is unavailable or denied.\n'
    '        lat = request.data.get("latitude")\n'
    '        lon = request.data.get("longitude")\n'
    '        accuracy = request.data.get("accuracy_m")\n'
    '        try:\n'
    '            if lat not in (None, "") and lon not in (None, ""):\n'
    '                lat, lon = float(lat), float(lon)\n'
    '                accuracy = float(accuracy) if accuracy not in (None, "") else None\n'
    '                if not (-90 <= lat <= 90 and -180 <= lon <= 180):\n'
    '                    raise ValueError("Coordinates are outside valid ranges.")\n'
    '                if accuracy is not None and not (0 <= accuracy <= 100000):\n'
    '                    raise ValueError("Location accuracy is outside valid range.")\n'
    '                a.location_latitude = lat\n'
    '                a.location_longitude = lon\n'
    '                a.location_accuracy_m = accuracy\n'
    '                a.location_captured_at = timezone.now()\n'
    '                a.save(update_fields=["location_latitude", "location_longitude", "location_accuracy_m", "location_captured_at", "updated_at"])\n'
    '            else:\n'
    '                # Never show coordinates from an earlier activation as if they were current.\n'
    '                a.location_latitude = None\n'
    '                a.location_longitude = None\n'
    '                a.location_accuracy_m = None\n'
    '                a.location_captured_at = None\n'
    '                a.save(update_fields=["location_latitude", "location_longitude", "location_accuracy_m", "location_captured_at", "updated_at"])\n'
    '        except (TypeError, ValueError):\n'
    '            return Response({"detail": "Location coordinates were invalid. Guardian Mode may still be active; refresh status before retrying."}, status=status.HTTP_400_BAD_REQUEST)\n'
    '        return Response(serialize(a), status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)\n',
    "optional location validation and storage")

patch(
    "guardian/views.py",
    'def ack_page(request, token):\n',
    'def sos_page(request):\n'
    '    """Dedicated SOS screen; activation uses the existing authenticated Guardian API."""\n'
    '    plan = get_or_create_plan(request.user)\n'
    '    responders = list(plan.responders.select_related("contact"))\n'
    '    return render(request, "guardian/sos.html", {\n'
    '        "plan": plan, "responders": responders, "sim_notice": services.SIM_NOTICE,\n'
    '        "limits": services.LIMITS_NOTICE})\n'
    '\n\n'
    'def ack_page(request, token):\n',
    "dedicated SOS page view")

patch(
    "guardian/views.py",
    '    # The instruction is only shown when the owner granted this exact permission.\n'
    '    if has_permission(activation.plan, contact, Permission.RECEIVE_INSTRUCTION):\n',
    '    # Location is revealed only to an active, authorised alert recipient.\n'
    '    if has_permission(activation.plan, contact, Permission.RECEIVE_ALERT):\n'
    '        if activation.location_latitude is not None and activation.location_longitude is not None:\n'
    '            ctx["shared_location"] = {\n'
    '                "latitude": activation.location_latitude, "longitude": activation.location_longitude,\n'
    '                "accuracy_m": activation.location_accuracy_m, "captured_at": activation.location_captured_at,\n'
    '                "map_url": f"https://www.openstreetmap.org/?mlat={activation.location_latitude}&mlon={activation.location_longitude}#map=16/{activation.location_latitude}/{activation.location_longitude}",\n'
    '            }\n'
    '    # The instruction is only shown when the owner granted this exact permission.\n'
    '    if has_permission(activation.plan, contact, Permission.RECEIVE_INSTRUCTION):\n',
    "permission-gated responder location display")

patch(
    "guardian/urls.py",
    'urlpatterns = [\n    path("", views.guardian_page, name="page"),\n',
    'urlpatterns = [\n    path("", views.guardian_page, name="page"),\n    path("sos/", views.sos_page, name="sos"),\n',
    "SOS page route")

patch(
    "templates/guardian/ack.html",
    '{% if instruction %}\n',
    '{% if shared_location %}\n'
    '<section class="card" aria-labelledby="shared-location-heading">\n'
    '  <h2 id="shared-location-heading">Shared emergency location</h2>\n'
    '  <p>Location captured at {{ shared_location.captured_at|date:"Y-m-d H:i:s T" }}.</p>\n'
    '  {% if shared_location.accuracy_m %}<p>Reported accuracy: approximately {{ shared_location.accuracy_m|floatformat:0 }} metres.</p>{% endif %}\n'
    '  <p><a href="{{ shared_location.map_url }}" target="_blank" rel="noopener noreferrer">Open location map</a></p>\n'
    '  <p>Use this information responsibly. It may be inaccurate or outdated.</p>\n'
    '</section>\n'
    '{% endif %}\n\n'
    '{% if instruction %}\n',
    "authorised responder location card")
PY

# Create standalone SOS page (kept separate from other app pages).
cat > templates/guardian/sos.html <<'HTML'
{% extends "base.html" %}
{% block title %}SOS Emergency Mode{% endblock %}
{% block content %}
<section class="card sos-page" aria-labelledby="sos-title">
  <h1 id="sos-title">Emergency Mode</h1>
  {% if SIMULATION_MODE %}<p class="notice sim">{{ sim_notice }}</p>{% endif %}
  <p class="notice">{{ limits }}</p>
  <p>Press SOS to start your saved Guardian response plan. If you allow location access, your current coordinates will be attached to this activation and shown to authorised alert recipients through their secure response link.</p>
  <p><strong>Responders configured:</strong> {{ responders|length }}</p>
  {% if not responders %}<p class="error" role="alert">No responders are configured. Set up your Safety Circle before relying on this feature.</p>{% endif %}
  <button id="lesedi-sos-button" class="btn big danger sos-button" type="button" {% if not responders %}disabled{% endif %} aria-describedby="sos-status">SOS — Activate Emergency Mode</button>
  <p id="sos-status" role="status" aria-live="polite">Ready. Press SOS only when you want to activate your saved response plan.</p>
  <section id="sos-result" class="card" hidden aria-live="polite">
    <h2 id="sos-result-title">Emergency status</h2>
    <p id="sos-result-text"></p>
    <p id="sos-location-text"></p>
    <p><a href="{% url 'guardian:page' %}">Open full Guardian status</a></p>
  </section>
  <p class="help">This button does not contact police or emergency services. No such dispatch integration is configured by this feature. If you are in immediate danger, contact local emergency services directly. If location permission is denied or GPS fails, Guardian Mode can still activate without location.</p>
</section>
{% endblock %}
{% block scripts %}
<script>
(() => {
  "use strict";
  const button = document.getElementById("lesedi-sos-button");
  const statusNode = document.getElementById("sos-status");
  const result = document.getElementById("sos-result");
  const resultText = document.getElementById("sos-result-text");
  const locationText = document.getElementById("sos-location-text");
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  let inFlight = false;
  const idempotencyKey = () => {
    try {
      const key = window.crypto?.randomUUID?.();
      return key || (`sos-${Date.now()}-${Math.random().toString(16).slice(2)}`);
    } catch (_) { return `sos-${Date.now()}`; }
  };
  function setStatus(message) { statusNode.textContent = message; }
  function getLocation() {
    return new Promise(resolve => {
      if (!navigator.geolocation) return resolve(null);
      navigator.geolocation.getCurrentPosition(
        pos => resolve({ latitude: pos.coords.latitude, longitude: pos.coords.longitude, accuracy_m: pos.coords.accuracy }),
        () => resolve(null),
        { enableHighAccuracy: true, timeout: 7000, maximumAge: 60000 }
      );
    });
  }
  button?.addEventListener("click", async () => {
    if (inFlight) return;
    inFlight = true;
    button.disabled = true;
    result.hidden = true;
    setStatus("Requesting location permission. Emergency activation will continue if location is unavailable…");
    try {
      const location = await getLocation();
      setStatus("Activating your saved Guardian response plan…");
      const payload = { idempotency_key: idempotencyKey() };
      if (location) Object.assign(payload, location);
      const response = await fetch("/api/guardian/activate/", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf, "Accept": "application/json" },
        body: JSON.stringify(payload)
      });
      let data = {};
      try { data = await response.json(); } catch (_) { /* handle non-JSON error below */ }
      if (!response.ok) {
        if (response.status === 401 || response.status === 403) {
          throw new Error("Your session may have expired or this account is not permitted to activate SOS. Sign in and try again when safe.");
        }
        throw new Error(data.detail || `Activation failed (HTTP ${response.status}). Check your Safety Plan and Guardian setup.`);
      }
      result.hidden = false;
      document.getElementById("sos-result-title").textContent = data.is_simulation ? "Simulation activation started" : "Guardian activation started";
      resultText.textContent = `Status: ${data.state_label || data.state || "Activation recorded"}. Notification submission is not proof of delivery or that help is on the way.`;
      locationText.textContent = data.location ? `Location captured (accuracy approximately ${Math.round(data.location.accuracy_m || 0)} m). It is available to authorised alert recipients.` : "Location was not captured. Guardian activation may still have started; share your location another way if it is safe to do so.";
      setStatus(data.is_simulation ? "Simulation mode: no real messages or emergency dispatch occurred." : "Guardian response activation recorded. Check status and delivery outcomes below.");
      if (data.is_simulation) resultText.textContent += " SIMULATION MODE: no real messages were sent.";
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Unexpected error. Check the Guardian page before retrying to avoid duplicate alerts.");
    } finally {
      inFlight = false;
      button.disabled = false;
    }
  });
})();
</script>
<style>
.sos-page { max-width: 760px; margin: 1.5rem auto; }
.sos-button { display: block; width: min(100%, 460px); min-height: 92px; margin: 1.5rem auto; border-radius: 1rem; font-size: 1.25rem; font-weight: 800; background: #b91c1c; color: #fff; border: 3px solid #7f1d1d; }
.sos-button:focus-visible { outline: 4px solid #1d4ed8; outline-offset: 4px; }
.sos-button:disabled { opacity: .55; cursor: not-allowed; }
</style>
{% endblock %}
HTML

log "Running Django checks before migration generation."
"${COMPOSE[@]}" exec -T web python manage.py check

log "Generating the Guardian migration for optional location fields."
"${COMPOSE[@]}" exec -T web python manage.py makemigrations guardian

log "Reviewing the migration plan."
"${COMPOSE[@]}" exec -T web python manage.py migrate guardian --plan

log "Creating a PostgreSQL backup before applying any migration."
if ! "${COMPOSE[@]}" exec -T db sh -lc 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > "$BACKUP_DIR/lesedi_v16_pre_sos.sql"; then
  rm -f "$BACKUP_DIR/lesedi_v16_pre_sos.sql"
  die "Database backup failed. Migration was not applied. Check DB service environment and pg_dump availability."
fi
chmod 600 "$BACKUP_DIR/lesedi_v16_pre_sos.sql"
[[ -s "$BACKUP_DIR/lesedi_v16_pre_sos.sql" ]] || die "Database backup file is empty; refusing to migrate."
log "Database backup saved to $BACKUP_DIR/lesedi_v16_pre_sos.sql"

printf '\nIMPORTANT: Review the migration plan above. This feature stores optional location coordinates on Guardian activations.\n'
printf 'This does NOT contact law enforcement. Existing notification configuration may still be simulation-only.\n'
read -r -p 'Type APPLY to apply pending migrations to V1.6 only, or anything else to stop: ' answer
if [[ "$answer" != "APPLY" ]]; then
  warn "Migration not applied. Source files are backed up at $BACKUP_DIR/files; generated migration may be pending."
  exit 2
fi

log "Applying migrations to the isolated V1.6 database."
"${COMPOSE[@]}" exec -T web python manage.py migrate guardian

log "Running final checks."
"${COMPOSE[@]}" exec -T web python manage.py check
"${COMPOSE[@]}" exec -T web python manage.py showmigrations guardian

log "SOS Mode installation completed."
printf 'SOS page: http://127.0.0.1:8016/guardian/sos/\n'
printf 'Existing Guardian status: http://127.0.0.1:8016/guardian/\n'
printf 'Backups: %s\n' "$BACKUP_DIR"
printf '\nImportant: The app can notify configured Guardians only through the existing notification adapters. This script does not create a police/emergency-service integration. If LESEDI_NOTIFICATION_MODE=simulation, no real messages are sent.\n'
