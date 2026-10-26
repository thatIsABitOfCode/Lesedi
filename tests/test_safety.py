"""Living Safety Protocol, plan health, Safety Circle permissions and the invitation/consent flow."""
from datetime import date, timedelta
from urllib.parse import urlparse

import pytest
from django.test import Client
from django.urls import reverse

from core.findings import SYSTEM_CHECKED, USER_REPORTED
from notifications.channels import Channel
from safety import services as safety
from safety.health import assess_plan
from safety.models import ContactStatus, Permission, SafetyPlanPermission, TrustedContact
from tests.factories import (
    ALERT, SENTINEL_DESTINATION, SENTINEL_INSTRUCTION, complete_plan, make_circle, make_contact, make_user)

pytestmark = pytest.mark.django_db


def codes(plan, **kw):
    return {f.code for f in assess_plan(plan, **kw)}


def plan_post(**overrides):
    data = {"title": "My safety plan", "emergency_instructions": "", "safe_destination": "", "transport_notes": "",
            "essential_documents": "", "checkin_method": "", "checkin_time": "", "ack_timeout_seconds": 60,
            "comms_failure_contingency": "", "review_date": ""}
    data.update(overrides)
    return data


# ----------------------------------------------------------------- plan and versions
def test_a_plan_is_created_once_and_starts_at_version_one():
    user = make_user()
    plan = safety.get_or_create_plan(user)
    assert safety.get_or_create_plan(user).pk == plan.pk
    assert plan.version == 1 and plan.versions.count() == 1


def test_every_save_adds_an_immutable_version_entry():
    plan = complete_plan(safety.get_or_create_plan(make_user()))
    assert plan.version == 2 and plan.versions.count() == 2
    newest, first = list(plan.versions.all())
    assert newest.snapshot["emergency_instructions"] == SENTINEL_INSTRUCTION
    assert first.snapshot["emergency_instructions"] == ""  # history was not rewritten


def test_invalid_plan_data_is_rejected_and_nothing_is_saved(client):
    user = make_user()
    client.force_login(user)
    plan = safety.get_or_create_plan(user)
    response = client.post(reverse("safety:plan"), plan_post(ack_timeout_seconds=5))  # minimum is 10
    assert response.status_code == 200
    plan.refresh_from_db()
    assert plan.version == 1


def test_a_valid_plan_form_saves_and_bumps_the_version(client):
    user = make_user()
    client.force_login(user)
    response = client.post(reverse("safety:plan"), plan_post(emergency_instructions="Call me.", review_date="2031-01-31"))
    assert response.status_code == 302
    plan = safety.get_or_create_plan(user)
    assert plan.emergency_instructions == "Call me." and plan.version == 2


def test_a_plan_is_private_to_its_owner(client):
    complete_plan(safety.get_or_create_plan(make_user()))
    other = make_user("other@example.test", "Other")
    client.force_login(other)
    for name in ("safety:plan", "safety:health", "safety:circle", "shield:page"):
        body = client.get(reverse(name)).content.decode()
        assert SENTINEL_DESTINATION not in body and SENTINEL_INSTRUCTION not in body


# ----------------------------------------------------------------- plan health
def test_an_empty_plan_gets_calm_actionable_findings():
    found = assess_plan(safety.get_or_create_plan(make_user()))
    assert {"NO_RESPONDER", "NO_INSTRUCTIONS", "TRANSPORT_UNCONFIRMED", "NO_COMMS_CONTINGENCY", "NO_CHECKIN",
            "NO_REVIEW_DATE"} <= {f.code for f in found}
    for f in found:
        assert f.action and f.why and f.source_label  # every finding says what to do and where it came from


def test_a_complete_plan_with_two_responders_is_clean_of_the_main_gaps():
    circle = make_circle()
    found = codes(circle.plan)
    assert not found & {"NO_RESPONDER", "NO_BACKUP", "NO_INSTRUCTIONS", "TRANSPORT_UNCONFIRMED",
                        "NO_COMMS_CONTINGENCY", "NO_CHECKIN", "NO_REVIEW_DATE", "PLAN_EXPIRED"}


