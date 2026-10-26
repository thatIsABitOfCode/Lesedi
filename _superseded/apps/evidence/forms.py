from datetime import timedelta

from django import forms
from django.utils import timezone

from apps.safety_circle.models import TrustedContact

from .models import Incident, TimelineEntry

DATETIME_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"]


def local_datetime_field(label):
    return forms.DateTimeField(
        label=label,
        input_formats=DATETIME_FORMATS,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )


def _not_in_future(value):
    if value > timezone.now() + timedelta(minutes=5):
        raise forms.ValidationError("This date and time is in the future. Please check it.")
    return value


class IncidentForm(forms.ModelForm):
    occurred_at = local_datetime_field("When did it happen?")

    class Meta:
        model = Incident
        fields = ["title", "occurred_at", "description"]
        widgets = {"description": forms.Textarea(attrs={"rows": 4})}
        labels = {"title": "Short title", "description": "What happened (optional)"}
        help_texts = {"title": "Choose words that would be safe if someone else saw this screen."}

    def clean_occurred_at(self):
        return _not_in_future(self.cleaned_data["occurred_at"])


class EntryForm(forms.ModelForm):
    occurred_at = local_datetime_field("When did this happen?")

    class Meta:
        model = TimelineEntry
        fields = ["occurred_at", "note"]
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}
        labels = {"note": "Note"}

    def clean_occurred_at(self):
        return _not_in_future(self.cleaned_data["occurred_at"])


class UploadForm(forms.Form):
    file = forms.FileField(
        label="File",
        help_text="Photos (JPG, PNG), PDFs and plain-text files are accepted. Files are encrypted when stored.",
    )
    entry = forms.ModelChoiceField(
        queryset=TimelineEntry.objects.none(),
        required=False,
        label="Attach to a timeline note (optional)",
    )

    def __init__(self, *args, incident, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["entry"].queryset = incident.entries.all()


class ShareForm(forms.Form):
    contact = forms.ModelChoiceField(queryset=TrustedContact.objects.none(), label="Share with")

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["contact"].queryset = TrustedContact.objects.filter(
            owner=user, removed_at__isnull=True, linked_user__isnull=False
        )
