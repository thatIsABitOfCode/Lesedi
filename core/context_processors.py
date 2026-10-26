from django.conf import settings


def lesedi(request):
    return {
        "SIMULATION_MODE": settings.LESEDI_NOTIFICATION_MODE == "simulation",
        "QUICK_EXIT_URL": settings.LESEDI_QUICK_EXIT_URL,
    }
