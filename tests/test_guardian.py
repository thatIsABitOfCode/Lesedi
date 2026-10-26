"""Guardian Mode: state machine, escalation, honest status reporting, idempotency, concurrency and the HTTP/API layer.

Nothing here can send a real message: the notification adapter is the simulator (see conftest.py)."""
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from django.db import connection, connections
from django.test import Client
from django.urls import reverse

from audit.models import AuditEvent
from guardian import services
from guardian.models import ActionStatus, GuardianActivation, ResponderAcknowledgement
from guardian.states import ALLOWED_TRANSITIONS, OPEN_STATES, TERMINAL_STATES, State, can_transition
from notifications import services as notify
from notifications.models import DeliveryStatus, NotificationDelivery
from safety import services as safety
from safety.models import Permission
from tests.factories import (
    ALERT, SENTINEL_DESTINATION, SENTINEL_INSTRUCTION, make_circle, make_user)

pytestmark = pytest.mark.django_db


def kinds(activation):
    return [e.kind for e in activation.events.all()]


def deliveries(activation):
    return list(activation.deliveries.order_by("queued_at"))


# ----------------------------------------------------------------- the state machine itself
def test_every_state_has_a_transition_entry():
    assert set(ALLOWED_TRANSITIONS) == {s.value for s in State}


def test_terminal_states_cannot_be_left():
    for state in TERMINAL_STATES:
        assert ALLOWED_TRANSITIONS[state.value] == ()
        for target in State:
            assert not can_transition(state, target)


def test_valid_and_invalid_transitions():
    assert can_transition(State.ACTIVATED, State.ALERTS_PENDING)
    assert can_transition("awaiting_acknowledgement", "acknowledged")
    assert can_transition(State.BACKUP_CONTACTED, State.ESCALATION_REQUIRED)
    assert can_transition(State.ESCALATION_EXHAUSTED, State.ACKNOWLEDGED)
    assert not can_transition(State.ACTIVATED, State.ACKNOWLEDGED)  # cannot skip straight to "someone saw it"
    assert not can_transition(State.RESOLVED, State.ACTIVATED)
    assert not can_transition(State.ACKNOWLEDGED, State.ESCALATION_REQUIRED)
    assert not can_transition(State.AWAITING_ACKNOWLEDGEMENT, State.BACKUP_CONTACTED)  # must pass through escalation


def test_the_server_refuses_an_invalid_transition():
    circle = make_circle()
    a, _ = services.activate(circle.owner)
    services.close(circle.owner, a.pk, outcome=State.RESOLVED)
    a.refresh_from_db()
    with pytest.raises(services.InvalidTransition):
        services._transition(a, State.ACKNOWLEDGED)


# ----------------------------------------------------------------- activation
def test_activation_notifies_the_primary_and_reports_only_what_happened():
    circle = make_circle()
    a, created = services.activate(circle.owner)
    assert created and a.state == State.AWAITING_ACKNOWLEDGEMENT and a.is_simulation
    assert a.ack_deadline is not None and a.plan_version == circle.plan.version

    [first] = deliveries(a)
    assert first.contact == circle.faith and first.channel == "sms"
    assert first.status == DeliveryStatus.SUBMITTED  # submitted - NOT delivered, NOT seen
    assert first.is_simulated and first.provider == "simulation" and first.delivered_at is None
    assert not a.acknowledgements.exists()
    assert a.actions.get(rank=1).status == ActionStatus.DONE
    assert a.actions.get(rank=2).status == ActionStatus.PENDING  # the backup is NOT contacted yet
    assert all(e.message.startswith("[SIMULATION]") for e in a.events.filter(kind="notification_submitted"))
    assert "plan_loaded" in kinds(a)


def test_notifications_are_neutral_and_never_carry_private_details():
    circle = make_circle()
    a, _ = services.activate(circle.owner)
    body = deliveries(a)[0].body_preview
    assert "/guardian/ack/" in body
    for secret in ("Naledi", SENTINEL_DESTINATION, SENTINEL_INSTRUCTION, "naledi@example.test"):
        assert secret not in body


def test_a_delivery_receipt_is_a_separate_step_and_still_not_an_acknowledgement():
    circle = make_circle()
    a, _ = services.activate(circle.owner)
    d = notify.simulate_delivery_receipt(deliveries(a)[0])
    assert d.status == DeliveryStatus.DELIVERED
    a.refresh_from_db()
    assert a.state == State.AWAITING_ACKNOWLEDGEMENT and not a.acknowledgements.exists()
    with pytest.raises(ValueError):
        notify.simulate_delivery_receipt(d)  # cannot be "delivered" twice


