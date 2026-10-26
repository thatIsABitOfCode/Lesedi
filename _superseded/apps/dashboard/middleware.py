from django.conf import settings
from django.utils.cache import patch_cache_control

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; "
    "form-action 'self'; frame-ancestors 'none'"
)


class SecurityHeadersMiddleware:
    """Adds conservative response headers.

    * A strict Content-Security-Policy (no inline scripts or styles anywhere in
      the templates). The Django admin is excluded because it uses some inline
      styles.
    * Nothing signed-in is cached by the browser or shared caches.
    * No referrer is sent, so a link from LESEDI never reveals LESEDI URLs.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=(), payment=()")
        if not request.path.startswith("/" + settings.ADMIN_URL):
            response.headers.setdefault("Content-Security-Policy", CSP)
        user = getattr(request, "user", None)
        if request.method == "POST" or (user is not None and user.is_authenticated):
            patch_cache_control(response, private=True, no_store=True)
        return response
