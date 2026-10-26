# LESEDI v1.2 reference-led UI redesign

- Lavender, warm cream, rose and plum visual system; lotus-mark SVG.
- New responsive splash screen with the requested support-first language.
- Four-pathway dashboard: I need help / worried about someone / information / Child Safe.
- Two-step, privacy-conscious help journey at `/help/` and `/help/options/`; links connect to **existing** resources, evidence and safety-plan screens. There is **no emergency response integration**.
- Mobile bottom navigation for authenticated personal safety users.
- Existing Django backend, evidence permissions, Guardian Mode and SHIELD untouched.
- **Not yet implemented:** Child Safe-specific content, verified referral directories, multi-select guided recommendations, real hotline integrations; these should not be represented as live capabilities.
- Screenshot-inspired design is not an exact pixel recreation; the original reference is not embedded in the application.

## Verification
Run `python manage.py check`, migrations and existing test suite in a properly configured environment. This archive is a UI redesign of a safety-sensitive **prototype**, not a security certification.
