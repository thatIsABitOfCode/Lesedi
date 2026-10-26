from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from accounts.models import Role


def survivor_required(view):
    """Login required AND the account must hold the survivor role. Enforced server-side."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if request.user.role != Role.SURVIVOR:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper
