#!/usr/bin/env bash
# LESEDI V1.6 Support & Learning centre installer.
# Backs up the matched template and PostgreSQL before replacing the known placeholder.
# Targets only the isolated lesedi-v16 Docker Compose project.

set -Eeuo pipefail
IFS=$'\n\t'
PROJECT_DIR="${HOME}/Downloads/LESEDI/LESEDI_v1.6_Redesign_Amani/lesedi"
COMPOSE_PROJECT="lesedi-v16"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${PROJECT_DIR}/backups/support_learning_${STAMP}"
PLACEHOLDER="This section is a placeholder for content that qualified people have reviewed"

log(){ printf '\n[INFO] %s\n' "$*"; }
die(){ printf '\n[ERROR] %s\n' "$*" >&2; exit 1; }
trap 'rc=$?; printf "\n[ERROR] Script stopped at line %s (exit %s).\n" "$LINENO" "$rc" >&2; exit "$rc"' ERR

[[ -d "$PROJECT_DIR" ]] || die "V1.6 project directory not found: $PROJECT_DIR"
command -v docker >/dev/null 2>&1 || die "Docker is unavailable."
docker compose version >/dev/null 2>&1 || die "Docker Compose plugin is unavailable."
cd "$PROJECT_DIR"
docker compose -p "$COMPOSE_PROJECT" ps --status running --services | grep -qx web || die "V1.6 web service is not running. Start it with docker compose -p lesedi-v16 up -d."

