# Draft policies — NOT FOR PUBLICATION

These are working drafts that describe how this build behaves. They are not legal documents. Each needs review
by a qualified South African privacy and legal professional (POPIA, child-protection and GBV-related duties)
before anything is published or relied on.

## Privacy (draft)
- Data held: account details, safety-plan content, trusted-contact details entered by the user, activation and
  notification records, audit events, evidence files (encrypted at rest) and their metadata.
- Contacts' details are visible only to the account owner. A contact sees only what the owner has permitted,
  and only after accepting an invitation.
- Roles do not grant access to private data. Administrators do not get evidence or plan contents by default.
- Audit events avoid storing passwords, tokens, evidence contents, message bodies and precise locations.
- Export and deletion are available from the Account security page. Retention periods: **to be decided by legal review**.

## Terms of use (draft)
- LESEDI is a planning and coordination aid. It does not replace emergency services, legal advice, medical
  care or counselling, and it cannot guarantee that an alert is sent, seen or acted on.
- Users must not use LESEDI to track, harass or monitor another person.

## AI transparency (draft)
No AI features exist in this build. If added: opt-in per action, minimal data, no evidence, locations, plans or
contact details sent by default, outputs reviewed by the user before saving, never used to judge guilt,
predict violence or contact authorities.

## Data security (draft)
Argon2 password hashing, CSRF protection, secure session settings, rate limiting on authentication, private
encrypted evidence storage, authorisation checks on every evidence download, audit trail. Secrets only in
environment variables. Not independently reviewed or penetration tested.

## Evidence handling (draft)
Originals are preserved as uploaded; a SHA-256 hash is recorded at upload. A hash helps detect later changes and
proves nothing about authenticity, timing or admissibility. Evidence packs state their origin and limits and
contain no legal conclusions.
