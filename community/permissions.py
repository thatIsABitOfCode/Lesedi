from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from accounts.models import Role

MODERATOR_ROLES = {Role.MODERATOR.value, Role.ADMIN.value}


def is_moderator(user) -> bool:
    """Moderators see community submissions only. This role grants no access to anyone's plan, circle,
    evidence, location or Guardian activations."""
    return bool(user.is_authenticated and user.role in MODERATOR_ROLES)


def moderator_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not is_moderator(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper
