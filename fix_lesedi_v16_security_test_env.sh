#!/usr/bin/env bash
# Fixes a test-isolation issue in LESEDI V1.6 only.
# The tests subprocess must not load the project's .env, otherwise missing-secret tests
# accidentally inherit real development secrets. Does not change runtime settings or database.
set -Eeuo pipefail
umask 077
PROJECT="lesedi-v16"
ROOT="$HOME/Downloads/LESEDI/LESEDI_v1.6_Redesign_Amani/lesedi"
STAMP="$(date +%Y%m%d_%H%M%S)"
MODE="${1:-audit}"
case "$MODE" in audit|fix) ;; *) echo "Usage: $0 [audit|fix]" >&2; exit 2 ;; esac
[[ -d "$ROOT" ]] || { echo "V1.6 directory not found: $ROOT" >&2; exit 1; }
cd "$ROOT"
[[ -f tests/test_accounts_security.py ]] || { echo "Expected test file not found; no changes made." >&2; exit 1; }
mkdir -p reports backups
chmod 700 reports backups
REPORT="reports/security_test_env_${STAMP}"
BACKUP="backups/security_test_env_${STAMP}"
mkdir -p "$REPORT" "$BACKUP"
chmod 700 "$REPORT" "$BACKUP"
cp -p tests/test_accounts_security.py "$BACKUP/test_accounts_security.py.before"
sha256sum tests/test_accounts_security.py > "$BACKUP/test.sha256.before"

echo "Checking exact test helper and current test failures."
grep -n -A 10 -B 2 'def _import_settings' tests/test_accounts_security.py > "$REPORT/helper-before.txt" || true
docker compose -p "$PROJECT" exec -T web pytest -q tests/test_accounts_security.py > "$REPORT/tests-before.txt" 2>&1 || true

if [[ "$MODE" == "audit" ]]; then
  echo "Audit only; no changes made. Review $REPORT/helper-before.txt and tests-before.txt"
  exit 0
fi

python3 - <<'PY'
from pathlib import Path
p = Path("tests/test_accounts_security.py")
s = p.read_text()
old = 'clean = {"PATH": os.environ.get("PATH", ""), **env}'
new = 'clean = {"PATH": os.environ.get("PATH", ""), "PYTHON_DOTENV_DISABLED": "1", **env}'
if new in s:
    print("Patch already present; no change needed.")
elif old in s:
    p.write_text(s.replace(old, new, 1))
    print("Patched test subprocess environment to prevent .env leakage.")
else:
    raise SystemExit("Expected exact _import_settings environment line not found. No changes made.")
PY

echo "Running focused security tests."
if docker compose -p "$PROJECT" exec -T web pytest -q tests/test_accounts_security.py > "$REPORT/tests-after.txt" 2>&1; then
  echo "Focused security tests passed." | tee "$REPORT/result.txt"
else
  rc=$?
  echo "Focused tests still fail (exit $rc). Review $REPORT/tests-after.txt." | tee "$REPORT/result.txt"
  exit "$rc"
fi

echo "Running full test suite."
docker compose -p "$PROJECT" exec -T web pytest -q > "$REPORT/full-tests-after.txt" 2>&1 || {
  echo "Full suite still has failures; inspect $REPORT/full-tests-after.txt" | tee -a "$REPORT/result.txt"
}
echo "Report: $REPORT"
echo "Backup: $BACKUP"
echo "No runtime settings, database records, migrations, containers, or notification providers were changed."
