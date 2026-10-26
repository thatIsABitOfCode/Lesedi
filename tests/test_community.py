"""Community feed, moderation and Witness Mode. Everyone here is fictional.

These tests have been written but NOT run by the author (no Django in the authoring workspace). Run them with
`docker compose run --rm web pytest tests/test_community.py` and report failures."""
import json
from datetime import date, timedelta

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent
from community import services
from community.models import CommunityReport, ContentFlag, ReportStatus, WitnessConcern
from notifications.models import NotificationDelivery
from tests.factories import make_user

pytestmark = pytest.mark.django_db

DESC = "SECRET-DETAIL-XYZ a group keeps shouting at people near the taxi rank at night"
SUMMARY = "Concern about people being harassed near a transport hub in the evening."


def person(name, role="survivor"):
    return make_user(email=f"{name.lower()}@example.test", name=name, role=role)


def client_for(user):
    c = Client()
    c.force_login(user)
    return c


def make_report(author, category="unsafe_area", area="Fictional Ward", description=DESC):
    return services.submit_report(author, category=category, area=area, incident_date=date.today(),
                                  description=description)


def publish(report, moderator, summary=SUMMARY):
    services.transition(report, "under_review", moderator)
    return services.transition(report, "published", moderator, public_summary=summary)


# --- privacy of what reporters write ------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Please call him on 082 123 4567 about this",
    "his email is someone@example.test",
    "he lives at 12 Main Street near the shop",
    "see https://something.test/page",
    "the house is at erf 1234",
    "let's all hunt him down tonight",
])
def test_obvious_personal_details_are_refused(text):
    naledi = person("Naledi")
    response = client_for(naledi).post(reverse("community:report_new"), {
        "category": "unsafe_area", "area": "Fictional Ward", "incident_date": date.today().isoformat(),
        "description": text})
    assert response.status_code == 200  # form shown again with an error
    assert CommunityReport.objects.count() == 0
    assert text not in response.content.decode().split("<form")[0]  # never echoed back as a message


def test_area_cannot_be_a_street_address():
    naledi = person("Naledi")
    response = client_for(naledi).post(reverse("community:report_new"), {
        "category": "unsafe_area", "area": "14 Long Road", "incident_date": date.today().isoformat(),
        "description": "Poor lighting"})
    assert response.status_code == 200 and CommunityReport.objects.count() == 0


def test_future_incident_date_is_refused():
    naledi = person("Naledi")
    response = client_for(naledi).post(reverse("community:report_new"), {
        "category": "unsafe_area", "area": "Fictional Ward",
        "incident_date": (date.today() + timedelta(days=3)).isoformat(), "description": "Poor lighting"})
    assert response.status_code == 200 and CommunityReport.objects.count() == 0


# --- visibility -----------------------------------------------------------------------------------------------

def test_report_is_private_until_a_moderator_publishes_a_summary():
    naledi, faith, mona = person("Naledi"), person("Faith"), person("Mona", "moderator")
    report = make_report(naledi)
    assert report.status == ReportStatus.UNREVIEWED

    assert client_for(faith).get(reverse("community:report", args=[report.pk])).status_code == 404
    assert "SECRET-DETAIL-XYZ" not in client_for(faith).get(reverse("community:feed")).content.decode()
    assert "SECRET-DETAIL-XYZ" in client_for(naledi).get(reverse("community:report", args=[report.pk])).content.decode()

    publish(report, mona)
    feed = client_for(faith).get(reverse("community:feed")).content.decode()
    assert SUMMARY in feed
    assert "SECRET-DETAIL-XYZ" not in feed  # the raw text is never public
    detail = client_for(faith).get(reverse("community:report", args=[report.pk])).content.decode()
    assert SUMMARY in detail and "SECRET-DETAIL-XYZ" not in detail
    assert "has not verified" in detail


def test_feed_requires_login():
    response = Client().get(reverse("community:feed"))
    assert response.status_code == 302 and "/accounts/login/" in response["Location"]


def test_public_pages_never_show_who_reported():
    naledi, faith, mona = person("Naledi"), person("Faith"), person("Mona", "moderator")
    report = publish(make_report(naledi), mona)
    page = client_for(faith).get(reverse("community:report", args=[report.pk])).content.decode()
    assert "naledi@example.test" not in page and "Naledi" not in page.split("<main")[1]


def test_moderator_page_does_not_reveal_reporter_identity():
    naledi, mona = person("Naledi"), person("Mona", "moderator")
    report = make_report(naledi)
    page = client_for(mona).get(reverse("community:mod_report", args=[report.pk])).content.decode()
    assert "naledi@example.test" not in page and "Naledi" not in page.split("<main")[1]


