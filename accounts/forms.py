from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.forms import AuthenticationForm

from .models import User


class RegisterForm(forms.Form):
    email = forms.EmailField(max_length=254)
    display_name = forms.CharField(max_length=80, label="Name (a nickname is fine)")
    password1 = forms.CharField(widget=forms.PasswordInput, label="Password", strip=False)
    password2 = forms.CharField(widget=forms.PasswordInput, label="Repeat password", strip=False)

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()

    def clean(self):
        data = super().clean()
        p1, p2 = data.get("password1"), data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The two passwords do not match.")
        if p1:
            probe = User(email=data.get("email", ""), display_name=data.get("display_name", ""))
            try:
                password_validation.validate_password(p1, probe)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return data


class EmailLoginForm(AuthenticationForm):
    username = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autofocus": True, "autocomplete": "username"}))
    error_messages = {
        "invalid_login": "That email and password did not match. Please try again.",
        "inactive": "That email and password did not match. Please try again.",
    }

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["display_name", "phone", "preferred_language"]
        labels = {"phone": "Phone (optional)", "preferred_language": "Language code (e.g. en, zu, xh, af)"}


class DeleteAccountForm(forms.Form):
    password = forms.CharField(widget=forms.PasswordInput, strip=False, label="Confirm with your password")
    confirm = forms.BooleanField(label="I understand this permanently deletes my plan, contacts, incidents and evidence.")
