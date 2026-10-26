from django import forms

from apps.safety_circle.models import TrustedContact

from .models import ResponderRole, SafetyPlan
from .services import PLAN_FIELDS


class SafetyPlanForm(forms.ModelForm):
    class Meta:
        model = SafetyPlan
        fields = PLAN_FIELDS
        widgets = {
            "checkin_time": forms.TimeInput(attrs={"type": "time"}),
            "review_due": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "emergency_instructions": forms.Textarea(attrs={"rows": 3}),
            "safe_destination": forms.Textarea(attrs={"rows": 2}),
            "essential_documents": forms.Textarea(attrs={"rows": 3}),
            "alternative_arrangements": forms.Textarea(attrs={"rows": 3}),
            "comms_failure_plan": forms.Textarea(attrs={"rows": 3}),
        }
        labels = {
            "checkin_method": "Agreed check-in method",
            "checkin_time": "Agreed check-in time",
            "review_due": "Review this plan by",
        }


class ResponderForm(forms.Form):
    contact = forms.ModelChoiceField(queryset=TrustedContact.objects.none(), label="Person from your Safety Circle")
    role = forms.ChoiceField(choices=ResponderRole.choices)

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["contact"].queryset = TrustedContact.objects.filter(owner=user, removed_at__isnull=True)
