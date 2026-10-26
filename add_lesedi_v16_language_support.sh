#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

# LESEDI V1.6 only. Adds Django language-selection infrastructure and a selector.
# Full UI translations still require translated catalogues and gettext-marked strings.
# Does not run migrations or modify the database.

PROJECT_DIR="${HOME}/Downloads/LESEDI/LESEDI_v1.6_Redesign_Amani/lesedi"
COMPOSE_PROJECT="lesedi-v16"
SERVICE="web"

log() { printf '[%s] %s\n' "$1" "$2"; }
die() { log ERROR "$1" >&2; exit 1; }

[[ -d "$PROJECT_DIR" ]] || die "V1.6 project directory not found: $PROJECT_DIR"
command -v docker >/dev/null 2>&1 || die "Docker not found."
docker compose version >/dev/null 2>&1 || die "Docker Compose plugin unavailable."
cd "$PROJECT_DIR"
docker compose -p "$COMPOSE_PROJECT" ps --status running --services | grep -Fxq "$SERVICE" \
  || die "V1.6 web service is not running. No changes made."

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="$PROJECT_DIR/backups/language_support_$STAMP"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

log INFO "Detecting Django settings, URLconf, and base template."
docker compose -p "$COMPOSE_PROJECT" exec -T "$SERVICE" python - <<'PY' > "$BACKUP_DIR/paths.env"
from pathlib import Path
root = Path("/app")
settings = next((p for p in (root/"config/settings.py", root/"lesedi/settings.py", root/"settings.py") if p.is_file()), None)
urls = next((p for p in (root/"config/urls.py", root/"lesedi/urls.py", root/"urls.py") if p.is_file()), None)
base = next((p for p in (root/"templates/base.html", root/"templates/core/base.html") if p.is_file()), None)
if not settings or not urls:
    raise SystemExit("Could not identify Django settings.py and urls.py under /app; refusing to guess.")
print(f"SETTINGS={settings}")
print(f"URLCONF={urls}")
print(f"BASE_TEMPLATE={base or ''}")
PY

while IFS='=' read -r key value; do
  case "$key" in
    SETTINGS|URLCONF|BASE_TEMPLATE)
      [[ -n "$value" ]] || continue
      rel="${value#/app/}"
      mkdir -p "$BACKUP_DIR/$(dirname "$rel")"
      docker compose -p "$COMPOSE_PROJECT" exec -T "$SERVICE" sh -lc "cat '$value'" > "$BACKUP_DIR/$rel.before"
      [[ -s "$BACKUP_DIR/$rel.before" ]] || die "Could not back up $value; no changes made."
      chmod 600 "$BACKUP_DIR/$rel.before"
      ;;
  esac
done < "$BACKUP_DIR/paths.env"

log INFO "Installing language selector and Django language handling."
docker compose -p "$COMPOSE_PROJECT" exec -T "$SERVICE" python - <<'PY'
from pathlib import Path
import ast, os, re, shutil, uuid

root = Path("/app")
settings_path = next((p for p in (root/"config/settings.py", root/"lesedi/settings.py", root/"settings.py") if p.is_file()), None)
urls_path = next((p for p in (root/"config/urls.py", root/"lesedi/urls.py", root/"urls.py") if p.is_file()), None)
base_path = next((p for p in (root/"templates/base.html", root/"templates/core/base.html") if p.is_file()), None)
if not settings_path or not urls_path:
    raise SystemExit("Django settings/URLconf not found; no changes made.")

settings = settings_path.read_text()
urls = urls_path.read_text()
base = base_path.read_text() if base_path else None
if not re.search(r"(?m)^INSTALLED_APPS\s*=\s*\[", settings):
    raise SystemExit("INSTALLED_APPS is not a simple list; no changes made.")
if not re.search(r"(?m)^MIDDLEWARE\s*=\s*\[", settings):
    raise SystemExit("MIDDLEWARE is not a simple list; no changes made.")
if "urlpatterns" not in urls:
    raise SystemExit("urlpatterns not found; no changes made.")
if base is None:
    raise SystemExit("No known base.html template found. Settings and URL files were not modified.")
if base.count("</nav>") != 1 and base.count("{% block content %}") != 1:
    raise SystemExit("Base template has no unique safe selector insertion point. No changes made.")

language_lines = [
    "    ('en', 'English'),",
    "    ('af', 'Afrikaans'),",
    "    ('zu', 'isiZulu'),",
    "    ('xh', 'isiXhosa'),",
    "    ('nso', 'Sepedi'),",
    "    ('tn', 'Setswana'),",
    "    ('st', 'Sesotho'),",
    "    ('ts', 'itsonga'),",
    "    ('ss', 'siSwati'),",
    "    ('ve', 'Tshivenda'),",
    "    ('nr', 'isiNdebele'),",
    "    ('sfs', 'South African Sign Language (SASL)'),",
]
languages_assignment = "LANGUAGES = [\n" + "\n".join(language_lines) + "\n]"

settings_new = settings
if not re.search(r"(?m)^LANGUAGE_CODE\s*=", settings_new):
    settings_new += "\nLANGUAGE_CODE = 'en'\n"
else:
    settings_new = re.sub(r"(?m)^LANGUAGE_CODE\s*=.*$", "LANGUAGE_CODE = 'en'", settings_new, count=1)

lang_match = re.search(r"(?ms)^LANGUAGES\s*=\s*\[.*?^\]", settings_new)
if lang_match:
    settings_new = settings_new[:lang_match.start()] + languages_assignment + settings_new[lang_match.end():]
else:
    settings_new += "\n\n" + languages_assignment + "\n"

apps_match = re.search(r"(?ms)^INSTALLED_APPS\s*=\s*\[(.*?)^\]", settings_new)
if not apps_match:
    raise SystemExit("Could not parse INSTALLED_APPS safely.")
if "language_support" not in apps_match.group(1):
    settings_new = settings_new[:apps_match.end()-1] + "    'language_support',\n" + settings_new[apps_match.end()-1:]

mw_match = re.search(r"(?ms)^MIDDLEWARE\s*=\s*\[(.*?)^\]", settings_new)
if not mw_match:
    raise SystemExit("Could not parse MIDDLEWARE safely.")
mw_block = mw_match.group(0)
if "django.middleware.locale.LocaleMiddleware" not in mw_block:
    session_pos = mw_block.find("django.contrib.sessions.middleware.SessionMiddleware")
    common_pos = mw_block.find("django.middleware.common.CommonMiddleware")
    if session_pos < 0 or common_pos < 0 or session_pos > common_pos:
        raise SystemExit("Cannot safely place LocaleMiddleware between SessionMiddleware and CommonMiddleware.")
    insert_at = mw_block.find("\n", session_pos) + 1
    mw_block = mw_block[:insert_at] + "    'django.middleware.locale.LocaleMiddleware',\n" + mw_block[insert_at:]
    settings_new = settings_new[:mw_match.start()] + mw_block + settings_new[mw_match.end():]

if "language_support.context_processors.language_options" not in settings_new:
    request_cp = re.search(r"(?m)^(\s*)'django\.template\.context_processors\.request',\s*$", settings_new)
    if not request_cp:
        raise SystemExit("Could not find the request context processor; no settings changes made.")
    indent = request_cp.group(1)
    settings_new = settings_new[:request_cp.end()] + "\n" + indent + "'language_support.context_processors.language_options'," + settings_new[request_cp.end():]

app_dir = root / "language_support"
app_dir.mkdir(exist_ok=True)
(app_dir / "__init__.py").touch(exist_ok=True)
(app_dir / "apps.py").write_text(
    "from django.apps import AppConfig\n\n"
    "class LanguageSupportConfig(AppConfig):\n"
    "    default_auto_field = 'django.db.models.BigAutoField'\n"
    "    name = 'language_support'\n"
)
(app_dir / "context_processors.py").write_text(
    "from django.conf import settings\n\n"
    "def language_options(request):\n"
    "    return {'lesedi_languages': settings.LANGUAGES,\n"
    "            'lesedi_current_language': getattr(request, 'LANGUAGE_CODE', settings.LANGUAGE_CODE)}\n"
)
(app_dir / "views.py").write_text(
    "from django.conf import settings\n"
    "from django.http import HttpResponseBadRequest\n"
    "from django.shortcuts import redirect\n"
    "from django.utils.translation import check_for_language, activate\n"
    "from django.utils.http import url_has_allowed_host_and_scheme\n"
    "from django.views.decorators.http import require_POST\n\n"
    "@require_POST\n"
    "def set_language(request):\n"
    "    language = request.POST.get('language', '')\n"
    "    supported = {code for code, _label in settings.LANGUAGES}\n"
    "    if language not in supported or not check_for_language(language):\n"
    "        return HttpResponseBadRequest('Unsupported language selection.')\n"
    "    activate(language)\n"
    "    request.session[settings.LANGUAGE_COOKIE_NAME] = language\n"
    "    next_url = request.POST.get('next') or request.META.get('HTTP_REFERER') or '/'\n"
    "    if not url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):\n"
    "        next_url = '/'\n"
    "    response = redirect(next_url)\n"
    "    response.set_cookie(settings.LANGUAGE_COOKIE_NAME, language, max_age=31536000,\n"
    "                        secure=request.is_secure(), httponly=False, samesite='Lax')\n"
    "    return response\n"
)