def test_a_second_activation_returns_the_open_one_without_notifying_again():
    circle = make_circle()
    first, created1 = services.activate(circle.owner)
    second, created2 = services.activate(circle.owner)
    assert created1 and not created2 and first.pk == second.pk
    assert GuardianActivation.objects.filter(owner=circle.owner).count() == 1
    assert NotificationDelivery.objects.count() == 1


def test_the_same_idempotency_key_never_creates_two_activations():
    circle = make_circle()
    first, _ = services.activate(circle.owner, idempotency_key="tap-1")
    again, created = services.activate(circle.owner, idempotency_key="tap-1")
    assert not created and first.pk == again.pk and NotificationDelivery.objects.count() == 1


def test_a_person_can_start_again_after_resolving():
    circle = make_circle()
    first, _ = services.activate(circle.owner)
    services.close(circle.owner, first.pk, outcome=State.RESOLVED)
    second, created = services.activate(circle.owner)
    assert created and second.pk != first.pk


def test_activation_needs_a_plan():
    with pytest.raises(services.NoActivePlan):
        services.activate(make_user())


def test_with_nobody_to_ask_it_says_so_and_never_claims_help_was_called():
    owner = make_user()
    safety.get_or_create_plan(owner)
    a, _ = services.activate(owner)
    assert a.state == State.ESCALATION_EXHAUSTED and not NotificationDelivery.objects.exists()
    message = a.events.get(kind="exhausted").message
    assert "has not contacted emergency services" in message and "local emergency services" in message


# ----------------------------------------------------------------- escalation to the backup
def test_no_acknowledgement_in_time_moves_on_to_the_backup():
    circle = make_circle()
    a, _ = services.activate(circle.owner)
    assert services.process_due(now=a.ack_deadline - timedelta(seconds=1)) == 0  # not due yet
    a.refresh_from_db()
    assert a.state == State.AWAITING_ACKNOWLEDGEMENT and len(deliveries(a)) == 1

    assert services.process_due(now=a.ack_deadline + timedelta(seconds=1)) == 1
    a.refresh_from_db()
    assert a.state == State.BACKUP_CONTACTED
    first, second = deliveries(a)
    assert (first.contact, second.contact) == (circle.faith, circle.mapaseka)
    assert (first.channel, second.channel) == ("sms", "whatsapp")
    assert second.status == DeliveryStatus.SUBMITTED and a.ack_deadline is not None
    assert {"ack_timeout", "notification_submitted"} <= set(kinds(a))
    assert a.actions.get(rank=2).status == ActionStatus.DONE


def test_after_the_backup_also_times_out_it_stops_and_tells_the_truth():
    circle = make_circle()
    a, _ = services.activate(circle.owner)
    services.process_due(now=a.ack_deadline + timedelta(seconds=1))
    a.refresh_from_db()
    services.process_due(now=a.ack_deadline + timedelta(seconds=1))
    a.refresh_from_db()
    assert a.state == State.ESCALATION_EXHAUSTED and a.ack_deadline is None
    assert len(deliveries(a)) == 2  # nobody was contacted a third time
    assert "has not contacted emergency services" in a.events.get(kind="exhausted").message


def test_running_the_timeout_job_twice_does_not_notify_twice():
    circle = make_circle()
    a, _ = services.activate(circle.owner)
    later = a.ack_deadline + timedelta(seconds=1)
    services.process_due(now=later)
    services.process_due(now=later)
    assert NotificationDelivery.objects.count() == 2


def test_a_failed_primary_is_retried_a_limited_number_of_times_then_the_backup_is_tried(settings):
    circle = make_circle()
    a, _ = services.activate(circle.owner, simulate_primary_failure=True)
    faith_tries = [d for d in deliveries(a) if d.contact == circle.faith]
    assert len(faith_tries) == settings.GUARDIAN_MAX_SEND_ATTEMPTS
    assert all(d.status == DeliveryStatus.FAILED and "Simulated" in d.error for d in faith_tries)
    assert a.actions.get(rank=1).status == ActionStatus.FAILED
    [backup] = [d for d in deliveries(a) if d.contact == circle.mapaseka]
    assert backup.status == DeliveryStatus.SUBMITTED
    assert a.state == State.BACKUP_CONTACTED
    assert {"notification_failed", "action_failed", "notification_submitted"} <= set(kinds(a))


