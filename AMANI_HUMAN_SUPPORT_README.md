# Amani human-first support (v1.5 development prototype)

Run `python manage.py migrate` after installing requirements. Groq remains optional: set GROQ_API_KEY in .env and restart.

## How matching works
A user requests a real listener first. Only volunteers with `ListenerProfile.trained=True` AND `available=True` are eligible. Requests require acceptance. A person can mark an accepted listener as primary; the same connection and message history remain accessible across visits. A voluntary 'My Story So Far' summary is private unless explicitly shared with the primary listener. AI chat is optional and never receives this summary automatically.

## Approving volunteers (demo only)
A trusted administrator can approve a trained volunteer in Django admin shell:
`python manage.py shell`
`from django.contrib.auth import get_user_model; from amani.models import ListenerProfile`
`u = get_user_model().objects.get(username='LISTENER_USERNAME')`
`p, _ = ListenerProfile.objects.get_or_create(user=u); p.trained=True; p.available=True; p.save()`

## IMPORTANT before public deployment
This is an MVP, not a production-ready survivor safety service. Peer messages are stored in the app database and are not end-to-end encrypted. Moderator dashboard, reports/blocking, age protections, volunteer vetting/training, abuse prevention, privacy retention/deletion, notification controls, response-time expectations and security review are NOT implemented. Do not onboard vulnerable real users until these are completed. No emergency dispatch is connected. No automated claim of 24/7 human availability. Messages use regular form submission, not realtime sockets.
