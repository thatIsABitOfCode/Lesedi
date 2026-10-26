from django.conf import settings
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path("", include("core.urls")),
    path("accounts/", include("accounts.urls")),
    path("plan/", include("safety.urls")),
    path("guardian/", include("guardian.urls")),
    path("api/guardian/", include("guardian.api_urls")),
    path("shield/", include("shield.urls")),
    path("evidence/", include("evidence.urls")),
    path("community/", include("community.urls")),
    path("amani/", include("amani.urls")),
]