def test_a_responder_without_alert_permission_is_skipped_not_notified():
    circle = make_circle()
    safety.set_permissions(circle.plan, circle.faith, {Permission.ACKNOWLEDGE_ALERT})  # alert permission withdrawn
    a, _ = services.activate(circle.owner)
    assert not NotificationDelivery.objects.filter(contact=circle.faith).exists()
    assert a.actions.get(rank=1).status == ActionStatus.SKIPPED
    assert a.state == State.BACKUP_CONTACTED and NotificationDelivery.objects.filter(contact=circle.mapaseka).exists()


def test_a_removed_contact_is_never_notified():
    circle = make_circle()
    safety.revoke_contact(circle.faith)
    a, _ = services.activate(circle.owner)
    assert not NotificationDelivery.objects.filter(contact=circle.faith).exists()
    assert [d.contact for d in deliveries(a)] == [circle.mapaseka]


def test_demo_clock_runs_the_real_escalation_code_and_only_in_simulation(settings):
    circle = make_circle()
    a, _ = services.activate(circle.owner)
    a = services.demo_force_timeout(circle.owner, a.pk)
    assert a.state == State.BACKUP_CONTACTED and len(deliveries(a)) == 2
    assert "demo_clock" in kinds(a)

    settings.LESEDI_NOTIFICATION_MODE = "live"
    other = make_circle(make_user("other@example.test", "Other"))
    b, _ = services.activate(other.owner)
    with pytest.raises(services.GuardianError):
        services.demo_force_timeout(other.owner, b.pk)


# ----------------------------------------------------------------- never pretend to send real messages
def test_outside_simulation_mode_nothing_is_claimed_to_have_been_sent(settings):
    settings.LESEDI_NOTIFICATION_MODE = "live"  # no live adapter exists in this build
    circle = make_circle()
    a, _ = services.activate(circle.owner, simulate_primary_failure=True)
    assert not a.is_simulation and not a.simulate_primary_failure
    sent = deliveries(a)
    assert sent and all(d.status == DeliveryStatus.FAILED and not d.is_simulated and d.provider == "none" for d in sent)
    assert "No live provider adapter" in sent[0].error
    assert a.state == State.ESCALATION_EXHAUSTED
    assert not any(e.message.startswith("[SIMULATION]") for e in a.events.all())


# ----------------------------------------------------------------- acknowledgement
def test_acknowledgement_means_seen_not_help_is_coming():
    circle = make_circle()
    a, _ = services.activate(circle.owner)
    token = services.make_ack_token(a, circle.faith)
    a, contact, created = services.acknowledge(token)
    assert created and contact == circle.faith and a.state == State.ACKNOWLEDGED and a.ack_deadline is None
    message = a.events.get(kind="acknowledged").message
    assert "does not confirm that anyone is travelling" in message
    _, _, again = services.acknowledge(token)
    assert not again and ResponderAcknowledgement.objects.count() == 1  # idempotent


def test_once_acknowledged_the_timeout_job_does_nothing():
    circle = make_circle()
    a, _ = services.activate(circle.owner)
    services.acknowledge(services.make_ack_token(a, circle.faith))
    assert services.process_due(now=a.activated_at + timedelta(days=1)) == 0
    assert NotificationDelivery.objects.count() == 1


def test_a_contact_who_was_never_notified_cannot_acknowledge():
    circle = make_circle()
    a, _ = services.activate(circle.owner)
    with pytest.raises(services.NotPermitted):
        services.acknowledge(services.make_ack_token(a, circle.mapaseka))


def test_withdrawing_the_acknowledge_permission_is_respected():
    circle = make_circle()
    a, _ = services.activate(circle.owner)
    safety.set_permissions(circle.plan, circle.faith, {Permission.RECEIVE_ALERT})
    with pytest.raises(services.NotPermitted):
        services.acknowledge(services.make_ack_token(a, circle.faith))


def test_bad_and_expired_links_are_rejected(settings):
    circle = make_circle()
    a, _ = services.activate(circle.owner)
    with pytest.raises(services.InvalidToken):
        services.acknowledge("garbage")
    token = services.make_ack_token(a, circle.faith)
    settings.GUARDIAN_ACK_TOKEN_MAX_AGE = -1
    with pytest.raises(services.InvalidToken):
        services.acknowledge(token)


