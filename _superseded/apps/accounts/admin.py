from django.contrib import admin

from .models import User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    """Deliberately minimal. Staff can manage account status and role but cannot
    read plans, contacts, incidents or evidence: those models are not registered
    here. Create administrators with `manage.py createsuperuser`."""

    list_display = ("email", "display_name", "role", "is_active", "is_staff", "date_joined")
    list_filter = ("role", "is_active", "is_staff")
    search_fields = ("email", "display_name")
    fields = ("email", "display_name", "role", "is_active", "is_staff", "date_joined", "last_login")
    readonly_fields = ("email", "display_name", "date_joined", "last_login")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
