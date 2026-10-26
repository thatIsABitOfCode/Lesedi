# LESEDI v1.6 — Windows / VS Code

1. Open this `lesedi` folder in VS Code.
2. In PowerShell: `py -m venv .venv` then `.\.venv\Scripts\Activate.ps1`
3. Install: `python -m pip install -r requirements.txt`
4. Copy `.env.example` to `.env`. Keep it private. Default local DB is SQLite and Redis is disabled.
5. Set `DJANGO_SECRET_KEY` to a unique random value. To generate: `python -c "import secrets; print(secrets.token_urlsafe(64))"`.
6. Optionally set `GROQ_API_KEY` in `.env` to enable the AI companion.
7. Run `python manage.py migrate` then `python manage.py runserver`.
8. Open `http://127.0.0.1:8000/`. Register, then visit `/amani/`.
9. To approve a test volunteer, use Django admin and edit its ListenerProfile `trained` field. Do not approve actual volunteers without real screening.

## Important limitations

This is a development prototype, not a validated safety product. Guardian alerts are simulations; peer messages are not end-to-end encrypted. Moderation, reporting, blocking, clinical escalation, accessibility, security review, and privacy assessment need completion before real-user use. Human chat uses form submissions, not realtime messaging. AI conversations go to Groq when enabled. Never commit `.env`.
