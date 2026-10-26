from django.conf import settings


class SafetyHeadersMiddleware:
    """No caching of authenticated pages (limits what a shared device keeps) and a strict CSP.

    Neither header can erase browser history or stop someone with access to the device."""

    CSP = (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
        "frame-ancestors 'none'; form-action 'self'; base-uri 'self'"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated:
            response["Cache-Control"] = "no-store, private"
        # The Django admin uses inline styles, so it is the one place the strict CSP is not applied.
        if not request.path.startswith("/" + settings.ADMIN_URL):
            response.setdefault("Content-Security-Policy", self.CSP)
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), payment=()")
        return response
