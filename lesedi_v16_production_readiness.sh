#!/usr/bin/env bash
# LESEDI V1.6 production-readiness audit and guarded repairs.
# Targets ONLY the V1.6 directory and Compose project lesedi-v16.
# Never stops/removes containers, deletes volumes, prints secrets, or sends real alerts.
set -Eeuo pipefail
umask 077

EXPECTED_DIR="$HOME/Downloads/LESEDI/LESEDI_v1.6_Redesign_Amani/lesedi"
PROJECT="lesedi-v16"
HOST_PORT="8016"
STAMP="$(date +%Y%m%d_%H%M%S)"
MODE="${1:-audit}"
say(){ printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"; }
warn(){ printf '[WARN] %s\n' "$*" >&2; }
fail(){ printf '[ERROR] %s\n' "$*" >&2; exit 1; }

case "$MODE" in audit|safe-fix) ;; *) fail "Usage: $0 [audit|safe-fix]" ;; esac
command -v docker >/dev/null 2>&1 || fail "Docker is required."
[[ -d "$EXPECTED_DIR" ]] || fail "V1.6 directory not found: $EXPECTED_DIR"
cd "$EXPECTED_DIR"
[[ -f docker-compose.yml || -f compose.yml || -f compose.yaml || -f docker-compose.yaml ]] || fail "Compose file not found."
docker compose version >/dev/null 2>&1 || fail "Docker Compose plugin unavailable."

REPORT_DIR="$EXPECTED_DIR/reports/production_readiness_$STAMP"
BACKUP_DIR="$EXPECTED_DIR/backups/production_readiness_$STAMP"
mkdir -p "$REPORT_DIR" "$BACKUP_DIR"
chmod 700 "$REPORT_DIR" "$BACKUP_DIR"

cat > "$REPORT_DIR/README.txt" <<EOF
LESEDI V1.6 production-readiness audit
Date: $(date -Is)
Project: $PROJECT
Mode: $MODE
No containers or volumes removed; no real notification dispatched.
EOF

say "Checking project and container status."
docker compose -p "$PROJECT" ps > "$REPORT_DIR/compose-services.txt" 2>&1 || warn "Could not read V1.6 Compose status."
docker ps --format '{{.Names}} {{.Ports}}' > "$REPORT_DIR/docker-ps.txt"
if grep -qE 'lesedi-web-1|lesedi_default|127\.0\.0\.1:8000' "$REPORT_DIR/docker-ps.txt"; then
  say "Legacy instance detected. It will not be modified."
fi

say "Creating backups of candidate source/config files; excluding .env and user data."
for f in docker-compose.yml compose.yml compose.yaml docker-compose.yaml Dockerfile requirements.txt requirements-dev.txt; do
  if [[ -f "$f" ]]; then mkdir -p "$BACKUP_DIR/$(dirname "$f")"; cp -p -- "$f" "$BACKUP_DIR/$f"; fi
done
for d in accounts guardian core evidence templates; do
  if [[ -d "$d" ]]; then
    tar --exclude='*/.env' --exclude='*/media' --exclude='*/uploads' --exclude='*/__pycache__' --exclude='*/.git' --exclude='*/.venv' \
      -czf "$BACKUP_DIR/${d}.tar.gz" "$d" 2>/dev/null || warn "Partial backup of $d."
  fi
done

say "Checking environment variable presence without printing secret values."
if [[ -f .env ]]; then
  chmod 600 .env 2>/dev/null || warn "Could not set .env permissions."
  python3 - <<'PY' > "$REPORT_DIR/env-presence.txt"
from pathlib import Path
keys = {
 "DEBUG": ["DEBUG"], "ALLOWED_HOSTS": ["ALLOWED_HOSTS"],
 "CSRF_TRUSTED_ORIGINS": ["CSRF_TRUSTED_ORIGINS"],
 "DJANGO_SECRET_KEY": ["DJANGO_SECRET_KEY"],
 "POSTGRES_PASSWORD": ["POSTGRES_PASSWORD"],
 "REDIS_URL": ["REDIS_URL"], "CELERY_BROKER_URL": ["CELERY_BROKER_URL"],
 "LESEDI_NOTIFICATION_MODE": ["LESEDI_NOTIFICATION_MODE"],
 "EVIDENCE_ENCRYPTION_KEYS": ["EVIDENCE_ENCRYPTION_KEYS"],
 "SMS/WhatsApp provider credentials": ["TWILIO_ACCOUNT_SID","TWILIO_AUTH_TOKEN","TWILIO_API_KEY","WHATSAPP_ACCESS_TOKEN","INFOBIP_API_KEY","VONAGE_API_KEY"],
}
env={}
for raw in Path(".env").read_text(errors="ignore").splitlines():
    line=raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k,v=line.split("=",1); env[k.strip()]=v.strip().strip("'").strip('"')