def test_a_late_acknowledgement_after_exhaustion_is_still_recorded():
    circle = make_circle()
    a, _ = services.activate(circle.owner)
    services.process_due(now=a.ack_deadline + timedelta(seconds=1))
    a.refresh_from_db()
    services.process_due(now=a.ack_deadline + timedelta(seconds=1))
    a, _, created = services.acknowledge(services.make_ack_token(a, circle.faith))
    assert created and a.state == State.ACKNOWLEDGED


# ----------------------------------------------------------------- ending an activation
def test_cancelling_stops_further_escalation_and_ignores_late_acknowledgements():
    circle = make_circle()
    a, _ = services.activate(circle.owner)
    ended = services.close(circle.owner, a.pk, outcome=State.CANCELLED)
    assert ended.state == State.CANCELLED and ended.closed_at is not None
    assert ended.actions.get(rank=2).status == ActionStatus.SKIPPED
    assert services.process_due(now=a.ack_deadline + timedelta(days=1)) == 0
    assert NotificationDelivery.objects.count() == 1
    _, _, created = services.acknowledge(services.make_ack_token(a, circle.faith))
    assert not created and not ResponderAcknowledgement.objects.exists()
    assert services.close(circle.owner, a.pk, outcome=State.RESOLVED).state == State.CANCELLED  # stays ended


def test_only_the_owner_can_end_an_activation():
    circle = make_circle()
    a, _ = services.activate(circle.owner)
    stranger = make_user("other@example.test", "Other")
    with pytest.raises(GuardianActivation.DoesNotExist):
        services.close(stranger, a.pk, outcome=State.CANCELLED)


def test_an_exhausted_activation_can_be_retried_after_fixing_the_plan():
    circle = make_circle()
    safety.set_permissions(circle.plan, circle.faith, set())
    safety.set_permissions(circle.plan, circle.mapaseka, set())
    first, _ = services.activate(circle.owner)
    assert first.state == State.ESCALATION_EXHAUSTED
    safety.set_permissions(circle.plan, circle.faith, ALERT)
    second, created = services.activate(circle.owner)
    first.refresh_from_db()
    assert created and second.state == State.AWAITING_ACKNOWLEDGEMENT and first.state == State.CANCELLED


def test_audit_records_exist_and_hold_no_contact_details():
    circle = make_circle()
    a, _ = services.activate(circle.owner)
    services.acknowledge(services.make_ack_token(a, circle.faith))
    actions = set(AuditEvent.objects.values_list("action", flat=True))
    assert {"guardian.activated", "guardian.transition", "guardian.acknowledged"} <= actions
    dump = json.dumps(list(AuditEvent.objects.values("metadata", "object_id", "object_type")), default=str)
    assert "+27" not in dump and "example.test" not in dump


# ----------------------------------------------------------------- concurrency (PostgreSQL only)
@pytest.mark.django_db(transaction=True)
def test_simultaneous_activations_create_exactly_one_activation_and_one_notification():
    if connection.vendor == "sqlite":
        pytest.skip("Needs PostgreSQL: SQLite cannot run this concurrency test meaningfully.")
    circle = make_circle()

    def attempt(_):
        try:
            a, created = services.activate(circle.owner)
            return str(a.pk), created
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(6)))
    assert len({pk for pk, _ in results}) == 1
    assert sum(1 for _, created in results if created) == 1
    assert GuardianActivation.objects.filter(owner=circle.owner).count() == 1
    assert NotificationDelivery.objects.filter(contact=circle.faith).count() == 1


# ----------------------------------------------------------------- the responder's public page
def test_the_responder_page_shows_the_instruction_only_to_people_allowed_to_see_it(client):
    circle = make_circle()
    a, _ = services.activate(circle.owner)
    faith = client.get(reverse("guardian:ack", args=[services.make_ack_token(a, circle.faith)]))
    mapaseka = client.get(reverse("guardian:ack", args=[services.make_ack_token(a, circle.mapaseka)]))
    assert faith.status_code == mapaseka.status_code == 200
    assert SENTINEL_INSTRUCTION in faith.content.decode()           # Faith was given this permission
    assert SENTINEL_INSTRUCTION not in mapaseka.content.decode()    # Mapaseka was not
    for page in (faith, mapaseka):
        assert SENTINEL_DESTINATION not in page.content.decode()    # the safe destination is never shared


