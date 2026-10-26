#!/usr/bin/env bash
# Safely prepare and launch a separate LESEDI V1.6 Docker Compose project.
# Usage: bash start-lesedi-v16.sh [/full/path/to/V1.6/project]
set -Eeuo pipefail

PROJECT_NAME="lesedi-v16"
HOST_PORT="8016"
DEFAULT_ROOT="$HOME/Downloads/LESEDI"

say() { printf '\n[LESEDI V1.6] %s\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "Docker is not installed or is not in PATH."
docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required."
docker info >/dev/null 2>&1 || die "Docker is not accessible. Check that Docker is running and your user has permission."

if [[ -n "${1:-}" ]]; then
  PROJECT_DIR="$(realpath "$1")"
else
  mapfile -t CANDIDATES < <(
    find "$DEFAULT_ROOT" -maxdepth 5 -type f \( -name docker-compose.yml -o -name compose.yml -o -name compose.yaml -o -name docker-compose.yaml \) \
      -not -path '*/.git/*' -not -path '*/node_modules/*' 2>/dev/null |
    while IFS= read -r f; do
      d="$(dirname "$f")"
      if [[ "$d" =~ [Vv]1[._-]?6 ]]; then printf '%s\n' "$d"; fi
    done | sort -u
  )
  if (( ${#CANDIDATES[@]} == 1 )); then
    PROJECT_DIR="${CANDIDATES[0]}"
  else
    say "Could not uniquely identify the V1.6 folder."
    printf 'Compose files found under %s:\n' "$DEFAULT_ROOT"
    find "$DEFAULT_ROOT" -maxdepth 5 -type f \( -name docker-compose.yml -o -name compose.yml -o -name compose.yaml -o -name docker-compose.yaml \) \
      -not -path '*/.git/*' -not -path '*/node_modules/*' 2>/dev/null || true
    printf '\nRun with the exact V1.6 directory:\n  bash %q /full/path/to/lesediV1.6\n' "$0"
    exit 2
  fi
fi

[[ -d "$PROJECT_DIR" ]] || die "Project directory does not exist: $PROJECT_DIR"
cd "$PROJECT_DIR"

COMPOSE_FILE=""
for f in compose.yaml compose.yml docker-compose.yml docker-compose.yaml; do
  if [[ -f "$f" ]]; then COMPOSE_FILE="$f"; break; fi
done
[[ -n "$COMPOSE_FILE" ]] || die "No Docker Compose file found in $PROJECT_DIR"

say "Project directory: $PROJECT_DIR"
say "Compose file: $COMPOSE_FILE"
say "Compose project: $PROJECT_NAME (isolated containers, network, and named volumes)"

if [[ ! -f .env ]]; then
  if [[ -f .env.example ]]; then
    cp .env.example .env
    chmod 600 .env
    say "Created .env from .env.example; review it before startup."
  elif [[ -f .env.sample ]]; then
    cp .env.sample .env
    chmod 600 .env
    say "Created .env from .env.sample; review it before startup."
  else
    say "No .env or example env file found; required variables may be missing."
  fi
else
  chmod 600 .env
  say "Existing .env preserved; permissions set to 600."
fi

export LESEDI_UID="$(id -u)"
export LESEDI_GID="$(id -g)"

# Change only a known localhost mapping. Save a backup before editing.
if grep -Eq '127\.0\.0\.1:(8000|8014|8016):[0-9]+' "$COMPOSE_FILE"; then
  if grep -Eq '127\.0\.0\.1:8016:' "$COMPOSE_FILE"; then
    say "Host port 8016 is already configured."
  else
    cp -n "$COMPOSE_FILE" "${COMPOSE_FILE}.pre-v16-backup"
    sed -i -E 's/127\.0\.0\.1:(8000|8014):([0-9]+)/127.0.0.1:8016:\2/g' "$COMPOSE_FILE"
    say "Configured localhost port 8016. Backup: ${COMPOSE_FILE}.pre-v16-backup"
  fi
else
  die "Could not safely identify a localhost port mapping for 8000, 8014, or 8016. Inspect $COMPOSE_FILE and configure the web service to publish 127.0.0.1:8016. No containers were started."
fi

if command -v ss >/dev/null 2>&1 && ss -ltn | awk '{print $4}' | grep -Eq '(^|:)8016$'; then
  die "Port 8016 is already in use. Free it or choose another host port before continuing."
fi

say "Validating Compose configuration..."
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" config --quiet

docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" config --format json |
python3 -c '
import json,sys
d=json.load(sys.stdin)
print("Resolved volumes:", {k:v.get("name",k) for k,v in d.get("volumes",{}).items()})
print("Resolved networks:", {k:v.get("name",k) for k,v in d.get("networks",{}).items()})
'

if [[ -f .env ]] && grep -Eiq 'CHANGE_ME|your[-_ ]?(secret|password)|^(DJANGO_SECRET_KEY|POSTGRES_PASSWORD|SECRET_KEY)=$' .env; then
  say ".env appears to contain placeholder or empty secret values."
  say "Edit .env to set unique strong secrets, then rerun this script. Build/start skipped."
  exit 3
fi

say "Building images..."
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" build --build-arg PIP_DEFAULT_TIMEOUT=180

say "Starting V1.6 services..."
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up -d

say "Service status:"
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" ps

say "Next checks:"
printf '  docker compose -p %s -f %q logs --tail=100 web db redis\n' "$PROJECT_NAME" "$COMPOSE_FILE"
printf '  docker compose -p %s -f %q exec -T web python manage.py check\n' "$PROJECT_NAME" "$COMPOSE_FILE"
printf '  docker compose -p %s -f %q exec -T web python manage.py showmigrations\n' "$PROJECT_NAME" "$COMPOSE_FILE"
printf '\nWeb URL (if the web service is configured): http://127.0.0.1:%s/\n' "$HOST_PORT"
printf 'Do not run migrations until checks and the migration plan have been reviewed.\n'