for label,names in keys.items():
    print(f"{label}: {'SET' if any(env.get(n) for n in names) else 'NOT SET'}")
if env.get("DEBUG","").lower() in ("true","1","yes","on"): print("WARNING: DEBUG appears enabled")
if env.get("LESEDI_NOTIFICATION_MODE","").lower() in ("simulation","simulated","console","log"): print("WARNING: notification mode appears non-production")
if "memory://" in env.get("CELERY_BROKER_URL","").lower(): print("WARNING: Celery broker appears in-memory")
if not env.get("REDIS_URL"): print("WARNING: Redis URL is empty")
PY
else
  echo ".env NOT FOUND" > "$REPORT_DIR/env-presence.txt"
  warn ".env is missing; no secrets will be generated."
fi

say "Running read-only Django checks where V1.6 web service is running."
if docker compose -p "$PROJECT" ps --services --filter status=running | grep -qx web; then
  docker compose -p "$PROJECT" exec -T web python manage.py check > "$REPORT_DIR/django-check.txt" 2>&1 || warn "Django check failed."
  docker compose -p "$PROJECT" exec -T web python manage.py check --deploy > "$REPORT_DIR/django-deploy-check.txt" 2>&1 || warn "Deployment checks report issues."
  docker compose -p "$PROJECT" exec -T web python manage.py showmigrations > "$REPORT_DIR/migrations.txt" 2>&1 || warn "Could not inspect migrations."
  docker compose -p "$PROJECT" exec -T web python manage.py makemigrations --check --dry-run > "$REPORT_DIR/makemigrations-check.txt" 2>&1 || warn "Migration consistency check failed."
  docker compose -p "$PROJECT" exec -T web sh -lc 'if command -v pytest >/dev/null 2>&1; then pytest -q; else python manage.py test; fi' > "$REPORT_DIR/tests.txt" 2>&1 || warn "Tests failed or unavailable."
  docker compose -p "$PROJECT" exec -T web python -c '
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", os.environ.get("DJANGO_SETTINGS_MODULE","config.settings"))
try:
 import django; django.setup()
 from django.conf import settings
 for k in ("DEBUG","ALLOWED_HOSTS","CSRF_TRUSTED_ORIGINS","SECURE_SSL_REDIRECT","SESSION_COOKIE_SECURE","CSRF_COOKIE_SECURE","SECURE_HSTS_SECONDS","SECURE_CONTENT_TYPE_NOSNIFF","SECURE_REFERRER_POLICY"):
  v=getattr(settings,k,None)
  if k in ("ALLOWED_HOSTS","CSRF_TRUSTED_ORIGINS"): v="configured" if v else "EMPTY"
  print(f"{k}: {v}")
except Exception as e: print("Could not inspect settings:",type(e).__name__,str(e)[:200])
' > "$REPORT_DIR/django-security-settings.txt" 2>&1 || warn "Could not inspect security settings."
  docker compose -p "$PROJECT" exec -T web sh -lc \
    "grep -RniE 'get_or_create_plan|def sos_page|No responders are configured|notification_mode|SIMULATION|celery|rate.limit|FileExtensionValidator|upload_to' /app/guardian /app/core /app/accounts /app/evidence /app/templates 2>/dev/null | head -300" \
    > "$REPORT_DIR/sos-notifications-upload-review.txt" || true
else
  warn "V1.6 web service is not running; skipped runtime checks."
fi

say "Capturing recent service logs (common secret patterns redacted)."
docker compose -p "$PROJECT" logs --tail=250 web worker beat redis db > "$REPORT_DIR/recent-service-logs.txt" 2>&1 || true
python3 - "$REPORT_DIR/recent-service-logs.txt" <<'PY'
import re,sys
from pathlib import Path
p=Path(sys.argv[1]); s=p.read_text(errors="ignore")
s=re.sub(r'(?i)(password|passwd|secret_key|api[_-]?key|access[_-]?token|auth[_-]?token)(\s*[=:]\s*)[^\s,;]+',r'\1\2[REDACTED]',s)
s=re.sub(r'(?i)(postgres(?:ql)?://[^:\s]+:)[^@\s]+(@)',r'\1[REDACTED]\2',s)
p.write_text(s)
PY