def test_a_responder_can_acknowledge_through_the_page_and_a_forged_link_is_refused(client):
    circle = make_circle()
    a, _ = services.activate(circle.owner)
    url = reverse("guardian:ack", args=[services.make_ack_token(a, circle.faith)])
    assert client.post(url).status_code == 200
    assert ResponderAcknowledgement.objects.filter(activation=a, contact=circle.faith).exists()
    assert client.get(reverse("guardian:ack", args=["forged-token"])).status_code == 404


def test_a_link_for_an_ended_activation_shows_no_details(client):
    circle = make_circle()
    a, _ = services.activate(circle.owner)
    services.close(circle.owner, a.pk, outcome=State.RESOLVED)
    page = client.get(reverse("guardian:ack", args=[services.make_ack_token(a, circle.faith)]))
    assert SENTINEL_INSTRUCTION not in page.content.decode()


# ----------------------------------------------------------------- the API the Guardian page uses
def _post(client, name, data=None, args=None):
    return client.post(reverse(name, args=args), data=json.dumps(data or {}), content_type="application/json")


def test_api_activation_returns_a_simulation_notice_and_an_honest_timeline(client):
    circle = make_circle()
    client.force_login(circle.owner)
    response = _post(client, "guardian_api:activate", {"idempotency_key": "k1"})
    body = response.json()
    assert response.status_code == 201 and body["state"] == "awaiting_acknowledgement"
    assert body["is_simulation"] and body["notice"].startswith("SIMULATION: no real SMS")
    assert "no emergency service was contacted" in body["notice"]
    assert [d["contact"] for d in body["deliveries"]] == ["Faith"]
    assert body["deliveries"][0]["status_code"] == "submitted" and body["acknowledgements"] == []
    assert body["events"] and "emergency services" in body["limits"]
    assert _post(client, "guardian_api:activate", {"idempotency_key": "k1"}).status_code == 200  # not created again


def test_api_demo_scenario_primary_timeout_then_backup_then_acknowledged_then_resolved(client):
    circle = make_circle()
    client.force_login(circle.owner)
    activation = _post(client, "guardian_api:activate").json()
    skipped = _post(client, "guardian_api:simulate_timeout", args=[activation["id"]]).json()
    assert skipped["state"] == "backup_contacted"
    assert [d["contact"] for d in skipped["deliveries"]] == ["Faith", "Mapaseka"]
    assert any("No acknowledgement within" in e["message"] for e in skipped["events"])

    link = next(d["responder_link"] for d in skipped["deliveries"] if d["contact"] == "Mapaseka")
    assert Client().post(link).status_code == 200  # Mapaseka, not logged in, opens the link and acknowledges
    current = client.get(reverse("guardian_api:current")).json()["activation"]
    assert current["state"] == "acknowledged" and [k["contact"] for k in current["acknowledgements"]] == ["Mapaseka"]

    resolved = _post(client, "guardian_api:resolve", args=[activation["id"]]).json()
    assert resolved["state"] == "resolved" and not resolved["is_open"]


def test_api_never_lets_one_user_see_or_end_another_users_activation(client):
    mine = make_circle()
    a, _ = services.activate(mine.owner)
    client.force_login(make_user("other@example.test", "Other"))
    assert client.get(reverse("guardian_api:detail", args=[a.pk])).status_code == 404
    assert _post(client, "guardian_api:cancel", args=[a.pk]).status_code == 404
    a.refresh_from_db()
    assert a.state == State.AWAITING_ACKNOWLEDGEMENT


def test_api_without_a_plan_gives_a_clear_error(client):
    client.force_login(make_user())
    response = _post(client, "guardian_api:activate")
    assert response.status_code == 400 and "safety plan" in response.json()["detail"]


def test_guardian_page_always_states_the_simulation_and_the_limits(client):
    circle = make_circle()
    client.force_login(circle.owner)
    html = client.get(reverse("guardian:page")).content.decode()
    assert "SIMULATION: no real SMS" in html and "does not contact emergency services" in html
    assert "Faith" in html and "Mapaseka" in html


def test_open_and_terminal_state_sets_do_not_overlap():
    assert not set(OPEN_STATES) & set(TERMINAL_STATES)
