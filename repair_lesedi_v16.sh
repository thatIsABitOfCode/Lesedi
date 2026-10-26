#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

PROJECT="lesedi-v16"
BASE_URL="http://127.0.0.1:8016"
BACKUP_DIR=".repair-backups"
STAMP="$(date +%Y%m%d-%H%M%S)"

fail() { echo "ERROR: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

[[ -f .env && -f docker-compose.yml && -f manage.py && -f config/settings.py ]] \
  || fail "Required V1.6 files are missing."
docker compose version >/dev/null 2>&1 || fail "Docker Compose is unavailable."

# Confirm the Compose configuration includes the isolated web and database services.
docker compose -p "$PROJECT" config --quiet \
  || fail "Compose configuration is invalid."
docker compose -p "$PROJECT" config --services | grep -qx web \
  || fail "Compose project has no web service."
docker compose -p "$PROJECT" config --services | grep -qx db \
  || fail "Compose project has no db service."

# Check settings support PostgreSQL before changing anything.
grep -q 'django.db.backends.postgresql' config/settings.py \
  || fail "PostgreSQL backend not found in settings; no changes made."

# Validate required database variables without printing their values.
python3 - <<'PY' || exit 1
from pathlib import Path
v = {}
for line in Path(".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, val = line.split("=", 1)
        v[k.strip()] = val.strip().strip("'\"")
missing = [k for k in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD") if not v.get(k)]
if missing:
    raise SystemExit("Missing required .env variables: " + ", ".join(missing))
if v.get("POSTGRES_HOST", "db") != "db":
    raise SystemExit("POSTGRES_HOST must be 'db' for this isolated Compose setup.")
print("PASS: Required PostgreSQL settings exist; secrets were not displayed.")
PY

# Keep a private backup before modifying .env.
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
cp -p .env "$BACKUP_DIR/env.before-repair-$STAMP"
chmod 600 "$BACKUP_DIR/env.before-repair-$STAMP"

# Set only the database backend selector.
python3 - <<'PY'
from pathlib import Path
p = Path(".env")
lines = p.read_text().splitlines()
out, found = [], False
for line in lines:
    if line.strip().startswith("DATABASE_ENGINE="):
        out.append("DATABASE_ENGINE=postgresql")
        found = True
    else:
        out.append(line)
if not found:
    out.append("DATABASE_ENGINE=postgresql")
p.write_text("\n".join(out) + "\n")
p.chmod(0o600)
PY
pass "Configured V1.6 to use PostgreSQL; private backup saved."

# Start only the V1.6 database, then wait for health if a healthcheck exists.
docker compose -p "$PROJECT" up -d db
DB_ID="$(docker compose -p "$PROJECT" ps -q db)"
[[ -n "$DB_ID" ]] || fail "V1.6 database container was not created."
for _ in $(seq 1 90); do
  STATE="$(docker inspect -f '{{.State.Status}}' "$DB_ID")"
  HEALTH="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$DB_ID")"
  [[ "$STATE" == running ]] || fail "V1.6 database is not running."
  [[ "$HEALTH" == healthy || "$HEALTH" == none ]] && break
  [[ "$HEALTH" != unhealthy ]] || fail "V1.6 database is unhealthy."
  sleep 1
done
[[ "$HEALTH" == healthy || "$HEALTH" == none ]] || fail "Database health check timed out."

# Recreate only the V1.6 app services to load the updated environment.
docker compose -p "$PROJECT" up -d --no-deps --force-recreate web worker beat

# Verify that Django really uses PostgreSQL and can connect before migrating.
docker compose -p "$PROJECT" exec -T web python manage.py shell -c '
import sys
from django.conf import settings
from django.db import connection
print("Database backend:", settings.DATABASES["default"]["ENGINE"])
if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
    sys.exit("ERROR: Django is not using PostgreSQL; migrations aborted.")
try:
    connection.ensure_connection()
    with connection.cursor() as c:
        c.execute("SELECT 1")
        assert c.fetchone()[0] == 1
except Exception as e:
    sys.exit("ERROR: PostgreSQL connection failed: " + type(e).__name__)
print("PASS: PostgreSQL connection verified.")
' || fail "Database verification failed; migrations were not run."

# Inspect plan before applying migrations.
docker compose -p "$PROJECT" exec -T web python manage.py migrate --plan \
  || fail "Could not produce migration plan."
docker compose -p "$PROJECT" exec -T web python manage.py migrate --noinput \
  || fail "Migration failed. Review V1.6 logs before retrying."
docker compose -p "$PROJECT" exec -T web python manage.py check \
  || fail "Django system checks failed."

# Verify all migration entries are applied.
docker compose -p "$PROJECT" exec -T web python manage.py showmigrations --plan \
  > /tmp/lesedi-v16-migration-plan.txt \
  || fail "Could not verify migration state."
if grep -q '^\[ \]' /tmp/lesedi-v16-migration-plan.txt; then
  cat /tmp/lesedi-v16-migration-plan.txt
  fail "Some migrations remain unapplied."
fi
pass "All listed migrations are applied."

# Verify HTTP response without treating a redirect as a failure.
HTTP_CODE=""
for _ in $(seq 1 60); do
  HTTP_CODE="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "$BASE_URL/" 2>/dev/null || true)"
  case "$HTTP_CODE" in 200|301|302) break ;; esac
  sleep 1
done
case "$HTTP_CODE" in
  200|301|302) pass "HTTP endpoint responded with $HTTP_CODE." ;;
  *) docker compose -p "$PROJECT" logs --tail=80 web
     fail "HTTP check failed (status ${HTTP_CODE:-no response})." ;;
esac

echo
echo "SUCCESS: V1.6 database, migrations, Django checks, and HTTP check passed."
echo "URL: $BASE_URL"
echo "Backup: $BACKUP_DIR/env.before-repair-$STAMP"
echo "No containers or volumes were removed."