def test_community_models_link_to_no_private_safety_data():
    labels = {f.related_model._meta.label for f in CommunityReport._meta.get_fields()
              if f.is_relation and f.related_model}
    labels |= {f.related_model._meta.label for f in WitnessConcern._meta.get_fields()
               if f.is_relation and f.related_model}
    for label in labels:
        assert not label.startswith(("guardian.", "evidence.", "safety.", "shield.", "notifications.")), label


# --- moderation rules ------------------------------------------------------------------------------------------

def test_only_moderators_can_change_status():
    naledi, faith = person("Naledi"), person("Faith")
    report = make_report(naledi)
    with pytest.raises(services.CommunityError):
        services.transition(report, "under_review", faith)
    with pytest.raises(services.CommunityError):
        services.transition(report, "under_review", naledi)


def test_invalid_transitions_are_refused():
    naledi, mona = person("Naledi"), person("Mona", "moderator")
    report = make_report(naledi)
    with pytest.raises(services.CommunityError):
        services.transition(report, "published", mona, public_summary=SUMMARY)  # must be under review first
    publish(report, mona)
    services.transition(report, "resolved", mona)
    for target in ("under_review", "published", "rejected"):
        with pytest.raises(services.CommunityError):
            services.transition(report, target, mona, note="x", public_summary=SUMMARY)


def test_publishing_needs_a_clean_summary():
    naledi, mona = person("Naledi"), person("Mona", "moderator")
    report = make_report(naledi)
    services.transition(report, "under_review", mona)
    with pytest.raises(services.CommunityError):
        services.transition(report, "published", mona, public_summary="")
    with pytest.raises(services.CommunityError):
        services.transition(report, "published", mona, public_summary="Contact someone@example.test for more")
    report.refresh_from_db()
    assert report.status == ReportStatus.UNDER_REVIEW and report.published_at is None


def test_sensitive_report_summary_must_be_rewritten_not_copied():
    naledi, mona = person("Naledi"), person("Mona", "moderator")
    report = make_report(naledi, category="child_concern", description="A child seems frightened at the shop")
    services.transition(report, "under_review", mona)
    with pytest.raises(services.CommunityError):
        services.transition(report, "published", mona, public_summary="A child seems frightened at the shop")
    services.transition(report, "published", mona, public_summary="A concern for a child's wellbeing in the area.")


def test_moderator_cannot_moderate_their_own_report():
    mona = person("Mona", "moderator")
    report = make_report(mona)
    with pytest.raises(services.CommunityError):
        services.transition(report, "under_review", mona)


def test_rejection_needs_a_reason_the_reporter_can_see_and_can_be_appealed_once():
    naledi, faith, mona = person("Naledi"), person("Faith"), person("Mona", "moderator")
    report = make_report(naledi)
    with pytest.raises(services.CommunityError):
        services.transition(report, "rejected", mona, note="")
    services.transition(report, "rejected", mona, note="Not enough detail to review")
    report.refresh_from_db()
    assert report.purge_after is not None
    page = client_for(naledi).get(reverse("community:report", args=[report.pk])).content.decode()
    assert "Not enough detail to review" in page

    assert client_for(faith).post(reverse("community:appeal", args=[report.pk]), {"text": "x"}).status_code == 404
    client_for(naledi).post(reverse("community:appeal", args=[report.pk]), {"text": "I can add more detail"})
    report.refresh_from_db()
    assert report.appealed_at is not None
    with pytest.raises(services.CommunityError):
        services.appeal(report, naledi, "again")
    needs_action, _ = services.moderation_queue()
    assert report in list(needs_action)
    services.transition(report, "under_review", mona)  # an appeal can be accepted for re-examination


def test_corrections_are_shown_on_the_public_report():
    naledi, faith, mona = person("Naledi"), person("Faith"), person("Mona", "moderator")
    report = publish(make_report(naledi), mona)
    services.add_update(report, mona, "The area was earlier described too widely.", "correction")
    page = client_for(faith).get(reverse("community:report", args=[report.pk])).content.decode()
    assert "too widely" in page and "Correction" in page


def test_updates_are_screened_and_only_for_published_reports():
    naledi, mona = person("Naledi"), person("Mona", "moderator")
    report = make_report(naledi)
    with pytest.raises(services.CommunityError):
        services.add_update(report, mona, "Fine text", "update")
    report = publish(report, mona)
    with pytest.raises(services.CommunityError):
        services.add_update(report, mona, "Call 082 123 4567", "update")


def test_moderator_actions_through_the_real_pages():
    naledi, mona = person("Naledi"), person("Mona", "moderator")
    report = make_report(naledi)
    mod = client_for(mona)
    url = reverse("community:mod_report", args=[report.pk])
    assert mod.post(url, {"do": "status", "status": "under_review"}).status_code == 302
    assert mod.post(url, {"do": "status", "status": "published", "public_summary": SUMMARY}).status_code == 302
    report.refresh_from_db()
    assert report.status == ReportStatus.PUBLISHED and report.reviewed_by == mona
    assert report.moderation_actions.count() == 2


