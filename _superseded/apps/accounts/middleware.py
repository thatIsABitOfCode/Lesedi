from django.contrib.auth import logout


class SessionVersionMiddleware:
    """End sessions that were created before the user's last 'sign out everywhere'."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            if request.session.get("sv") != user.session_version:
                logout(request)
        return self.get_response(request)