urls_new = urls
if "language_support.views" not in urls_new:
    import_match = re.search(r"(?m)^from django\.urls import ([^\n]+)$", urls_new)
    if import_match:
        imports = [x.strip() for x in import_match.group(1).split(",")]
        if "path" not in imports:
            urls_new = urls_new[:import_match.start(1)] + import_match.group(1) + ", path" + urls_new[import_match.end(1):]
    else:
        urls_new = "from django.urls import path\n" + urls_new
    urls_new = "from language_support.views import set_language\n" + urls_new
    match = re.search(r"(?m)^urlpatterns\s*=\s*\[", urls_new)
    if not match:
        raise SystemExit("Could not safely add language URL.")
    urls_new = urls_new[:match.end()] + "\n    path('language/set/', set_language, name='set_language')," + urls_new[match.end():]

selector = """
<form method="post" action="{% url 'set_language' %}" class="lesedi-language-selector" style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;margin:.5rem 0;">
  {% csrf_token %}
  <label for="lesedi-language-select">Language / Ulimi / Tšhomišo ya polelo:</label>
  <select id="lesedi-language-select" name="language" aria-label="Choose language">
    {% for code, label in lesedi_languages %}
      <option value="{{ code }}" {% if code == lesedi_current_language %}selected{% endif %}>{{ label }}</option>
    {% endfor %}
  </select>
  <input type="hidden" name="next" value="{{ request.get_full_path }}">
  <button type="submit">Apply</button>
</form>
""".strip()

base_new = base
if "lesedi-language-selector" not in base_new:
    if base_new.count("</nav>") == 1:
        base_new = base_new.replace("</nav>", "</nav>\n" + selector, 1)
    else:
        base_new = base_new.replace("{% block content %}", selector + "\n\n{% block content %}", 1)

ast.parse(settings_new); compile(settings_new, str(settings_path), "exec")
ast.parse(urls_new); compile(urls_new, str(urls_path), "exec")

backup_dir = root / "backups" / "language_support_script"
backup_dir.mkdir(parents=True, exist_ok=True)
shutil.copy2(settings_path, backup_dir / (settings_path.name + ".before"))
shutil.copy2(urls_path, backup_dir / (urls_path.name + ".before"))
shutil.copy2(base_path, backup_dir / (base_path.name + ".before"))

def atomic_write(path, content):
    temp = path.with_name("." + path.name + ".lesedi-language-" + uuid.uuid4().hex + ".tmp")
    try:
        temp.write_text(content)
        os.chmod(temp, path.stat().st_mode)
        if path.suffix == ".py":
            compile(temp.read_text(), str(path), "exec")
        os.replace(temp, path)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass

atomic_write(settings_path, settings_new)
atomic_write(urls_path, urls_new)
atomic_write(base_path, base_new)
print(f"Updated {settings_path}")
print(f"Updated {urls_path}")
print(f"Updated {base_path}")
print("Created /app/language_support app.")
PY

log INFO "Running Django system checks."
if ! docker compose -p "$COMPOSE_PROJECT" exec -T "$SERVICE" python manage.py check; then
  log ERROR "Django checks failed. Restoring source/config files from host backups."
  while IFS='=' read -r key value; do
    case "$key" in
      SETTINGS|URLCONF|BASE_TEMPLATE)
        [[ -n "$value" ]] || continue
        rel="${value#/app/}"
        backup="$BACKUP_DIR/$rel.before"
        [[ -f "$backup" ]] || continue
        docker compose -p "$COMPOSE_PROJECT" exec -T "$SERVICE" sh -lc "cat > '$value'" < "$backup"
        ;;
    esac
  done < "$BACKUP_DIR/paths.env"
  die "Repair rolled back. Backup retained at $BACKUP_DIR. No database changes were made."
fi

log INFO "Django checks passed."
printf 'Backup directory: %s\n' "$BACKUP_DIR"
printf 'Database schema: unchanged; no migrations run.\n'
printf 'Legacy/V1.4: not targeted.\n'
printf 'Important: full UI translation requires translated Django .po catalogues and marking user-facing strings with gettext. SASL needs visual/video content; text catalogues cannot translate sign language.\n'
