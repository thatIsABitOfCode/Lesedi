#!/usr/bin/env bash
# Safely build and start the isolated LESEDI V1.6 Compose project.
# Usage:
#   bash start-lesedi-v16-reliable.sh
#   bash start-lesedi-v16-reliable.sh /full/path/to/LESEDI_v1.6_Redesign_Amani/lesedi
set -Eeuo pipefail

PROJECT_NAME="lesedi-v16"
HOST_PORT="8016"
DEFAULT_ROOT="${HOME}/Downloads/LESEDI"
MAX_BUILD_ATTEMPTS=3

say() { printf '\n[LESEDI V1.6] %s\n' "$*"; }
warn() { printf '\n[WARNING] %s\n' "$*" >&2; }
die() { printf '\n[ERROR] %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "Docker is not installed or is not in PATH."
command -v python3 >/dev/null 2>&1 || die "python3 is required."
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required."
docker info >/dev/null 2>&1 || die "Docker is not accessible. Start Docker and check your user permissions."

# Find the V1.6 project unless an explicit path was supplied.
if [[ -n "${1:-}" ]]; then
  PROJECT_DIR="$(realpath -e "$1")" || die "Cannot resolve project path: $1"
else
  [[ -d "$DEFAULT_ROOT" ]] || die "Folder not found: $DEFAULT_ROOT"
  mapfile -t CANDIDATES < <(
    find "$DEFAULT_ROOT" -maxdepth 6 -type f \
      \( -name docker-compose.yml -o -name compose.yml -o -name compose.yaml -o -name docker-compose.yaml \) \
      -not -path '*/.git/*' -not -path '*/node_modules/*' -print0 2>/dev/null |
    while IFS= read -r -d '' f; do
      d="$(dirname "$f")"
      if [[ "$d" =~ [Vv]1[._-]?6|[Rr]edesign[_-][Aa]mani ]]; then printf '%s\n' "$d"; fi
    done | sort -u
  )
  if (( ${#CANDIDATES[@]} != 1 )); then
    warn "Could not uniquely identify the V1.6 folder."
    find "$DEFAULT_ROOT" -maxdepth 6 -type f \
      \( -name docker-compose.yml -o -name compose.yml -o -name compose.yaml -o -name docker-compose.yaml \) \
      -not -path '*/.git/*' -not -path '*/node_modules/*' 2>/dev/null || true
    printf '\nRun with the exact project path:\n  bash %q "/home/%s/Downloads/LESEDI/LESEDI_v1.6_Redesign_Amani/lesedi"\n' "$0" "$USER"
    exit 2
  fi
  PROJECT_DIR="${CANDIDATES[0]}"
fi

[[ -d "$PROJECT_DIR" ]] || die "Project directory does not exist: $PROJECT_DIR"
cd "$PROJECT_DIR"

COMPOSE_FILE=""
for f in docker-compose.yml compose.yaml compose.yml docker-compose.yaml; do
  if [[ -f "$f" ]]; then COMPOSE_FILE="$f"; break; fi
done
[[ -n "$COMPOSE_FILE" ]] || die "No Compose file found in $PROJECT_DIR"
[[ -f Dockerfile ]] || die "Dockerfile not found in $PROJECT_DIR"

say "Project directory: $PROJECT_DIR"
say "Compose file: $COMPOSE_FILE"
say "All Docker Compose commands will use project name: $PROJECT_NAME"
say "This script will not stop or remove any containers, volumes, or networks."

# Keep existing env file and secrets; never print its contents.
if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp -n .env.example .env
    chmod 600 .env
    say "Created .env from .env.example. Review required values before startup."
  elif [[ -f .env.sample ]]; then
    cp -n .env.sample .env
    chmod 600 .env
    say "Created .env from .env.sample. Review required values before startup."
  else
    warn "No .env or .env.example/.env.sample found. Compose may fail if variables are required."
  fi
else
  chmod 600 .env
  say "Existing .env preserved; permissions set to 600."
fi

# Refuse obvious placeholder secrets without showing secret values.
if [[ -f .env ]] && grep -Eiq 'CHANGE_ME|change-this|replace[-_ ]?me|your[-_ ]?(secret|password)|example[-_ ]?(secret|password)' .env; then
  warn ".env appears to contain placeholder values."
  warn "Edit .env and replace placeholders with unique strong values, then rerun this script."
  exit 3
fi

export LESEDI_UID="$(id -u)"
export LESEDI_GID="$(id -g)"
export PIP_DEFAULT_TIMEOUT=300
export PIP_RETRIES=10

# Adjust only an explicit localhost mapping for the known prior ports. Back up first.
if grep -Eq '127\.0\.0\.1:(8000|8014|8016):[0-9]+' "$COMPOSE_FILE"; then
  if ! grep -Eq '127\.0\.0\.1:8016:' "$COMPOSE_FILE"; then
    BACKUP="${COMPOSE_FILE}.pre-v16-reliable-backup"
    if [[ ! -e "$BACKUP" ]]; then cp -p "$COMPOSE_FILE" "$BACKUP"; fi
    sed -i -E 's/127\.0\.0\.1:(8000|8014):([0-9]+)/127.0.0.1:8016:\2/g' "$COMPOSE_FILE"
    say "Changed the known localhost mapping to port 8016; backup: $BACKUP"
  else
    say "Localhost port 8016 is already configured."
  fi
else
  die "Could not safely identify a localhost mapping for ports 8000, 8014, or 8016. No containers were started. Inspect the Compose ports manually."
fi

# Avoid binding to a port already in use. Do not stop whatever owns it.
if command -v ss >/dev/null 2>&1 && ss -H -ltn 2>/dev/null | awk '{print $4}' | grep -Eq '(^|[.:])8016$'; then
  die "Port 8016 is already in use. Nothing was stopped. Inspect with: ss -ltnp | grep ':8016'"
fi

# Patch only the known pip-install RUN line; preserve a backup of the Dockerfile.
# This removes the unnecessary pip self-upgrade and adds a longer timeout/retries.
if grep -Eq 'RUN pip install --upgrade pip && pip install -r requirements-dev\.txt' Dockerfile; then
  [[ -e Dockerfile.pre-v16-reliable-backup ]] || cp -p Dockerfile Dockerfile.pre-v16-reliable-backup
  python3 - <<'PY'
from pathlib import Path
p = Path("Dockerfile")
s = p.read_text()
old = "RUN pip install --upgrade pip && pip install -r requirements-dev.txt"
new = "RUN python -m pip install --retries 10 --timeout 300 --index-url https://pypi.org/simple --prefer-binary -r requirements-dev.txt"
if old not in s:
    raise SystemExit("Expected pip install line changed during patch; refusing to edit Dockerfile.")
p.write_text(s.replace(old, new, 1))
PY
  say "Updated the known pip install line; backup: Dockerfile.pre-v16-reliable-backup"
elif grep -Eq 'RUN .*pip install.*requirements-dev\.txt' Dockerfile; then
  # Ensure the existing requirements-dev install command has explicit timeout/retry options.
  if ! grep -Eq 'RUN .*pip install.*--timeout[ =]300' Dockerfile; then
    [[ -e Dockerfile.pre-v16-reliable-backup ]] || cp -p Dockerfile Dockerfile.pre-v16-reliable-backup
    python3 - <<'PY'
from pathlib import Path
p = Path("Dockerfile")
lines = p.read_text().splitlines()
found = False
for i, line in enumerate(lines):
    if line.lstrip().startswith("RUN ") and "pip install" in line and "requirements-dev.txt" in line:
        # Replace the full line to avoid retaining a failing pip self-upgrade chain.
        lines[i] = "RUN python -m pip install --retries 10 --timeout 300 --index-url https://pypi.org/simple --prefer-binary -r requirements-dev.txt"
        found = True
        break
if not found:
    raise SystemExit("Could not safely identify the pip install RUN line.")
p.write_text("\n".join(lines) + "\n")
PY
    say "Updated the existing pip install line; backup: Dockerfile.pre-v16-reliable-backup"
  else
    say "Dockerfile already has a 300-second pip timeout; leaving it unchanged."
  fi
else
  warn "Could not find a recognizable pip install RUN line in Dockerfile."
  warn "Dockerfile was not changed. Inspect it before proceeding."
  exit 4
fi

say "Validating Compose configuration..."
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" config --quiet

# Print only resolved resource names, never environment values.
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" config --format json |
python3 -c '
import json,sys
d=json.load(sys.stdin)
print("Resolved volumes:", {k:v.get("name",k) for k,v in d.get("volumes",{}).items()})
print("Resolved networks:", {k:v.get("name",k) for k,v in d.get("networks",{}).items()})
'

say "Building images with retries and extended package-download timeouts."
BUILD_OK=0
for attempt in $(seq 1 "$MAX_BUILD_ATTEMPTS"); do
  say "Build attempt $attempt of $MAX_BUILD_ATTEMPTS"
  if docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" build \
      --build-arg PIP_DEFAULT_TIMEOUT=300 \
      --build-arg PIP_RETRIES=10 \
      --progress=plain; then
    BUILD_OK=1
    break
  fi
  if (( attempt < MAX_BUILD_ATTEMPTS )); then
    warn "Build attempt $attempt failed. Retrying once more after a short pause; existing services will not be stopped."
    sleep 5
  fi
done

if (( BUILD_OK == 0 )); then
  die "Build failed after $MAX_BUILD_ATTEMPTS attempts. No 'down' or container removal was run. Review the final pip/network error and rerun this script after connectivity improves."
fi

say "Starting only the isolated V1.6 project..."
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up -d

say "Service status:"
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" ps

say "Checking the web endpoint (up to 60 seconds)..."
WEB_OK=0
for _ in $(seq 1 12); do
  if curl -fsSI --max-time 5 "http://127.0.0.1:${HOST_PORT}/" >/dev/null 2>&1; then
    WEB_OK=1
    break
  fi
  sleep 5
done

if (( WEB_OK == 1 )); then
  say "HTTP endpoint responded successfully: http://127.0.0.1:${HOST_PORT}/"
else
  warn "The endpoint did not return a successful HEAD response yet. Inspect service health/logs below."
fi

say "Service status after endpoint check:"
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" ps

printf '\nUseful checks (copy/paste):\n'
printf '  cd %q\n' "$PROJECT_DIR"
printf '  docker compose -p %s -f %q logs --tail=100 web worker beat db redis\n' "$PROJECT_NAME" "$COMPOSE_FILE"
printf '  docker compose -p %s -f %q exec -T web python manage.py check\n' "$PROJECT_NAME" "$COMPOSE_FILE"
printf '  docker compose -p %s -f %q exec -T web python manage.py showmigrations\n' "$PROJECT_NAME" "$COMPOSE_FILE"
printf '\nMigrations have NOT been run automatically. Review checks and migration plan first.\n'
