#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

# V1.6-only repair. Does not run migrations or modify any database.
PROJECT_DIR="${HOME}/Downloads/LESEDI/LESEDI_v1.6_Redesign_Amani/lesedi"
COMPOSE_PROJECT="lesedi-v16"
SERVICE="web"
TARGET="/app/guardian/views.py"

log() { printf '[%s] %s\n' "$1" "$2"; }
die() { log ERROR "$1" >&2; exit 1; }

[[ -d "$PROJECT_DIR" ]] || die "V1.6 directory not found: $PROJECT_DIR"
command -v docker >/dev/null 2>&1 || die "Docker is not available."
docker compose version >/dev/null 2>&1 || die "Docker Compose plugin is unavailable."
cd "$PROJECT_DIR"

if ! docker compose -p "$COMPOSE_PROJECT" ps --status running --services | grep -Fxq "$SERVICE"; then
  die "V1.6 web service is not running. Start V1.6 first; no changes made."
fi

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="$PROJECT_DIR/backups/sos_anonymous_user_fix_retry_$STAMP"
mkdir -p "$BACKUP_DIR"

log INFO "Verifying the V1.6 SOS view."
docker compose -p "$COMPOSE_PROJECT" exec -T "$SERVICE" sh -lc \
  'test -f /app/guardian/views.py && grep -q "^def sos_page(request):" /app/guardian/views.py' \
  || die "Expected V1.6 /app/guardian/views.py and sos_page(request) were not found."

docker compose -p "$COMPOSE_PROJECT" exec -T "$SERVICE" sh -lc "cat '$TARGET'" > "$BACKUP_DIR/views.py.before"
[[ -s "$BACKUP_DIR/views.py.before" ]] || die "Backup failed; refusing to continue."
chmod 600 "$BACKUP_DIR/views.py.before"

log INFO "Patching sos_page() using a temporary file on the same filesystem."
docker compose -p "$COMPOSE_PROJECT" exec -T "$SERVICE" python - <<'PY'
from pathlib import Path
import ast
import os
import re
import uuid

path = Path("/app/guardian/views.py")
source = path.read_text()
pattern = re.compile(r"(?ms)^def sos_page\(request\):\n(?P<body>.*?)(?=^def |\Z)")
match = pattern.search(source)
if not match:
    raise SystemExit("Could not isolate sos_page(request); no edit made.")

body = match.group("body")
if re.search(r"request\.user\.is_authenticated", body):
    print("sos_page() already contains an authentication guard; no source edit needed.")
    raise SystemExit(0)

target = "    plan = get_or_create_plan(request.user)"
if body.count(target) != 1:
    raise SystemExit("Expected exactly one plan creation call in sos_page(); no edit made.")

# Ensure redirect is imported from django.shortcuts.
if not re.search(r"(?m)^from django\.shortcuts import .*\bredirect\b", source):
    shortcut_import = re.search(r"(?m)^from django\.shortcuts import ([^\n]+)$", source)
    if shortcut_import:
        imports = shortcut_import.group(1).strip()
        if imports.startswith("("):
            raise SystemExit("Multiline django.shortcuts import; refusing uncertain edit.")
        source = source[:shortcut_import.start(1)] + imports + ", redirect" + source[shortcut_import.end(1):]
    else:
        source = "from django.shortcuts import redirect\n" + source
    match = pattern.search(source)
    if not match:
        raise SystemExit("Could not re-find sos_page() after preparing import.")
    body = match.group("body")

guard = (
    "    if not request.user.is_authenticated:\n"
    '        return redirect("accounts:login")\n'
)
new_body = body.replace(target, guard + target, 1)
updated = source[:match.start("body")] + new_body + source[match.end("body"):]
new_match = pattern.search(updated)
assert new_match
assert new_match.group("body").find("request.user.is_authenticated") < new_match.group("body").find(target)
ast.parse(updated)
compile(updated, str(path), "exec")

# Write temp file in the target directory so os.replace stays on one filesystem.
temp_path = path.parent / f".views.py.lesedi-v16-fix-{uuid.uuid4().hex}.tmp"
try:
    temp_path.write_text(updated)
    os.chmod(temp_path, path.stat().st_mode)
    # Read back and syntax-check the exact bytes before atomic replacement.
    candidate = temp_path.read_text()
    compile(candidate, str(path), "exec")
    os.replace(temp_path, path)
finally:
    try:
        temp_path.unlink()
    except FileNotFoundError:
        pass

print("Authentication guard installed before get_or_create_plan(request.user).")
PY

log INFO "Running Django system checks."
if ! docker compose -p "$COMPOSE_PROJECT" exec -T "$SERVICE" python manage.py check; then
  log ERROR "Django checks failed; restoring the pre-retry view backup."
  docker compose -p "$COMPOSE_PROJECT" exec -T "$SERVICE" sh -lc "cat > '$TARGET'" < "$BACKUP_DIR/views.py.before"
  docker compose -p "$COMPOSE_PROJECT" exec -T "$SERVICE" python -m py_compile "$TARGET" \
    || log ERROR "Restored file did not pass py_compile; inspect the backup."
  die "Repair rolled back. Backup retained at $BACKUP_DIR"
fi

log INFO "Repair completed successfully."
printf 'Modified file: %s (Compose project %s)\n' "$TARGET" "$COMPOSE_PROJECT"
printf 'Backup: %s\n' "$BACKUP_DIR/views.py.before"
printf 'Database schema: unchanged; no migrations run.\n'
printf 'Legacy and V1.4 instances: not targeted.\n'
printf 'Logged-out visitors: redirected to the accounts:login route.\n'
