#!/usr/bin/env bash
# Guarded repair for findings in LESEDI V1.6 audit.
# Only targets lesedi-v16 and the specified project directory.
# Does not restart/stop containers, run migrations, alter DB rows, send messages, or touch V1/V1.4.
set -Eeuo pipefail
umask 077
PROJECT="lesedi-v16"
ROOT="$HOME/Downloads/LESEDI/LESEDI_v1.6_Redesign_Amani/lesedi"
MODE="${1:-audit}"
STAMP="$(date +%Y%m%d_%H%M%S)"
say(){ printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"; }
fail(){ echo "[ERROR] $*" >&2; exit 1; }
case "$MODE" in audit|fix) ;; *) fail "Usage: $0 [audit|fix]" ;; esac
command -v docker >/dev/null 2>&1 || fail "Docker is required."
[[ -d "$ROOT" ]] || fail "V1.6 directory not found: $ROOT"
cd "$ROOT"
[[ -f config/settings.py && -f .env ]] || fail "Expected config/settings.py or .env is missing; no changes made."
docker compose version >/dev/null 2>&1 || fail "Docker Compose unavailable."
docker compose -p "$PROJECT" ps --services --filter status=running | grep -qx web || fail "V1.6 web container is not running; no changes made."
REPORT="reports/repair_audit_${STAMP}"
BACKUP="backups/repair_audit_${STAMP}"
mkdir -p "$REPORT" "$BACKUP"; chmod 700 "$REPORT" "$BACKUP"
cp -p config/settings.py "$BACKUP/settings.py.before"
sha256sum config/settings.py > "$BACKUP/settings.sha256.before"

say "Collecting exact settings and failing test expectations."
docker compose -p "$PROJECT" exec -T web sh -lc \
  "sed -n '1,300p' /app/config/settings.py; echo '--- tests ---'; sed -n '140,200p' /app/tests/test_accounts_security.py" \
  > "$REPORT/settings-and-tests.txt" 2>&1 || true
docker compose -p "$PROJECT" exec -T web python manage.py makemigrations --check --dry-run \
  > "$REPORT/makemigrations-before.txt" 2>&1 || true
docker compose -p "$PROJECT" exec -T web pytest -q \
  > "$REPORT/tests-before.txt" 2>&1 || true
docker compose -p "$PROJECT" exec -T web python manage.py check --deploy \
  > "$REPORT/deploy-check-before.txt" 2>&1 || true

if [[ "$MODE" == "audit" ]]; then
  say "Audit-only mode. No code or settings changed."
  say "Review $REPORT/settings-and-tests.txt and $REPORT/tests-before.txt"
  exit 0
fi

say "Applying narrowly guarded settings patch."
python3 - <<'PY'
from pathlib import Path
import re, sys
p = Path("config/settings.py")
s = p.read_text()
original = s

# Do not patch if the project uses a different configuration pattern.
if "DJANGO_SECRET_KEY" not in s or "EVIDENCE_ENCRYPTION_KEYS" not in s:
    raise SystemExit("STOP: expected secret configuration references were not found. No patch applied.")
if not re.search(r"(?m)^DEBUG\s*=", s):
    raise SystemExit("STOP: no top-level DEBUG assignment. No patch applied.")

# Ensure os is imported.
if not re.search(r"(?m)^\s*import os\s*$", s):
    imports = list(re.finditer(r"(?m)^(?:from\s+\S+\s+import\s+.+|import\s+\S+.*)$", s))
    if imports:
        pos = imports[-1].end()
        s = s[:pos] + "\nimport os" + s[pos:]
    else:
        s = "import os\n" + s

# Normalize DEBUG to honour the environment variable used by the security tests.
m = re.search(r"(?m)^DEBUG\s*=.*$", s)
if m:
    s = s[:m.start()] + 'DEBUG = os.environ.get("DJANGO_DEBUG", os.environ.get("DEBUG", "1")).strip().lower() in ("1", "true", "yes", "on")' + s[m.end():]

