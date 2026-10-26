from django import forms

from .models import Incident


class IncidentForm(forms.ModelForm):
    class Meta:
        model = Incident
        fields = ["title", "description", "occurred_at"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
            "occurred_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }
        labels = {"occurred_at": "When it happened (approximate is fine)"}


_dt = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")


class NoteForm(forms.Form):
    title = forms.CharField(max_length=120, required=False, label="Short title (optional)")
    note_text = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), label="Note")
    event_time = forms.DateTimeField(required=False, widget=_dt, label="When it happened (blank = now)")


class UploadForm(forms.Form):
    file = forms.FileField(label="File (photo, PDF or text)")
    title = forms.CharField(max_length=120, required=False, label="Short title (optional)")
    event_time = forms.DateTimeField(required=False, widget=_dt, label="When it happened (blank = now)")


class ShareForm(forms.Form):
    recipient_label = forms.CharField(max_length=80, label="Who is this for? (a label only you will see)")
    hours = forms.IntegerField(min_value=1, max_value=24 * 14, initial=24, label="Link works for (hours)")
