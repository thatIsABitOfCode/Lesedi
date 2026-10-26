#!/usr/bin/env bash
# Safely repair the missing Community table in LESEDI V1.6 only.
# Does not stop/remove containers, delete volumes, or touch legacy/V1.4 instances.
set -Eeuo pipefail

PROJECT_DIR="${HOME}/Downloads/LESEDI/LESEDI_v1.6_Redesign_Amani/lesedi"
COMPOSE_PROJECT="lesedi-v16"
COMPOSE_FILE="${PROJECT_DIR}/docker-compose.yml"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${PROJECT_DIR}/backups/community_repair_${STAMP}"

log()  { printf '\n[%s] %s\n' "INFO" "$*"; }
warn() { printf '\n[%s] %s\n' "WARN" "$*" >&2; }
die()  { printf '\n[%s] ERROR: %s\n' "ERROR" "$*" >&2; exit 1; }

on_error() {
  local code=$?
  printf '\n[ERROR] Command failed at line %s (exit %s).\n' "${BASH_LINENO[0]:-unknown}" "$code" >&2
  printf '[INFO] No containers or volumes were intentionally removed. Review the output above before retrying.\n' >&2
  exit "$code"
}
trap on_error ERR

# Ensure this is the expected isolated V1.6 checkout.
[[ -d "$PROJECT_DIR" ]] || die "V1.6 project directory not found: $PROJECT_DIR"
[[ -f "$COMPOSE_FILE" ]] || die "docker-compose.yml not found in V1.6 project directory."
cd "$PROJECT_DIR"

command -v docker >/dev/null 2>&1 || die "Docker is not installed or not on PATH."
docker compose version >/dev/null 2>&1 || die "Docker Compose plugin is unavailable."
docker info >/dev/null 2>&1 || die "Docker daemon is not running or this user lacks permission. Start Docker and retry."

# Refuse to proceed if Compose configuration cannot be parsed.
docker compose -p "$COMPOSE_PROJECT" config --quiet || die "Compose configuration is invalid. Fix it before continuing."

log "Checking V1.6 service containers (no other project will be targeted)."
for service in db redis web worker beat; do
  if ! docker compose -p "$COMPOSE_PROJECT" ps --status running --services | grep -Fxq "$service"; then
    warn "Service '$service' is not running. Attempting to start only this V1.6 service."
    docker compose -p "$COMPOSE_PROJECT" up -d "$service"
  fi
done

# Wait for PostgreSQL to become ready, with a bounded retry loop.
log "Waiting for the V1.6 PostgreSQL database to become ready."
DB_READY=0
for attempt in $(seq 1 30); do
  if docker compose -p "$COMPOSE_PROJECT" exec -T db sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
    DB_READY=1
    break
  fi
  sleep 2
done
[[ "$DB_READY" -eq 1 ]] || die "PostgreSQL did not become ready within 60 seconds. Check: docker compose -p $COMPOSE_PROJECT logs --tail=100 db"

# Confirm Django can load settings and reach its database.
log "Checking Django configuration and database connectivity."
docker compose -p "$COMPOSE_PROJECT" exec -T web python manage.py check --database default
docker compose -p "$COMPOSE_PROJECT" exec -T web python manage.py shell -c 'from django.db import connection; connection.ensure_connection(); print("Database connection: OK"); print("Database vendor:", connection.vendor)'

DB_VENDOR="$(docker compose -p "$COMPOSE_PROJECT" exec -T web python manage.py shell -c 'from django.db import connection; print(connection.vendor)' | tr -d '\r' | tail -n 1)"
[[ "$DB_VENDOR" == "postgresql" ]] || die "Expected PostgreSQL for V1.6, but Django reports '$DB_VENDOR'. No migrations were applied."

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

# Save current Community migration files before generating anything.
if [[ -d community/migrations ]]; then
  cp -a community/migrations "$BACKUP_DIR/community_migrations_before" 
  log "Backed up existing Community migration files to: $BACKUP_DIR/community_migrations_before"
else
  log "No community/migrations directory exists yet; Django may create it."
fi

