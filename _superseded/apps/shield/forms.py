from django import forms

from .models import ShieldAnswers


class ShieldAnswersForm(forms.ModelForm):
    class Meta:
        model = ShieldAnswers
        fields = ["shared_account_access", "shared_device_access", "recovery_options_reviewed"]
        widgets = {
            "shared_account_access": forms.RadioSelect,
            "shared_device_access": forms.RadioSelect,
        }