def test_moderation_pages_are_for_moderators_only():
    naledi, mona = person("Naledi"), person("Mona", "moderator")
    report = make_report(naledi)
    for name, args in (("community:mod_queue", []), ("community:mod_witness", []), ("community:mod_report", [report.pk])):
        assert Client().get(reverse(name, args=args)).status_code == 302  # to login
        assert client_for(naledi).get(reverse(name, args=args)).status_code == 403
        assert client_for(mona).get(reverse(name, args=args)).status_code == 200
    # posting to the moderation page as a survivor changes nothing
    client_for(naledi).post(reverse("community:mod_report", args=[report.pk]), {"do": "status", "status": "published",
                                                                              "public_summary": SUMMARY})
    report.refresh_from_db()
    assert report.status == ReportStatus.UNREVIEWED


def test_a_moderator_role_gives_no_access_to_a_survivors_private_pages():
    mona = person("Mona", "moderator")
    for name in ("safety:plan", "safety:circle"):
        assert client_for(mona).get(reverse(name)).status_code == 403


# --- comments, flags, limits ----------------------------------------------------------------------------------

def test_comments_only_on_published_non_sensitive_reports():
    naledi, faith, mona = person("Naledi"), person("Faith"), person("Mona", "moderator")
    private = make_report(naledi)
    with pytest.raises(services.CommunityError):
        services.add_comment(faith, private, "hello")
    sensitive = publish(make_report(naledi, category="suspected_abuse", description="Shouting heard at night"), mona,
                        "A concern about possible abuse in the area.")
    with pytest.raises(services.CommunityError):
        services.add_comment(faith, sensitive, "hello")
    open_report = publish(make_report(naledi, area="Another Ward"), mona)
    services.add_comment(faith, open_report, "Thanks for sharing this.")
    with pytest.raises(services.CommunityError):
        services.add_comment(faith, open_report, "write to me at someone@example.test")
    assert open_report.comments.count() == 1


def test_comment_form_through_the_real_page():
    naledi, faith, mona = person("Naledi"), person("Faith"), person("Mona", "moderator")
    report = publish(make_report(naledi), mona)
    response = client_for(faith).post(reverse("community:comment", args=[report.pk]), {"body": "Stay safe everyone."})
    assert response.status_code == 302 and report.comments.count() == 1
    page = client_for(naledi).get(reverse("community:report", args=[report.pk])).content.decode()
    assert "Stay safe everyone." in page


def test_flagging_is_once_per_person_and_only_for_public_content(monkeypatch):
    naledi, faith, mona = person("Naledi"), person("Faith"), person("Mona", "moderator")
    private = make_report(naledi)
    with pytest.raises(services.CommunityError):
        services.flag(faith, "privacy", report=private)
    report = publish(make_report(naledi, area="Another Ward"), mona)
    assert services.flag(faith, "privacy", report=report) is True
    assert services.flag(faith, "privacy", report=report) is False
    assert ContentFlag.objects.count() == 1
    _, flagged = services.moderation_queue()
    assert report in list(flagged)
    services.dismiss_flags(report, mona)
    assert not ContentFlag.objects.filter(resolved_at__isnull=True).exists()


def test_flag_limit_per_day(monkeypatch):
    monkeypatch.setitem(services.DAILY_LIMITS, "flag", 2)
    mona, faith = person("Mona", "moderator"), person("Faith")
    reports = [publish(make_report(person(f"Author{i}"), area=f"Ward {i}"), mona) for i in range(3)]
    services.flag(faith, "other", report=reports[0])
    services.flag(faith, "other", report=reports[1])
    with pytest.raises(services.CommunityError):
        services.flag(faith, "other", report=reports[2])


def test_hidden_comments_disappear_and_flags_close():
    naledi, faith, mona = person("Naledi"), person("Faith"), person("Mona", "moderator")
    report = publish(make_report(naledi), mona)
    comment = services.add_comment(faith, report, "A rude comment")
    services.flag(naledi, "harassment", comment=comment)
    services.hide_comment(comment, mona, "Rude")
    comment.refresh_from_db()
    assert comment.is_hidden and not ContentFlag.objects.filter(resolved_at__isnull=True).exists()
    assert "A rude comment" not in client_for(naledi).get(reverse("community:report", args=[report.pk])).content.decode()


def test_daily_report_limit():
    naledi = person("Naledi")
    for i in range(services.DAILY_LIMITS["report"]):
        make_report(naledi, area=f"Ward {i}")
    with pytest.raises(services.CommunityError):
        make_report(naledi, area="One more ward")


