#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$HOME/Downloads/LESEDI/LESEDI_v1.6_Redesign_Amani/lesedi"
COMPOSE=(docker compose -p lesedi-v16)
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="$PROJECT_DIR/backups/sos_nav_$STAMP"
TARGET_FILE=""
BACKUP_FILE=""
PATCHED=0

log(){ printf '\n[INFO] %s\n' "$*"; }
warn(){ printf '\n[WARN] %s\n' "$*" >&2; }
die(){ printf '\n[ERROR] %s\n' "$*" >&2; exit 1; }
rollback(){
  local rc=$?
  if [[ "$PATCHED" == 1 && -n "$TARGET_FILE" && -f "$BACKUP_FILE" ]]; then
    warn "A later check failed. Restoring the navigation template from backup."
    cp -a "$BACKUP_FILE" "$TARGET_FILE" || warn "Automatic restore failed; restore manually from: $BACKUP_FILE"
  fi
  exit "$rc"
}
trap rollback ERR

[[ -d "$PROJECT_DIR" ]] || die "V1.6 project directory not found: $PROJECT_DIR"
cd "$PROJECT_DIR"
command -v docker >/dev/null 2>&1 || die "Docker is not installed or not in PATH."
docker compose version >/dev/null 2>&1 || die "Docker Compose is unavailable."
[[ -f docker-compose.yml || -f compose.yml || -f compose.yaml || -f docker-compose.yaml ]] || die "No Compose file found in V1.6 project directory."

log "Confirming the isolated V1.6 web service is running."
"${COMPOSE[@]}" ps --status running --services | grep -qx 'web' || die "V1.6 web service is not running. Start it with: docker compose -p lesedi-v16 up -d"

log "Checking that the SOS route already exists before adding a navigation link."
if ! grep -q 'path("sos/", views.sos_page, name="sos")' guardian/urls.py 2>/dev/null; then
  if ! grep -q "path('sos/', views.sos_page, name='sos')" guardian/urls.py 2>/dev/null; then
    die "Expected SOS route was not found in guardian/urls.py. No files changed."
  fi
fi

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

log "Locating the main navigation template and preparing a safe, idempotent patch."
set +e
PATCH_RESULT="$(python3 - "$PROJECT_DIR" "$BACKUP_DIR" <<'PY'
from pathlib import Path
import re, shutil, sys

root = Path(sys.argv[1])
backup_dir = Path(sys.argv[2])
search_roots = [root / 'templates']
# Some projects keep app templates under the app directories.
search_roots += [p for p in (root / 'config' / 'templates', root / 'core' / 'templates') if p.exists()]
files = []
for base in search_roots:
    if base.exists():
        files.extend(p for p in base.rglob('*.html') if p.is_file() and 'backups' not in p.parts)
# Add app-local template directories if the project has no shared templates folder.
if not files:
    for base in root.iterdir():
        if base.is_dir() and base.name not in {'.git', '.venv', 'venv', 'node_modules', 'backups', 'static'}:
            files.extend(p for p in base.rglob('*.html') if p.is_file() and 'templates' in p.parts and 'backups' not in p.parts)

# Existing marker/link means this script has already been applied.
for p in files:
    try: text = p.read_text(encoding='utf-8')
    except (OSError, UnicodeError): continue
    if 'lesedi-sos-nav-link' in text or re.search(r'href=["\'](?:\{%\s*url\s+["\']guardian:sos|/guardian/sos/)', text):
        print(f'ALREADY_PRESENT\t{p}')
        sys.exit(0)

# Prefer conventional shared navigation templates.
def rank(p):
    name = p.name.lower()
    if name in {'navbar.html', 'navigation.html', 'nav.html'}: return 0
    if name in {'base.html', 'base_site.html', 'layout.html', 'main.html'}: return 1
    if 'header' in name: return 2
    if 'nav' in name: return 3
    return 4