# Fail closed in production if either required key is absent/weak.
guard = '''
# LESEDI_V16_PRODUCTION_SECRET_GUARD
if not DEBUG:
    _lesedi_secret = os.environ.get("DJANGO_SECRET_KEY", "").strip()
    if (not _lesedi_secret or _lesedi_secret.startswith("django-insecure-")
            or len(_lesedi_secret) < 50 or len(set(_lesedi_secret)) < 5):
        raise RuntimeError("DJANGO_SECRET_KEY must be set to a strong random value when DEBUG=False")
    if not os.environ.get("EVIDENCE_ENCRYPTION_KEYS", "").strip():
        raise RuntimeError("EVIDENCE_ENCRYPTION_KEYS must be set when DEBUG=False")
'''
if "LESEDI_V16_PRODUCTION_SECRET_GUARD" not in s:
    m = re.search(r"(?m)^DEBUG\s*=.*$", s)
    s = s[:m.end()] + "\n" + guard + s[m.end():]

# Secure cookies/redirect only when DEBUG=False. HSTS stays opt-in until domain/TLS verified.
security = '''
# LESEDI_V16_PRODUCTION_SECURITY_GUARD
if not DEBUG:
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "true").strip().lower() in ("1", "true", "yes", "on")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    SECURE_HSTS_SECONDS = int(os.environ.get("DJANGO_SECURE_HSTS_SECONDS", "0"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get("DJANGO_HSTS_INCLUDE_SUBDOMAINS", "false").strip().lower() in ("1", "true", "yes", "on")
    SECURE_HSTS_PRELOAD = os.environ.get("DJANGO_HSTS_PRELOAD", "false").strip().lower() in ("1", "true", "yes", "on")
'''
if "LESEDI_V16_PRODUCTION_SECURITY_GUARD" not in s:
    s = s.rstrip() + "\n\n" + security + "\n"

if s != original:
    p.write_text(s)
    print("Updated config/settings.py with production secret guards and production-only cookie/HTTPS settings.")
else:
    print("Settings already contain the guarded patch; no edit needed.")
PY

say "Validating syntax and checks. No migrations are run."
if ! docker compose -p "$PROJECT" exec -T web python -m py_compile /app/config/settings.py > "$REPORT/pycompile.txt" 2>&1; then
  echo "Compile failed; restoring settings backup." >&2
  cp -p "$BACKUP/settings.py.before" config/settings.py
  exit 1
fi
if ! docker compose -p "$PROJECT" exec -T web python manage.py check > "$REPORT/django-check-after.txt" 2>&1; then
  echo "Django check failed; restoring settings backup." >&2
  cp -p "$BACKUP/settings.py.before" config/settings.py
  exit 1
fi

say "Re-running the targeted tests and migration drift check."
docker compose -p "$PROJECT" exec -T web pytest -q > "$REPORT/tests-after.txt" 2>&1 || echo "Tests still failing; inspect tests-after.txt" > "$REPORT/tests-status.txt"
docker compose -p "$PROJECT" exec -T web python manage.py makemigrations --check --dry-run > "$REPORT/makemigrations-after.txt" 2>&1 || true
docker compose -p "$PROJECT" exec -T web python manage.py check --deploy > "$REPORT/deploy-check-after.txt" 2>&1 || true

cat > "$REPORT/manual-followup.txt" <<'EOF'
Manual follow-up required:
- Audit showed pending Amani model ID field changes. Do not generate/apply migrations until comparing models with migration history and confirming whether the ID field changes are intended.
- The settings patch does not fix the notification provider, Redis/Celery broker, SOS delivery/acknowledgement, Safety Circle data, TLS/domain, backups, legal review, or accessibility.
- Before setting DJANGO_DEBUG=0, verify a real long random DJANGO_SECRET_KEY, EVIDENCE_ENCRYPTION_KEYS, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, valid HTTPS termination, static/media configuration and a staging rollback.
- HSTS remains disabled by default. Only set DJANGO_SECURE_HSTS_SECONDS after HTTPS works across the entire domain.
- No container restart, migration, database write, real notification or SOS activation was performed.
EOF
cat > "$REPORT/summary.txt" <<EOF
Targeted V1.6 repair run: $(date -Is)
Mode: $MODE
Backup: $BACKUP
Report: $REPORT
Review tests-after.txt, makemigrations-after.txt, deploy-check-after.txt and manual-followup.txt.
EOF
chmod -R go-rwx "$REPORT" "$BACKUP" 2>/dev/null || true
say "Finished. Read $REPORT/summary.txt"
