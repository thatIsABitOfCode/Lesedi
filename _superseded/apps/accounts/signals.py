from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver


@receiver(user_logged_in)
def stamp_session_version(sender, request, user, **kwargs):
    """Remember which session_version this login belongs to."""
    if request is not None and hasattr(request, "session"):
        request.session["sv"] = user.session_version
