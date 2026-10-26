# Known limitations and incomplete features

## Verification
- Never executed: Django, migrations, tests, Docker build, browser rendering. See README "Verification status".
- Dependency pins are unresolved against PyPI. Migrations are hand-written.

## Not built
MFA; journey sharing and maps (a partial `journeys/` app was added by someone else and is not wired in or reviewed);
area-based notifications for the community feed; AI assistance; real SMS, WhatsApp Business, push (FCM) and provider webhooks (signature validation, replay
protection); WebSockets; malware scanning of uploads; per-language translation files (English only) and SASL
content; reviewed Recognise / Leave / Speak / Heal content and any support directory; data-retention jobs for
evidence; a custom administrator dashboard (Django admin only; the moderation queue is built); account recovery beyond password reset.

## Built, with honest limits
- **Notifications are simulated.** "Submitted" means the simulator accepted it. It is never shown as delivered
  to a real phone, and the interface labels every simulated event.
- **Acknowledgement is not assistance.** A responder confirming the link means they saw the alert. It does
  not mean anyone is travelling, has arrived, or that emergency services were contacted. LESEDI never contacts
  police or any authority.
- **Offline devices.** If the survivor's device is off or has no connection, a new activation cannot be sent
  from it. Only an activation the server already accepted continues, and only while the server, worker and beat
  are running.
- **Quick Exit** navigates away from the page. It cannot erase browser history, OS records, network logs or
  monitoring software. A person with access to the device may still see that LESEDI was used.
- **SHIELD** reports what the user told it and what the server can see. It does not detect spyware,
  stalkerware, hidden cameras or trackers, and it does not monitor the device.
- **Evidence hash** (SHA-256) can show that a stored file changed after upload. It does not prove the file is
  authentic, that its timestamp is accurate, or that a court will accept it. The vault is not tamper-proof or
  court-certified, and an evidence pack contains no legal conclusions.
- **Encryption key loss = evidence loss.** Back up `EVIDENCE_ENCRYPTION_KEYS` separately from the data.
- **Concurrency.** Duplicate-activation protection relies on PostgreSQL locking. The related test is skipped on
  SQLite.
- **Development server and compose file** are not a production deployment.

## Community feed and Witness Mode (built, untested)
- **No "confirmed" status exists, on purpose.** LESEDI has no verification process, so nothing is ever labelled
  confirmed. Published reports are "community-submitted, reviewed for privacy, not verified".
- **Screening is best-effort.** It catches obvious phone or ID numbers, emails, links, street addresses, stand or
  erf numbers and calls to hunt someone. It cannot recognise a name, nickname, number plate or a description that
  points at one person, and it cannot judge defamation. Moderators are the real control and need training.
- **The public sees only a moderator-written summary**, never the reporter's text or name. For abuse, harassment,
  child and older-person categories the summary must be rewritten, not copied, and comments are closed.
- **Witness Mode contacts nobody.** A concern is visible to moderators and its sender only. LESEDI does not
  alert the person concerned, the police or any organisation. A moderator may add a note; nobody promises a response.
  Who handles urgent concerns, and how, is an organisational procedure that this software does not provide.
- Moderators are not vetted or trained by the software. There is no moderator two-person review and no moderator
  MFA yet. Rate limits and a pause after repeated rejections are simple counters, not abuse detection.
- Reports hold no coordinates, only a typed suburb, town or ward. A person can still type a misleading area.
- Retention default is 90 days for rejected or resolved reports and closed concerns, but the number is a
  placeholder for legal review. Published, unresolved reports have no expiry yet.
- Safeguarding for reports about children and older people (mandatory-reporting questions, escalation
  routes) needs qualified South African legal and child-protection review before any real use.

## Needs qualified review before any real use
POPIA and child-protection duties, retention periods, mandatory-reporting questions, safeguarding procedure for
reports involving children and older people, any partnership with a responder organisation, and every
support-resource entry. Do not run this with real survivors' data until these are done.
