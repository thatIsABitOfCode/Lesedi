"""SHIELD privacy assessment: findings come from the user's answers and LESEDI's own settings, are labelled by source,
and never claim to detect spyware or monitor a device."""
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from core.findings import INFERRED, SOURCE_LABELS, SYSTEM_CHECKED, USER_REPORTED
from safety import services as safety
from safety.models import Permission
from shield import services as shield
from shield.models import ShieldSelfReport
from tests.factories import ALERT, SENTINEL_DESTINATION, complete_plan, make_circle, make_contact, make_user

pytestmark = pytest.mark.django_db


def codes(user, **kw):
    return {f.code for f in shield.assess(user, **kw)}


def test_every_finding_explains_itself_and_says_where_it_came_from():
    owner = make_user()
    ShieldSelfReport.objects.create(owner=owner, shared_account_access=True, suspects_monitoring=True)
    findings = shield.assess(owner)
    assert findings
    for f in findings:
        assert f.title and f.why and f.action
        assert f.severity in {"high", "medium", "low"} and f.source in SOURCE_LABELS


@pytest.mark.parametrize("field,code,severity", [
    ("shared_account_access", "SHARED_ACCOUNT", "high"),
    ("shared_device", "SHARED_DEVICE", "high"),
    ("suspects_monitoring", "SUSPECTED_MONITORING", "high"),
    ("previews_visible", "PREVIEWS_VISIBLE", "medium"),
    ("location_always_shared", "LOCATION_SHARED", "medium"),
])
def test_the_users_own_answers_become_findings_labelled_as_user_reported(field, code, severity):
    owner = make_user()
    assert code not in codes(owner)
    ShieldSelfReport.objects.update_or_create(owner=owner, defaults={field: True})
    finding = next(f for f in shield.assess(owner) if f.code == code)
    assert finding.severity == severity and finding.source == USER_REPORTED  # LESEDI cannot verify these


def test_missing_backup_and_missing_mfa_are_reported_for_a_new_account():
    found = codes(make_user())
    assert {"NO_BACKUP", "NO_MFA"} <= found


def test_a_complete_circle_no_longer_reports_a_missing_backup():
    assert "NO_BACKUP" not in codes(make_circle().owner)


def test_overly_broad_permissions_without_a_role_are_inferred():
    circle = make_circle()
    extra = make_contact(circle.owner, "Extra")
    safety.set_permissions(circle.plan, extra, ALERT | {Permission.RECEIVE_INSTRUCTION})
    finding = next(f for f in shield.assess(circle.owner) if f.code == f"BROAD_NO_ROLE:{extra.id}")
    assert finding.source == INFERRED  # a suggestion, not a fact


def test_old_permissions_are_flagged_for_review_by_a_system_check():
    circle = make_circle()
    later = timezone.now() + timedelta(days=100)
    assert f"STALE_PERMISSIONS:{circle.faith.id}" not in codes(circle.owner)
    finding = next(f for f in shield.assess(circle.owner, now=later) if f.code == f"STALE_PERMISSIONS:{circle.faith.id}")
    assert finding.source == SYSTEM_CHECKED


def test_a_stored_safe_destination_is_noted_as_a_risk_if_the_account_is_accessed():
    owner = make_user()
    plan = safety.get_or_create_plan(owner)
    assert "DESTINATION_STORED" not in codes(owner)
    plan.safe_destination = SENTINEL_DESTINATION
    safety.save_plan(plan)
    assert "DESTINATION_STORED" in codes(owner)


def test_the_page_states_what_shield_cannot_do_and_does_not_leak_the_plan(client):
    owner = make_user()
    complete_plan(safety.get_or_create_plan(owner))
    client.force_login(owner)
    html = client.get(reverse("shield:page")).content.decode()
    assert "cannot detect spyware" in html
    assert "Where this comes from" in html
    assert SENTINEL_DESTINATION not in html  # the finding says a destination exists, never what it is


def test_saving_answers_through_the_page_changes_the_findings(client):
    owner = make_user()
    client.force_login(owner)
    assert client.post(reverse("shield:page"), {"shared_account_access": "on"}).status_code == 302
    html = client.get(reverse("shield:page")).content.decode()
    assert "Someone else may be able to get into your accounts" in html and "You told us" in html
    assert ShieldSelfReport.objects.get(owner=owner).shared_account_access is True


def test_users_cannot_see_or_alter_each_others_answers(client):
    first, second = make_user(), make_user("other@example.test", "Other")
    ShieldSelfReport.objects.create(owner=first, suspects_monitoring=True)
    client.force_login(second)
    html = client.get(reverse("shield:page")).content.decode()
    assert "You suspect your phone or accounts are monitored" not in html
    client.post(reverse("shield:page"), {"previews_visible": "on"})
    assert ShieldSelfReport.objects.get(owner=first).previews_visible is False
