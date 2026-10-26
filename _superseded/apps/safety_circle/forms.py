from django import forms
from django.conf import settings

from apps.notifications.channels import NEEDS_EMAIL, NEEDS_PHONE

from .models import Permission, TrustedContact


class ContactForm(forms.ModelForm):
    class Meta:
        model = TrustedContact
        fields = ["name", "phone", "email", "preferred_channel", "fallback_channel", "simulation_behaviour"]
        labels = {
            "name": "Name",
            "preferred_channel": "Preferred way to reach them",
            "fallback_channel": "Backup way to reach them (recommended)",
            "simulation_behaviour": "Simulation behaviour (demo only)",
        }
        help_texts = {
            "phone": "Used only to contact this person if you activate Guardian Mode. Never shown to anyone else.",
            "simulation_behaviour": "Only used while notifications are simulated. It lets you rehearse failures safely.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["fallback_channel"].required = False
        if settings.NOTIFICATIONS_MODE != "simulation":
            del self.fields["simulation_behaviour"]

    def clean(self):
        cleaned = super().clean()
        for field_name in ("preferred_channel", "fallback_channel"):
            channel = cleaned.get(field_name)
            if channel in NEEDS_PHONE and not cleaned.get("phone"):
                self.add_error(field_name, "This way of reaching them needs a phone number.")
            if channel in NEEDS_EMAIL and not cleaned.get("email"):
                self.add_error(field_name, "This way of reaching them needs an email address.")
        if cleaned.get("fallback_channel") and cleaned.get("fallback_channel") == cleaned.get("preferred_channel"):
            self.add_error("fallback_channel", "Choose a different way from the preferred one, or leave this empty.")
        return cleaned


class PermissionsForm(forms.Form):
    permissions = forms.MultipleChoiceField(
        choices=Permission.choices,
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="What this person may do",
    )
