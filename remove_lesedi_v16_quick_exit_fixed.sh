#!/usr/bin/env bash
# Safely remove the Support & Learning Quick Exit button, its CSS, and its handler.
# Only the lesedi-v16 Compose project is targeted. SOS/Guardian logic is untouched.
set -Eeuo pipefail
IFS=$'\n\t'

PROJECT_DIR="${HOME}/Downloads/LESEDI/LESEDI_v1.6_Redesign_Amani/lesedi"
COMPOSE_PROJECT="lesedi-v16"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${PROJECT_DIR}/backups/remove_quick_exit_fixed_${STAMP}"

log(){ printf '\n[INFO] %s\n' "$*"; }
die(){ printf '\n[ERROR] %s\n' "$*" >&2; exit 1; }
trap 'rc=$?; printf "\n[ERROR] Script stopped at line %s (exit %s).\n" "$LINENO" "$rc" >&2; exit "$rc"' ERR

[[ -d "$PROJECT_DIR" ]] || die "V1.6 project directory not found: $PROJECT_DIR"
command -v docker >/dev/null 2>&1 || die "Docker is unavailable."
docker compose version >/dev/null 2>&1 || die "Docker Compose plugin is unavailable."
cd "$PROJECT_DIR"
docker compose -p "$COMPOSE_PROJECT" ps --status running --services | grep -qx web \
  || die "V1.6 web service is not running. Start it with: docker compose -p lesedi-v16 up -d"

log "Finding the Support & Learning template containing the Quick Exit code."
MATCHES="$(docker compose -p "$COMPOSE_PROJECT" exec -T web sh -lc \
  "grep -RIlE 'lesedi-quick-exit|Quick Exit from Support and Learning' /app --include='*.html' 2>/dev/null || true")"
[[ -n "$MATCHES" ]] || die "No matching Quick Exit implementation found under /app. Nothing changed."
COUNT="$(printf '%s\n' "$MATCHES" | sed '/^[[:space:]]*$/d' | wc -l | tr -d ' ')"
[[ "$COUNT" == 1 ]] || { printf '%s\n' "$MATCHES"; die "Found $COUNT matching templates; refusing to edit multiple files."; }
TARGET="${MATCHES%%$'\n'*}"
[[ "$TARGET" == /app/* ]] || die "Matched path is outside /app. Refusing to edit."

mkdir -p "$BACKUP_DIR/files"
BASENAME="$(basename "$TARGET")"
docker compose -p "$COMPOSE_PROJECT" exec -T web sh -lc "cat '$TARGET'" > "$BACKUP_DIR/files/${BASENAME}.before"
chmod 600 "$BACKUP_DIR/files/${BASENAME}.before"
log "Template backup saved to $BACKUP_DIR/files/${BASENAME}.before"

# Use a quoted heredoc so Bash does not interpret Python regexes or HTML as shell syntax.
docker compose -p "$COMPOSE_PROJECT" exec -T web sh -lc "cat '$TARGET' > /tmp/lesedi_support_without_quick_exit.html"

docker compose -p "$COMPOSE_PROJECT" exec -T web sh -lc 'python -' <<'PY'
from pathlib import Path
import re

path = Path("/tmp/lesedi_support_without_quick_exit.html")
text = path.read_text()

# Remove exactly the button wrapper containing the known unique button ID.
text, button_count = re.subn(
    r'\s*<div class="quick-exit">\s*<button\b[^>]*id="lesedi-quick-exit"[^>]*>.*?</button>\s*</div>\s*',
    '\n',
    text,
    count=1,
    flags=re.I | re.S,
)

# Remove only the two CSS rules introduced for this button.
text = re.sub(r'\s*\.quick-exit\{[^}]*\}', '', text, count=1)
text = re.sub(r'\s*\.quick-exit button\{[^}]*\}', '', text, count=1)

# Remove only the script block that contains the known element ID.
text, js_count = re.subn(
    r'\s*<script>\s*\(function\s*\(\)\s*\{\s*"use strict";.*?lesedi-quick-exit.*?</script>\s*',
    '\n',
    text,
    count=1,
    flags=re.I | re.S,
)

if button_count != 1:
    raise SystemExit(f"Expected one Quick Exit button block; found {button_count}. Live file unchanged.")
if js_count != 1:
    raise SystemExit(f"Expected one dedicated Quick Exit JavaScript block; found {js_count}. Live file unchanged.")
if "lesedi-quick-exit" in text or "Quick Exit from Support and Learning" in text:
    raise SystemExit("Quick Exit identifiers remain in proposed template. Live file unchanged.")

path.write_text(text)
print("Removed the Quick Exit button, its CSS rules, and its dedicated JavaScript handler.")
PY

log "Validating the proposed template."
docker compose -p "$COMPOSE_PROJECT" exec -T web sh -lc \
  "grep -q 'Support and learning' /tmp/lesedi_support_without_quick_exit.html && grep -q 'South African support and emergency contacts' /tmp/lesedi_support_without_quick_exit.html && grep -q '{% endblock %}' /tmp/lesedi_support_without_quick_exit.html" \
  || die "Template validation failed. Live file remains unchanged."
if docker compose -p "$COMPOSE_PROJECT" exec -T web sh -lc \
  "grep -q 'lesedi-quick-exit\\|Quick Exit from Support and Learning' /tmp/lesedi_support_without_quick_exit.html"; then
  die "Quick Exit identifiers remain in proposed template. Live file remains unchanged."
fi

log "Installing the updated template."
docker compose -p "$COMPOSE_PROJECT" exec -T web sh -lc \
  "cat /tmp/lesedi_support_without_quick_exit.html > '$TARGET'"

log "Running Django system checks."
if ! docker compose -p "$COMPOSE_PROJECT" exec -T web python manage.py check; then
  printf '[WARN] Django check failed. Restoring the original template.\n' >&2
  docker compose -p "$COMPOSE_PROJECT" exec -T web sh -lc "cat > '$TARGET'" < "$BACKUP_DIR/files/${BASENAME}.before"
  die "Django check failed; original template restored."
fi

if docker compose -p "$COMPOSE_PROJECT" exec -T web sh -lc \
  "grep -q 'lesedi-quick-exit\\|Quick Exit from Support and Learning' '$TARGET'"; then
  die "Live-template verification failed. Backup retained at $BACKUP_DIR."
fi

log "Quick Exit removed from the Support & Learning page."
printf 'Updated template: %s\nBackup: %s\n' "$TARGET" "$BACKUP_DIR"
printf 'No database migration was needed. SOS/Guardian backend was not targeted.\n'