say "Checking local HTTP responses only; no SOS activation is triggered."
if command -v curl >/dev/null 2>&1; then
  curl -sS --max-time 5 -o /dev/null -w 'V1.6 root HTTP status: %{http_code}\n' "http://127.0.0.1:${HOST_PORT}/" > "$REPORT_DIR/http-probe.txt" 2>&1 || echo "Root HTTP probe failed." >> "$REPORT_DIR/http-probe.txt"
  curl -sS --max-time 5 -o /dev/null -w 'Anonymous SOS HTTP status: %{http_code}\n' "http://127.0.0.1:${HOST_PORT}/guardian/sos/" >> "$REPORT_DIR/http-probe.txt" 2>&1 || echo "Anonymous SOS probe failed." >> "$REPORT_DIR/http-probe.txt"
fi

cat > "$REPORT_DIR/manual-release-gates.txt" <<'EOF'
MANUAL RELEASE GATES — REQUIRED
1. SOS: synthetic account + consenting test responders; verify event timestamps/status, cancel, duplicate/idempotency, network loss/reconnect and responder acknowledgement.
2. Notifications: configure a real provider in secret storage; verify callback signatures, retry policy, delivery statuses, timeouts, dead-letter/failure alerts and fallback. This script sends no real messages.
3. Safety Circle: verify saved responder records, active consent, contact validity and correct owner/query filtering. Do not remove the empty-responder safeguard just to enable SOS.
4. Authorization: two synthetic users; attempt cross-account access to plans, contacts, activations, location, evidence and downloads.
5. Evidence: inspect size/type validation, malware scanning, storage permissions, encryption, retention, deletion and audit requirements.
6. Backups: encrypted scheduled off-host backups; restore to an isolated test database. No restore is performed here.
7. Production: HTTPS, DEBUG=False, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, secure cookies, HSTS, static/media storage, database restrictions, monitoring, rollback and incident ownership.
8. Legal: POPIA/privacy review, Information Officer, incident response, accurate support contacts and written partner agreements. This script does not certify compliance.
9. Accessibility: reviewed translations; SASL needs suitable visual content; test screen readers, low-cost Android, low bandwidth and survivor-safe behavior.
10. Independent review: threat model, dependency/container scan, penetration test, load/failure tests, staging go/no-go and rollback.
EOF

if [[ "$MODE" == "safe-fix" ]]; then
  say "Applying only low-risk, reversible safeguards."
  if [[ -f .env ]]; then chmod 600 .env && echo ".env permissions set to 600 (best effort)." > "$REPORT_DIR/safe-fixes.txt"; fi
  if [[ ! -e .gitignore ]]; then
    cat > .gitignore <<'EOF'
.env
.env.*
!.env.example
*.pem
*.key
*.p12
*.pfx
__pycache__/
*.py[cod]
.pytest_cache/
.coverage
htmlcov/
media/
uploads/
reports/
backups/
EOF
    chmod 600 .gitignore
    echo "Created .gitignore; existing files were not overwritten." >> "$REPORT_DIR/safe-fixes.txt"
  else
    echo "Existing .gitignore preserved; review manually." >> "$REPORT_DIR/safe-fixes.txt"
  fi
  # Intentionally do not auto-edit auth, responder gating, provider configuration,
  # Django settings, compose topology, migrations or data without code/schema review.
fi

cat > "$REPORT_DIR/summary.txt" <<EOF
LESEDI V1.6 audit finished: $(date -Is)
Mode: $MODE
Report: $REPORT_DIR
Backup: $BACKUP_DIR
Review env-presence.txt, django-check.txt, django-deploy-check.txt,
makemigrations-check.txt, tests.txt, django-security-settings.txt,
sos-notifications-upload-review.txt, recent-service-logs.txt,
http-probe.txt and manual-release-gates.txt.
This is an audit aid, not production certification. No real messages sent.
No containers or volumes removed; no database rows intentionally modified.
EOF
chmod -R go-rwx "$REPORT_DIR" "$BACKUP_DIR" 2>/dev/null || true
say "Completed. Read: $REPORT_DIR/summary.txt"
[[ "$MODE" == "audit" ]] && say "For low-risk safeguards only, run: $0 safe-fix"
