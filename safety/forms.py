from django import forms

from notifications.channels import Channel

from .models import Permission, SafetyPlan, TrustedContact


class PlanForm(forms.ModelForm):
    class Meta:
        model = SafetyPlan
        fields = [
            "title", "emergency_instructions", "safe_destination", "transport_notes", "transport_confirmed",
            "essential_documents", "checkin_method", "checkin_time", "ack_timeout_seconds",
            "comms_failure_contingency", "review_date",
        ]
        widgets = {
            "emergency_instructions": forms.Textarea(attrs={"rows": 3}),
            "safe_destination": forms.Textarea(attrs={"rows": 2}),
            "transport_notes": forms.Textarea(attrs={"rows": 2}),
            "essential_documents": forms.Textarea(attrs={"rows": 2}),
            "comms_failure_contingency": forms.Textarea(attrs={"rows": 2}),
            "checkin_time": forms.TimeInput(attrs={"type": "time"}),
            "review_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }


class ContactForm(forms.ModelForm):
    class Meta:
        model = TrustedContact
        fields = ["name", "relationship", "phone", "email", "preferred_channel"]

    def clean(self):
        data = super().clean()
        phone, email, channel = data.get("phone"), data.get("email"), data.get("preferred_channel")
        if not phone and not email:
            raise forms.ValidationError("Please give a phone number or an email address.")
        if channel in (Channel.SMS, Channel.WHATSAPP) and not phone:
            self.add_error("phone", "A phone number is needed for SMS or WhatsApp.")
        if channel == Channel.EMAIL and not email:
            self.add_error("email", "An email address is needed for email.")
        return data


class PermissionsForm(forms.Form):
    permissions = forms.MultipleChoiceField(
        choices=Permission.choices, required=False, widget=forms.CheckboxSelectMultiple, label="This person may")


class AssignResponderForm(forms.Form):
    rank = forms.TypedChoiceField(
        choices=[(1, "Primary responder"), (2, "First backup"), (3, "Second backup")], coerce=int, label="Position")
    grant_alert_permissions = forms.BooleanField(
        required=False, initial=True,
        label="Also allow this person to receive and acknowledge my alerts")