# Make a database backup before schema changes, when pg_dump is available.
log "Creating a database backup before any migration is applied."
if docker compose -p "$COMPOSE_PROJECT" exec -T db sh -lc 'command -v pg_dump >/dev/null 2>&1'; then
  if docker compose -p "$COMPOSE_PROJECT" exec -T db sh -lc 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$BACKUP_DIR/lesedi_v16_pre_community_repair.sql"; then
    [[ -s "$BACKUP_DIR/lesedi_v16_pre_community_repair.sql" ]] || die "Database backup file is empty. Aborting before migrations."
    chmod 600 "$BACKUP_DIR/lesedi_v16_pre_community_repair.sql"
    log "Database backup saved (permissions restricted): $BACKUP_DIR/lesedi_v16_pre_community_repair.sql"
  else
    die "Database backup failed. No migrations were applied. Check database credentials/permissions and retry."
  fi
else
  die "pg_dump is unavailable in the database container. No migrations were applied. Install/enable pg_dump or create a verified backup first."
fi

# Detect whether the expected table already exists.
TABLE_EXISTS="$(docker compose -p "$COMPOSE_PROJECT" exec -T web python manage.py shell -c 'from django.db import connection; print("yes" if "community_communityreport" in connection.introspection.table_names() else "no")' | tr -d '\r' | tail -n 1)"
if [[ "$TABLE_EXISTS" == "yes" ]]; then
  log "The community_communityreport table already exists. No schema migration is needed for this table."
else
  log "The community_communityreport table is missing. Checking Community migrations."

  # Generate a migration only if Django detects model changes.
  MAKE_OUTPUT="$(docker compose -p "$COMPOSE_PROJECT" exec -T web python manage.py makemigrations community 2>&1)" || {
    printf '%s\n' "$MAKE_OUTPUT"
    die "makemigrations community failed. No migrations were applied; inspect community/models.py, INSTALLED_APPS, and the migration package."
  }
  printf '%s\n' "$MAKE_OUTPUT"

  # Require at least one migration file after generation. Do not fabricate a table manually.
  if [[ ! -d community/migrations ]] || ! find community/migrations -maxdepth 1 -type f -name '[0-9]*.py' ! -name '__init__.py' -print -quit | grep -q .; then
    die "No numbered Community migration file exists after makemigrations. Stop here; do not create the table manually. Check that CommunityReport is a Django model and the app is installed."
  fi
fi

log "Current migration status for Community:"
docker compose -p "$COMPOSE_PROJECT" exec -T web python manage.py showmigrations community

log "Reviewing the migration plan."
PLAN_FILE="$BACKUP_DIR/migration_plan.txt"
docker compose -p "$COMPOSE_PROJECT" exec -T web python manage.py migrate --plan | tee "$PLAN_FILE"

if [[ "$TABLE_EXISTS" != "yes" ]]; then
  if ! grep -Eiq 'community[^[:cntrl:]]*|communityreport' "$PLAN_FILE"; then
    warn "The plan does not visibly mention Community. This may mean migrations are missing or the app's migration configuration differs from expectations."
    die "Migration plan did not clearly include Community. No migrations were applied; inspect $PLAN_FILE and the Community app configuration."
  fi
fi

printf '\nBackup directory: %s\n' "$BACKUP_DIR"
printf 'The script will now apply the pending Django migrations for V1.6 only.\n'
printf 'Review the migration plan above. Type APPLY to continue, or anything else to abort: '
read -r CONFIRM
[[ "$CONFIRM" == "APPLY" ]] || die "Cancelled by user. Backups are retained and no migrations were applied."

log "Applying pending migrations to the isolated V1.6 database."
docker compose -p "$COMPOSE_PROJECT" exec -T web python manage.py migrate

log "Verifying Community migration status and database table."
docker compose -p "$COMPOSE_PROJECT" exec -T web python manage.py showmigrations community
FINAL_TABLE="$(docker compose -p "$COMPOSE_PROJECT" exec -T web python manage.py shell -c 'from django.db import connection; print("yes" if "community_communityreport" in connection.introspection.table_names() else "no")' | tr -d '\r' | tail -n 1)"
[[ "$FINAL_TABLE" == "yes" ]] || die "Migrations completed, but community_communityreport still does not exist. Do not retry blindly; inspect migration output and model table names."

log "Running a final Django system check."
docker compose -p "$COMPOSE_PROJECT" exec -T web python manage.py check

log "Community table repair completed successfully."
printf 'Backup files: %s\n' "$BACKUP_DIR"
printf 'Test the page at: http://127.0.0.1:8016/community/\n'
printf 'If the page still errors, collect: docker compose -p %s logs --tail=100 web\n' "$COMPOSE_PROJECT"