candidates = []
for p in set(files):
    try: text = p.read_text(encoding='utf-8')
    except (OSError, UnicodeError): continue
    # Match complete nav blocks that contain links. Avoid arbitrary template edits.
    for m in re.finditer(r'<nav\b[^>]*>[\s\S]*?</nav\s*>', text, flags=re.I):
        block = m.group(0)
        if re.search(r'<a\b', block, flags=re.I):
            candidates.append((rank(p), -len(re.findall(r'<a\b', block, flags=re.I)), str(p), p, m.start(), m.end(), block))

if not candidates:
    print('NO_CANDIDATE\tNo shared <nav> block with existing links was found. No files changed.')
    sys.exit(2)
candidates.sort(key=lambda x: (x[0], x[1], x[2]))
# Require a clear best candidate; otherwise prefer the conventional file rank and link-rich nav.
best = candidates[0]
rank_value = best[0]
# If only generic candidates exist and multiple unrelated navs tie, abort rather than guessing.
if rank_value >= 4 and len(candidates) > 1 and candidates[1][0] == best[0] and candidates[1][1] == best[1]:
    print('AMBIGUOUS\tMultiple equally plausible navigation blocks found; no files changed. Inspect templates and rerun after identifying the shared navigation template.')
    sys.exit(3)
_, _, _, path, start, end, block = best

# Insert before the closing nav tag, using the existing navigation's link conventions.
closing = re.search(r'</nav\s*>$', block, flags=re.I)
if not closing:
    print('NO_CLOSING_NAV\tCould not safely identify the closing nav tag. No files changed.')
    sys.exit(4)
indent_match = re.search(r'(?m)^(\s*)<a\b', block, flags=re.I)
indent = indent_match.group(1) if indent_match else '  '
# Use a stable literal URL to avoid namespace-name assumptions; this route was verified above.
link = f'\n{indent}<a id="lesedi-sos-nav-link" class="nav-link" href="/guardian/sos/" aria-label="SOS Emergency Mode">SOS Emergency Mode</a>\n'
new_block = block[:closing.start()] + link + block[closing.start():]
text = path.read_text(encoding='utf-8')
new_text = text[:start] + new_block + text[end:]
if new_text == text:
    print('NO_CHANGE\tPatch would not change the file. No files changed.')
    sys.exit(5)
relative = path.relative_to(root)
backup = backup_dir / relative
backup.parent.mkdir(parents=True, exist_ok=True)
shutil.copy2(path, backup)
path.write_text(new_text, encoding='utf-8')
print(f'PATCHED\t{path}')
print(f'BACKUP\t{backup}')
PY
)"
PY_RC=$?
set -e
printf '%s\n' "$PATCH_RESULT"
if [[ $PY_RC -eq 0 ]]; then
  if grep -q '^ALREADY_PRESENT' <<< "$PATCH_RESULT"; then
    log "SOS navigation link is already present. No change needed."
    trap - ERR
    exit 0
  fi
  TARGET_FILE="$(awk -F '\t' '$1=="PATCHED" {print $2; exit}' <<< "$PATCH_RESULT")"
  BACKUP_FILE="$(awk -F '\t' '$1=="BACKUP" {print $2; exit}' <<< "$PATCH_RESULT")"
  [[ -n "$TARGET_FILE" && -n "$BACKUP_FILE" && -f "$BACKUP_FILE" ]] || die "Patch output did not include a valid backup path."
  PATCHED=1
else
  die "Could not safely patch navigation (status $PY_RC). No source file was changed. Review the diagnostic above."
fi

log "Running Django system checks inside the V1.6 web container."
"${COMPOSE[@]}" exec -T web python manage.py check

log "Confirming the new SOS navigation link is present."
grep -n 'lesedi-sos-nav-link' "$TARGET_FILE" || die "SOS navigation marker was not found after patch."

PATCHED=0
trap - ERR
printf '\n[SUCCESS] SOS Emergency Mode link added to the navigation ribbon.\n'
printf 'Page: http://127.0.0.1:8016/guardian/sos/\n'
printf 'Updated template: %s\n' "$TARGET_FILE"
printf 'Backup: %s\n' "$BACKUP_FILE"
printf '\nRefresh the browser (Ctrl+Shift+R) to see the link.\n'
