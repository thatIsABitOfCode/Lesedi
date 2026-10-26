from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password

from .models import User


class RegistrationForm(forms.Form):
    email = forms.EmailField(max_length=254)
    display_name = forms.CharField(
        max_length=80,
        label="Name you would like to use",
        help_text="This is shown to people you choose to trust. It does not have to be your legal name.",
    )
    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="At least 10 characters. Use a password you do not use anywhere else.",
    )
    password2 = forms.CharField(
        label="Repeat password",
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    accept_disclaimer = forms.BooleanField(
        label="I understand that LESEDI does not replace emergency services, legal advice, "
        "medical care or counselling, and that it cannot guarantee a message is received.",
        error_messages={"required": "Please confirm that you understand this before continuing."},
    )

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The two passwords do not match.")
        elif p1:
            candidate = User(email=cleaned.get("email", ""), display_name=cleaned.get("display_name", ""))
            try:
                validate_password(p1, user=candidate)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "username"}))
    error_messages = {
        "invalid_login": "We could not sign you in with those details. Please check them and try again.",
        "inactive": "We could not sign you in with those details. Please check them and try again.",
    }

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class SettingsForm(forms.ModelForm):
    language = forms.ChoiceField(
        choices=settings.SUPPORTED_LANGUAGES,
        help_text="Only English is available in this build. Your choice is saved for when translations exist.",
    )

    class Meta:
        model = User
        fields = ["display_name", "phone", "language", "low_data_mode", "neutral_notifications"]
        labels = {
            "low_data_mode": "Low-data mode (lighter pages, no automatic refresh)",
            "neutral_notifications": "Keep alerts to my contacts neutral (no names or details)",
        }
