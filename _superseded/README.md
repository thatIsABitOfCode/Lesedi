# Superseded files (kept, not deleted)

These files come from an earlier, parallel layout of LESEDI (an `apps/` package tree with its own
`config/settings/` package). The project now uses the flat layout (`accounts/`, `safety/`, `guardian/`, ...)
wired to `config/settings.py`. Nothing here is imported by the running application.

Why they were moved: a `config/settings/` package shadows `config/settings.py` in Python, so both could not
stay in place.

Worth reviewing before you delete anything:
- `apps/dashboard/content.py` contains educational text and **unverified** helpline numbers written from general
  knowledge. Do not publish those numbers until a qualified person has checked each against an official source.
- `apps/safety_circle` had extra permission codes (check-in, backup responder, location) that the flat layout
  does not have yet.
- `apps/accounts/management/commands/process_deletions.py` implemented a delayed-deletion workflow.

Safe to delete once you have taken anything you want from it.