def test_missing_backup_is_detected():
    circle = make_circle()
    safety.remove_responder(circle.plan, circle.mapaseka)
    assert "NO_BACKUP" in codes(circle.plan)


def test_unverified_contact_details_are_flagged_as_user_reported():
    owner = make_user()
    plan = complete_plan(safety.get_or_create_plan(owner))
    contact = make_contact(owner, "Faith", confirmed=False)
    safety.assign_responder(plan, contact, 1)
    finding = next(f for f in assess_plan(plan) if f.code == f"DETAILS_UNCONFIRMED:{contact.id}")
    assert finding.source == USER_REPORTED  # LESEDI did not verify these details
    contact.owner_confirmed_details = True
    contact.save()
    assert f"DETAILS_UNCONFIRMED:{contact.id}" not in codes(plan)


def test_a_single_communication_channel_and_missing_permissions_are_flagged():
    owner = make_user()
    plan = complete_plan(safety.get_or_create_plan(owner))
    contact = make_contact(owner, "Faith", email="")
    safety.assign_responder(plan, contact, 1)
    found = codes(plan)
    assert f"ONE_CHANNEL:{contact.id}" in found
    assert f"NO_ALERT_PERMISSION:{contact.id}" in found and f"NO_ACK_PERMISSION:{contact.id}" in found


def test_an_expired_review_date_is_flagged_but_a_future_one_is_not():
    circle = make_circle()
    assert "PLAN_EXPIRED" not in codes(circle.plan)
    assert "PLAN_EXPIRED" in codes(circle.plan, today=date.today() + timedelta(days=90))
    plan_expired = next(f for f in assess_plan(circle.plan, today=date.today() + timedelta(days=90))
                        if f.code == "PLAN_EXPIRED")
    assert plan_expired.source == SYSTEM_CHECKED


def test_permissions_without_a_role_are_noticed():
    circle = make_circle()
    extra = make_contact(circle.owner, "Extra")
    safety.set_permissions(circle.plan, extra, ALERT)
    assert f"PERMISSIONS_WITHOUT_ROLE:{extra.id}" in codes(circle.plan)


# ----------------------------------------------------------------- Safety Circle: permissions and roles
def test_nothing_is_granted_by_default():
    owner = make_user()
    plan = safety.get_or_create_plan(owner)
    contact = make_contact(owner, "Faith")
    assert safety.active_permissions(plan, contact) == set()
    assert not safety.has_permission(plan, contact, Permission.RECEIVE_ALERT)


def test_permissions_are_granular_and_revocation_keeps_history():
    circle = make_circle()
    safety.set_permissions(circle.plan, circle.faith, {Permission.RECEIVE_ALERT})
    assert safety.has_permission(circle.plan, circle.faith, Permission.RECEIVE_ALERT)
    assert not safety.has_permission(circle.plan, circle.faith, Permission.ACKNOWLEDGE_ALERT)
    assert not safety.has_permission(circle.plan, circle.faith, Permission.RECEIVE_INSTRUCTION)
    revoked = SafetyPlanPermission.objects.filter(plan=circle.plan, contact=circle.faith, revoked_at__isnull=False)
    assert revoked.count() == 2  # revoked, not erased


def test_only_accepted_contacts_can_become_responders():
    owner = make_user()
    plan = safety.get_or_create_plan(owner)
    pending = make_contact(owner, "Faith", active=False)
    with pytest.raises(safety.SafetyError):
        safety.assign_responder(plan, pending, 1)


def test_a_responder_position_cannot_be_given_to_two_people():
    circle = make_circle()
    third = make_contact(circle.owner, "Third")
    with pytest.raises(safety.SafetyError):
        safety.assign_responder(circle.plan, third, 1)


