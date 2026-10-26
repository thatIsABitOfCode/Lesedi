"""Plan-health assessment. Wording is deliberately calm: these are suggestions, not alarms."""
from datetime import date

from core.findings import INFERRED, SYSTEM_CHECKED, USER_REPORTED, Finding, sort_findings

from .models import ContactStatus, Permission
from .services import active_permissions


def assess_plan(plan, today=None) -> list:
    today = today or date.today()
    findings = []
    responders = list(plan.responders.select_related("contact").order_by("rank"))

    if not responders:
        findings.append(Finding(
            "NO_RESPONDER", "No responder chosen yet",
            "Guardian Mode has nobody to notify until you choose someone.",
            "Add a trusted contact, invite them, then place them as your primary responder.",
            "high", SYSTEM_CHECKED))
    elif len(responders) == 1:
        findings.append(Finding(
            "NO_BACKUP", "No backup responder",
            "If your first responder cannot be reached, there is nobody to try next.",
            "Add a second person as backup responder.", "high", SYSTEM_CHECKED))

    for r in responders:
        c = r.contact
        perms = active_permissions(plan, c)
        if c.status != ContactStatus.ACTIVE:
            findings.append(Finding(
                f"CONTACT_NOT_ACCEPTED:{c.id}", f"{c.name} has not accepted",
                "Someone who has not agreed to take part should not be relied on.",
                "Send the invitation again, or choose someone else.", "high", SYSTEM_CHECKED))
        if Permission.RECEIVE_ALERT not in perms:
            findings.append(Finding(
                f"NO_ALERT_PERMISSION:{c.id}", f"{c.name} is not allowed to receive alerts",
                "Guardian Mode will skip this person until you allow it.",
                "Open their page in your Safety Circle and tick 'Receive an emergency alert'.", "high", SYSTEM_CHECKED))
        if Permission.ACKNOWLEDGE_ALERT not in perms:
            findings.append(Finding(
                f"NO_ACK_PERMISSION:{c.id}", f"{c.name} cannot acknowledge alerts",
                "Without acknowledgement, LESEDI cannot tell whether they saw the alert and will move on to the next person.",
                "Allow 'Acknowledge an alert' on their page.", "medium", SYSTEM_CHECKED))
        if not c.owner_confirmed_details:
            findings.append(Finding(
                f"DETAILS_UNCONFIRMED:{c.id}", f"Contact details for {c.name} are not confirmed",
                "LESEDI has not independently checked this phone number or email, and you have not marked them as confirmed.",
                "Check the details with them directly (for example by calling), then tick 'I have confirmed these details'.",
                "medium", USER_REPORTED))
        if not (c.phone and c.email):
            findings.append(Finding(
                f"ONE_CHANNEL:{c.id}", f"Only one way to reach {c.name}",
                "If that one channel fails, there is no alternative for this person.",
                "Add a second way to reach them if they are comfortable with that.", "low", SYSTEM_CHECKED))

    if not plan.checkin_method:
        findings.append(Finding(
            "NO_CHECKIN", "No check-in method set",
            "A regular check-in can help someone notice if something is wrong.",
            "Describe how and when you would like to check in. (Automatic check-in reminders are not part of this version.)",
            "low", USER_REPORTED))
    if not plan.emergency_instructions.strip():
        findings.append(Finding(
            "NO_INSTRUCTIONS", "No emergency instruction written",
            "A responder who acknowledges will not know what you would like them to do.",
            "Write a short instruction in your own words. You choose who may see it.", "medium", USER_REPORTED))
    if not plan.transport_confirmed:
        findings.append(Finding(
            "TRANSPORT_UNCONFIRMED", "Transport not confirmed",
            "A plan is stronger when the way to reach a safe place has been checked.",
            "Confirm the arrangement, then tick 'confirmed' on your plan.", "medium", USER_REPORTED))
    if not plan.comms_failure_contingency.strip():
        findings.append(Finding(
            "NO_COMMS_CONTINGENCY", "No plan for a communication failure",
            "Phones can be off, out of data, or taken away.",
            "Write down what should happen if a phone or channel does not work.", "medium", USER_REPORTED))
    if plan.review_date is None:
        findings.append(Finding(
            "NO_REVIEW_DATE", "No review date set",
            "Plans go out of date as life changes.", "Pick a date to look at this plan again.", "low", SYSTEM_CHECKED))
    elif plan.review_date < today:
        findings.append(Finding(
            "PLAN_EXPIRED", "This plan is due for a review",
            f"The review date ({plan.review_date:%d %b %Y}) has passed.",
            "Read through the plan, make any changes, and set a new review date.", "medium", SYSTEM_CHECKED))

    # Inference: someone holds permissions but is not in the responder order.
    responder_ids = {r.contact_id for r in responders}
    for c in plan.owner.trusted_contacts.exclude(status=ContactStatus.REVOKED):
        if c.id not in responder_ids and active_permissions(plan, c):
            findings.append(Finding(
                f"PERMISSIONS_WITHOUT_ROLE:{c.id}", f"{c.name} has permissions but no place in your responder order",
                "Permissions that are not being used are easy to forget.",
                "Remove permissions you no longer need, or give them a place in the order.", "low", INFERRED))
    return sort_findings(findings)
