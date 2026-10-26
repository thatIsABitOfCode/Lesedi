from django.conf import settings


def lesedi(request):
    """Template context available on every page."""
    user = getattr(request, "user", None)
    signed_in = bool(user is not None and user.is_authenticated)
    return {
        "simulation_mode": settings.NOTIFICATIONS_MODE == "simulation",
        "quick_exit_url": settings.QUICK_EXIT_URL,
        "low_data": bool(signed_in and user.low_data_mode),
        "policy_version": settings.POLICY_DRAFT_VERSION,
    }