def test_nobody_can_use_someone_elses_contact_or_plan():
    mine, theirs = make_circle(), make_circle(make_user("other@example.test", "Other"))
    with pytest.raises(safety.SafetyError):
        safety.assign_responder(mine.plan, theirs.faith, 3)
    with pytest.raises(safety.SafetyError):
        safety.set_permissions(mine.plan, theirs.faith, ALERT)


def test_removing_a_contact_revokes_everything_and_frees_their_slot():
    circle = make_circle()
    safety.revoke_contact(circle.faith)
    circle.faith.refresh_from_db()
    assert circle.faith.status == ContactStatus.REVOKED
    assert safety.active_permissions(circle.plan, circle.faith) == set()
    assert not circle.plan.responders.filter(contact=circle.faith).exists()


def test_other_users_cannot_see_or_change_my_contacts(client):
    mine = make_circle()
    client.force_login(make_user("other@example.test", "Other"))
    url = reverse("safety:contact", args=[mine.faith.pk])
    assert client.get(url).status_code == 404
    assert client.post(url, {"action": "revoke"}).status_code == 404
    mine.faith.refresh_from_db()
    assert mine.faith.status == ContactStatus.ACTIVE


# ----------------------------------------------------------------- invitation and consent
def test_invitation_flow_requires_the_contacts_own_acceptance():
    owner = make_user()
    contact = make_contact(owner, "Faith", active=False)
    invitation, token = safety.create_invitation(contact)
    contact.refresh_from_db()
    assert contact.status == ContactStatus.INVITED and contact.consented_at is None
    safety.respond_to_invitation(safety.load_invitation(token), accept=True)
    contact.refresh_from_db()
    assert contact.status == ContactStatus.ACTIVE and contact.consented_at is not None
    assert safety.load_invitation(token) is None  # one use only


def test_declining_an_invitation_removes_the_contact():
    contact = make_contact(make_user(), "Faith", active=False)
    _, token = safety.create_invitation(contact)
    safety.respond_to_invitation(safety.load_invitation(token), accept=False)
    contact.refresh_from_db()
    assert contact.status == ContactStatus.REVOKED


def test_tampered_and_expired_invitations_are_rejected(settings):
    contact = make_contact(make_user(), "Faith", active=False)
    _, token = safety.create_invitation(contact)
    assert safety.load_invitation(token + "x") is None
    settings.INVITATION_MAX_AGE = -1
    assert safety.load_invitation(token) is None


def test_the_public_invitation_page_reveals_only_the_inviters_name(client):
    owner = make_user()
    contact = make_contact(owner, "Faith", active=False, phone="+27 11 111 1111", email="faith.secret@example.test")
    _, token = safety.create_invitation(contact)
    page = client.get(reverse("safety:invite", args=[token]))
    body = page.content.decode()
    assert page.status_code == 200 and "Naledi" in body
    assert "+27 11 111 1111" not in body and "faith.secret@example.test" not in body
    assert client.get(reverse("safety:invite", args=["not-a-real-token"])).status_code == 404


def test_the_circle_pages_work_end_to_end_for_the_owner(client):
    owner = make_user()
    client.force_login(owner)
    response = client.post(reverse("safety:contact_add"), {
        "name": "Faith", "relationship": "Friend", "phone": "+27 00 000 0001", "email": "faith@example.test",
        "preferred_channel": Channel.SMS})
    assert response.status_code == 302
    contact = TrustedContact.objects.get(owner=owner, name="Faith")
    assert contact.status == ContactStatus.PENDING  # nothing is shared until she accepts
    invited = client.post(reverse("safety:contact", args=[contact.pk]), {"action": "invite"})
    assert invited.status_code == 200 and "/plan/invite/" in invited.context["invite_link"]
    path = urlparse(invited.context["invite_link"]).path
    Client().post(path, {"decision": "accept"})
    contact.refresh_from_db()
    assert contact.status == ContactStatus.ACTIVE
