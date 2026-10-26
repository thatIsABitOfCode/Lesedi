from datetime import date

from django import forms

from . import screening
from .models import Category, ContentFlag, ReportStatus, ReportUpdate, WitnessConcern


def _no_personal_details(value):
    problems = screening.screen_text(value)
    if problems:
        raise forms.ValidationError(f"Please remove {problems[0]}. This helps keep people safe.")
    return value


class ReportForm(forms.Form):
    category = forms.ChoiceField(choices=Category.choices)
    area = forms.CharField(max_length=120, label="Approximate area",
                           help_text="Suburb, town or ward only. Do not give a street address or house number.")
    incident_date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    description = forms.CharField(
        max_length=2000, widget=forms.Textarea(attrs={"rows": 5}),
        help_text="Describe what you saw or know. Do not include names, phone numbers, ID numbers, addresses or "
                  "links. Only moderators see this text; other people see a short summary a moderator writes.")

    def clean_area(self):
        return _no_personal_details(self.cleaned_data["area"])

    def clean_description(self):
        return _no_personal_details(self.cleaned_data["description"])

    def clean_incident_date(self):
        value = self.cleaned_data["incident_date"]
        if value > date.today():
            raise forms.ValidationError("The date cannot be in the future.")
        return value


class ModerationForm(forms.Form):
    status = forms.ChoiceField(choices=[(v, l) for v, l in ReportStatus.choices if v != ReportStatus.UNREVIEWED.value])
    public_summary = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Required to publish. This is the only text other people will see. Describe the kind of concern "
                  "and the general area. Never include names, contact details, addresses or anything that could "
                  "identify a person.")
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}), label="Internal note",
                           help_text="When rejecting, this reason is shown to the person who sent the report.")


class UpdateForm(forms.Form):
    kind = forms.ChoiceField(choices=ReportUpdate.Kind.choices)
    body = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={"rows": 3}), label="Public update or correction")


class CommentForm(forms.Form):
    body = forms.CharField(max_length=500, widget=forms.Textarea(attrs={"rows": 3}), label="Add a comment",
                           help_text="Be respectful. Do not share personal details or accuse anyone.")


class FlagForm(forms.Form):
    reason = forms.ChoiceField(choices=ContentFlag.Reason.choices)


class AppealForm(forms.Form):
    text = forms.CharField(max_length=1000, widget=forms.Textarea(attrs={"rows": 3}), label="Why should this be looked at again?")


class WitnessForm(forms.Form):
    about = forms.ChoiceField(choices=WitnessConcern.About.choices, label="Who are you worried about?")
    area = forms.CharField(max_length=120, required=False, label="Approximate area (optional)",
                           help_text="Suburb, town or ward only.")
    what_seen = forms.CharField(max_length=2000, widget=forms.Textarea(attrs={"rows": 5}), label="What have you noticed?")
    seems_urgent = forms.BooleanField(required=False, label="This seems urgent")


class WitnessReviewForm(forms.Form):
    status = forms.ChoiceField(choices=[(WitnessConcern.Status.REVIEWED.value, "Reviewed"),
                                        (WitnessConcern.Status.CLOSED.value, "Closed")])
    note = forms.CharField(required=False, max_length=1000)