def test_new_reports_pause_after_repeated_rejections():
    naledi, mona = person("Naledi"), person("Mona", "moderator")
    for i in range(services.REJECTION_LOCKOUT):
        services.transition(make_report(naledi, area=f"Ward {i}"), "rejected", mona, note="Not clear enough")
    with pytest.raises(services.CommunityError):
        make_report(naledi, area="Ward 9")


def test_possible_duplicates_are_marked_for_moderators_only():
    naledi, faith, mona = person("Naledi"), person("Faith"), person("Mona", "moderator")
    first = make_report(naledi)
    second = make_report(faith, area="fictional ward")  # case-insensitive match
    assert second.possible_duplicate_of == first
    other_category = make_report(faith, category="harassment", description="Followed after work")
    assert other_category.possible_duplicate_of is None


# --- Witness Mode -----------------------------------------------------------------------------------------------

def test_witness_concern_is_private_and_notifies_nobody():
    naledi, faith, mona = person("Naledi"), person("Faith"), person("Mona", "moderator")
    response = client_for(naledi).post(reverse("community:witness"), {
        "about": "adult", "area": "Fictional Ward", "what_seen": "WITNESS-SENTINEL I heard shouting every night",
        "seems_urgent": "on"})
    assert response.status_code == 302
    concern = WitnessConcern.objects.get()
    assert concern.seems_urgent and concern.status == WitnessConcern.Status.NEW

    assert CommunityReport.objects.count() == 0 and NotificationDelivery.objects.count() == 0
    assert "WITNESS-SENTINEL" not in client_for(faith).get(reverse("community:feed")).content.decode()
    assert "WITNESS-SENTINEL" not in client_for(faith).get(reverse("community:mine")).content.decode()
    assert "WITNESS-SENTINEL" in client_for(mona).get(reverse("community:mod_witness")).content.decode()
    assert client_for(faith).get(reverse("community:mod_witness")).status_code == 403


def test_moderator_reviews_a_concern_and_the_sender_sees_the_note():
    naledi, mona, moses = person("Naledi"), person("Mona", "moderator"), person("Moses", "moderator")
    concern = services.submit_witness(naledi, about="child", area="", what_seen="Worried about a neighbour's child",
                                      seems_urgent=False)
    client_for(mona).post(reverse("community:mod_witness"), {
        "concern": str(concern.pk), "status": "reviewed", "note": "Thank you. Please see the support page."})
    concern.refresh_from_db()
    assert concern.status == WitnessConcern.Status.REVIEWED and concern.reviewed_by == mona
    assert "Please see the support page" in client_for(naledi).get(reverse("community:mine")).content.decode()
    with pytest.raises(services.CommunityError):
        services.review_witness(services.submit_witness(mona, about="adult", area="", what_seen="x", seems_urgent=False),
                                mona, "reviewed")
    services.review_witness(concern, moses, "closed")
    concern.refresh_from_db()
    assert concern.purge_after is not None


def test_witness_daily_limit():
    naledi = person("Naledi")
    for _ in range(services.DAILY_LIMITS["witness"]):
        services.submit_witness(naledi, about="adult", area="", what_seen="x", seems_urgent=False)
    with pytest.raises(services.CommunityError):
        services.submit_witness(naledi, about="adult", area="", what_seen="x", seems_urgent=False)


# --- retention and audit ---------------------------------------------------------------------------------------

def test_purge_removes_only_expired_rejected_or_resolved_records():
    naledi, mona = person("Naledi"), person("Mona", "moderator")
    rejected = make_report(naledi, area="Ward A")
    services.transition(rejected, "rejected", mona, note="Not enough detail")
    kept = publish(make_report(naledi, area="Ward B"), mona)
    closed = services.submit_witness(naledi, about="adult", area="", what_seen="x", seems_urgent=False)
    services.review_witness(closed, mona, "closed")

    services.purge_expired()  # nothing is due yet, so nothing is removed
    assert CommunityReport.objects.filter(pk=rejected.pk).exists()
    services.purge_expired(now=timezone.now() + timedelta(days=91))
    assert not CommunityReport.objects.filter(pk=rejected.pk).exists()
    assert not WitnessConcern.objects.filter(pk=closed.pk).exists()
    assert CommunityReport.objects.filter(pk=kept.pk).exists()


def test_audit_records_actions_without_report_text():
    naledi, mona = person("Naledi"), person("Mona", "moderator")
    report = publish(make_report(naledi), mona)
    services.submit_witness(naledi, about="adult", area="", what_seen="WITNESS-SENTINEL", seems_urgent=False)
    events = AuditEvent.objects.filter(action__startswith="community.")
    assert events.count() >= 3
    blob = json.dumps(list(events.values("action", "object_type", "object_id", "metadata")), default=str)
    for secret in ("SECRET-DETAIL-XYZ", "WITNESS-SENTINEL", SUMMARY):
        assert secret not in blob
    assert str(report.pk) in blob  # the id is recorded, never the content