log "Finding the exact placeholder template inside V1.6."
MATCHES="$(docker compose -p "$COMPOSE_PROJECT" exec -T web sh -lc "grep -RIlF '$PLACEHOLDER' /app --include='*.html' 2>/dev/null || true")"
[[ -n "$MATCHES" ]] || die "Placeholder not found under /app. No files changed."
COUNT="$(printf '%s\n' "$MATCHES" | sed '/^[[:space:]]*$/d' | wc -l | tr -d ' ')"
[[ "$COUNT" == 1 ]] || { printf '%s\n' "$MATCHES"; die "Expected exactly one matching template, found $COUNT. No files changed."; }
TARGET="${MATCHES%%$'\n'*}"
[[ "$TARGET" == /app/* ]] || die "Matched file is outside /app. Refusing to edit."

BASE_LINE="$(docker compose -p "$COMPOSE_PROJECT" exec -T web sh -lc "grep -m1 -E '^[[:space:]]*\\{%[[:space:]]*extends[[:space:]]+' '$TARGET' || true")"
[[ -n "$BASE_LINE" ]] || die "Could not identify a Django base-template declaration. No source changes made."

mkdir -p "$BACKUP_DIR/files"
docker compose -p "$COMPOSE_PROJECT" exec -T web sh -lc "cat '$TARGET'" > "$BACKUP_DIR/files/$(basename "$TARGET").before"
chmod 600 "$BACKUP_DIR/files/$(basename "$TARGET").before"

log "Creating a PostgreSQL backup before changing the template."
if ! docker compose -p "$COMPOSE_PROJECT" exec -T db sh -lc 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --no-privileges' > "$BACKUP_DIR/lesedi_v16_pre_support_learning.sql"; then
  rm -f "$BACKUP_DIR/lesedi_v16_pre_support_learning.sql"
  die "Database backup failed. No source changes made."
fi
chmod 600 "$BACKUP_DIR/lesedi_v16_pre_support_learning.sql"

log "Preparing Support and Learning content."
docker compose -p "$COMPOSE_PROJECT" exec -T web sh -lc 'cat > /tmp/lesedi_support_learning_new.html' <<'HTML'
{% extends "base.html" %}
{% block content %}
<style>
.support-centre{max-width:1100px;margin:0 auto;padding:1.25rem;color:var(--text,#f4edf8)}
.support-notice{padding:1rem;border-radius:1rem;background:rgba(130,78,150,.22);margin:1rem 0}
.support-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1rem}
.support-card{border:1px solid rgba(180,150,190,.35);border-radius:1rem;padding:1rem;background:rgba(255,255,255,.025)}
.support-card h3{margin-top:0}.support-meta{font-size:.85rem;opacity:.85}
.support-checklist label{display:flex;gap:.6rem;align-items:flex-start;margin:.6rem 0}
.support-checklist input{margin-top:.35rem}
.quick-exit{position:sticky;top:.5rem;z-index:20;display:flex;justify-content:flex-end}
.quick-exit button{background:#fff;color:#222;border:0;border-radius:.5rem;padding:.6rem .8rem;font-weight:700}
.support-centre details{padding:.7rem 0;border-bottom:1px solid rgba(180,150,190,.25)}
.support-centre summary{font-weight:700;cursor:pointer}
</style>
<div class="support-centre">
  <div class="quick-exit"><button type="button" id="lesedi-quick-exit" aria-label="Quick exit from Support and Learning">Quick Exit</button></div>
  <h1>Support and learning</h1>
  <div class="support-notice" role="note"><strong>If you are in immediate danger, contact emergency services directly.</strong> LESEDI does not dispatch police, ambulance services, or other responders by itself. This page does not replace emergency services, qualified legal advice, medical care, or professional counselling. If this device may be monitored, consider whether it is safe to continue browsing.</div>
  <p>Explore information at your own pace. You do not have to report abuse to read these resources or seek support.</p>
  <div class="support-grid">
    <section class="support-card" id="recognise"><h2>1. Recognise abuse</h2><p>Abuse may be physical, sexual, emotional, financial, or digital. Coercive control can include monitoring, isolation, threats, intimidation, controlling money, or restricting access to help.</p><details><summary>Possible warning signs</summary><ul><li>You feel afraid of a person's reaction or change your behaviour to avoid it.</li><li>Someone controls your movements, money, communication, clothing, or relationships.</li><li>Someone threatens you, follows you, shares private material, or monitors your accounts or device.</li><li>Boundaries and consent are repeatedly ignored.</li></ul><p>These examples are information, not a diagnosis or a requirement to label your experience.</p></details></section>
    <section class="support-card" id="safety-planning"><h2>2. Safety planning</h2><p>A safety plan is personal. Choose only steps that are safe for your circumstances; do not complete a checklist if doing so could put you at greater risk.</p><div class="support-checklist"><label><input type="checkbox"> Identify trusted people and a safe way to contact them.</label><label><input type="checkbox"> Agree on a code word or phrase that means “I need help”.</label><label><input type="checkbox"> Consider safe places, transport, exits, and a backup destination.</label><label><input type="checkbox"> If safe, plan access to medication, documents, keys, money, and children's necessities.</label><label><input type="checkbox"> Decide what information a trusted person may receive and how they should respond.</label><label><input type="checkbox"> Consider shared accounts, location sharing, passwords, and notification previews.</label></div><p class="support-meta">Checklist selections stay in this page only; this template does not save them to the server.</p></section>
    <section class="support-card" id="leaving"><h2>3. Considering leaving</h2><p>Leaving is a personal decision and can sometimes increase risk. You are not to blame for the abuse, and you do not have to leave before seeking support.</p><details><summary>Preparation ideas, only if safe</summary><ul><li>Discuss options with a qualified support worker or trusted person, using a safer device if possible.</li><li>Consider transport, a safe destination, children or dependants, medication, and essential documents.</li><li>Avoid announcing plans if that could increase danger.</li><li>Consider whether accounts, shared devices, vehicle tracking, or location sharing may reveal plans.</li><li>If danger is immediate, prioritise safety and contact emergency services.</li></ul></details></section>
    <section class="support-card" id="speak"><h2>4. Speak and get support</h2><p>You can seek information, medical care, counselling, shelter referrals, or legal assistance without being forced to report to police. Options depend on your circumstances and provider.</p><details><summary>Before contacting a service</summary><ul><li>Choose a safe time and communication method where possible.</li><li>Ask what information they record, what confidentiality limits apply, and what choices you have.</li><li>If the first contact is not suitable, ask about another service or referral.</li></ul></details></section>
    <section class="support-card" id="heal"><h2>5. Healing and ongoing support</h2><p>Recovery can involve emotional, physical, social, financial, and legal needs. There is no single correct timeline.</p><ul><li>Consider a qualified counsellor, social worker, healthcare professional, or survivor-support organisation.</li><li>Ask about confidentiality, costs, accessibility, and language options.</li><li>Seek medical care for injuries or health concerns.</li><li>Choose supportive people who respect your choices and do not pressure you.</li></ul></section>
    <section class="support-card" id="digital-safety"><h2>6. Digital safety</h2><p>Changing settings can sometimes alert a person who monitors your device. Consider the safest approach before making changes.</p><details><summary>Options to consider</summary><ul><li>Use a device or account the other person cannot access, if available.</li><li>Review location sharing, linked devices, cloud accounts, browser history, and notification previews only if safe.</li><li>Change passwords from a safer device if doing so will not increase risk.</li><li>Avoid storing plans or evidence on a shared device if discovery could put you at risk.</li><li>If you suspect spyware or tracking, seek specialist advice before removing it.</li></ul></details></section>
  </div>
  <h2 id="verified-contacts">South African support and emergency contacts</h2>
  <p class="support-notice"><strong>Immediate emergency:</strong> Police <a href="tel:10111">10111</a>; mobile emergency number <a href="tel:112">112</a>. Call directly. LESEDI does not place these calls automatically.</p>
  <div class="support-grid">
    <section class="support-card"><h3>Gender-Based Violence Command Centre (GBVCC)</h3><p><strong>Phone:</strong> <a href="tel:0800428428">0800 428 428</a></p><p><strong>USSD / Please Call Me:</strong> *120*7867#</p><p><strong>SMS:</strong> Send “HELP” to <a href="sms:31531">31531</a> (official sources list this for people with disabilities).</p><p>GBV support and referrals. Confirm current availability and best channel when safe.</p><p class="support-meta">Sources: <a href="https://www.gov.za/about-government/government-call-centres-and-help-lines" target="_blank" rel="noopener noreferrer">South African Government contact listing</a>; <a href="https://www.dsd.gov.za/index.php/about/contact-us" target="_blank" rel="noopener noreferrer">Department of Social Development</a>; <a href="https://justice.gov.za/vg/GBV.html" target="_blank" rel="noopener noreferrer">Department of Justice GBV page</a>.</p><p class="support-meta">Source check: 25 October 2026. Human reviewer: not yet assigned. Approval required before production publication.</p></section>
    <section class="support-card"><h3>South African Police Service (SAPS)</h3><p><strong>Emergency:</strong> <a href="tel:10111">10111</a></p><p>Contact emergency services directly in immediate danger. LESEDI does not dispatch police.</p><p class="support-meta">Source: <a href="https://www.gov.za/faq/justice-and-crime-prevention/where-can-i-find-organisation-offers-assistance-victims-violence" target="_blank" rel="noopener noreferrer">South African Government guidance for victims of violence</a>.</p><p class="support-meta">Source check: 25 October 2026. Human reviewer: not yet assigned. Approval required before production publication.</p></section>
    <section class="support-card"><h3>Mobile emergency number</h3><p><strong>From a mobile phone:</strong> <a href="tel:112">112</a></p><p>State your location, what happened, and what assistance is needed if safe.</p><p class="support-meta">Source: <a href="https://www.gov.uk/foreign-travel-advice/south-africa/getting-help" target="_blank" rel="noopener noreferrer">UK Government emergency numbers for South Africa</a>.</p><p class="support-meta">Source check: 25 October 2026. Human reviewer: not yet assigned. Approval required before production publication.</p></section>
  </div>
  <h2>Review and verification record</h2><div class="support-card"><p><strong>Scope:</strong> General safety information and national contact details.</p><p><strong>Sources checked:</strong> South African Government, Department of Social Development, Department of Justice, and published emergency guidance.</p><p><strong>Source check date:</strong> 25 October 2026.</p><p><strong>Human reviewer:</strong> Not yet assigned.</p><p><strong>Publication status:</strong> Preliminary implementation. A designated reviewer must verify details, accessibility, language, and service availability before public release. Update reviewer and review date after approval.</p></div>
  <p class="support-meta">Services and contact details may change. If a number fails, use the linked official source or contact emergency services directly in an emergency. Never rely on this page as the only way to get help.</p>
</div>
<script>
(function () {
  "use strict";
  // Quick Exit navigates away. It cannot erase browser history or guarantee privacy
  // from monitoring software, device logs, or network records.
  var button = document.getElementById("lesedi-quick-exit");
  if (button) button.addEventListener("click", function () {
    try { window.location.replace("/"); }
    catch (error) { window.location.href = "/"; }
  });
})();
</script>
{% endblock %}
HTML

# Retain the original page's real Django extends line.
docker compose -p "$COMPOSE_PROJECT" exec -T web sh -lc "sed -i '1s|.*|$BASE_LINE|' /tmp/lesedi_support_learning_new.html"
docker compose -p "$COMPOSE_PROJECT" exec -T web sh -lc "grep -q 'Recognise abuse' /tmp/lesedi_support_learning_new.html && grep -q 'Review and verification record' /tmp/lesedi_support_learning_new.html && grep -q '{% endblock %}' /tmp/lesedi_support_learning_new.html" || die "Generated template validation failed. Original file unchanged."

log "Installing the new template."
docker compose -p "$COMPOSE_PROJECT" exec -T web sh -lc "cat /tmp/lesedi_support_learning_new.html > '$TARGET'"

log "Running Django system checks."
if ! docker compose -p "$COMPOSE_PROJECT" exec -T web python manage.py check; then
  printf '[WARN] Django check failed. Restoring original template.\n' >&2
  docker compose -p "$COMPOSE_PROJECT" exec -T web sh -lc "cat > '$TARGET'" < "$BACKUP_DIR/files/$(basename "$TARGET").before"
  die "Django check failed; original template restored."
fi

docker compose -p "$COMPOSE_PROJECT" exec -T web sh -lc "grep -q 'Quick Exit' '$TARGET' && grep -q 'South African support and emergency contacts' '$TARGET'" || die "Post-install verification failed. Check backup at $BACKUP_DIR."
log "Support and Learning template installed."
printf 'Template: %s\nBackup: %s\n' "$TARGET" "$BACKUP_DIR"
printf 'Reload the Support and Learning page. Assign a human reviewer and verify all details before production.\n'
