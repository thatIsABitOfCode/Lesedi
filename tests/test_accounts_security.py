"""Accounts, authentication, access control and security-header tests. All people here are fictional."""
import json
import os
import subprocess
import sys

import pytest
from django.conf import settings as django_settings
from django.core import mail
from django.test import Client
from django.urls import reverse

from accounts.models import Role, User
from audit.models import AuditEvent
from audit.services import record
from tests.factories import PASSWORD, make_circle, make_user

pytestmark = pytest.mark.django_db

LOGIN = "accounts:login"


def _register(client, email="thandi@example.test", password=PASSWORD, password2=None):
    return client.post(reverse("accounts:register"), {
        "email": email, "display_name": "Thandi", "password1": password, "password2": password2 or password})


# ----------------------------------------------------------------- registration and login
def test_register_creates_a_survivor_with_a_hashed_password(client):
    response = _register(client, "Thandi@Example.test")
    assert response.status_code == 302 and response.url == reverse(LOGIN)
    user = User.objects.get(email="thandi@example.test")  # email is normalised to lower case
    assert user.role == Role.SURVIVOR
    assert user.password != PASSWORD and PASSWORD not in user.password


def test_registering_an_existing_email_looks_identical_and_changes_nothing(client):
    original = make_user("naledi@example.test")
    first = _register(client, "new@example.test")
    again = _register(Client(), "naledi@example.test", password="Another-Strong-Pass-77")
    assert first.status_code == again.status_code == 302
    assert first.url == again.url  # no enumeration through the response
    assert User.objects.filter(email="naledi@example.test").count() == 1
    original.refresh_from_db()
    assert original.check_password(PASSWORD)  # the existing account was not touched


def test_weak_or_mismatched_passwords_are_rejected(client):
    assert _register(client, password="short1").status_code == 200
    assert _register(client, password=PASSWORD, password2="Different-Pass-12345").status_code == 200
    assert not User.objects.filter(email="thandi@example.test").exists()


def test_login_works_and_errors_do_not_reveal_whether_an_account_exists(client):
    make_user()
    ok = client.post(reverse(LOGIN), {"username": "naledi@example.test", "password": PASSWORD})
    assert ok.status_code == 302 and ok.url == reverse("core:dashboard")

    anon = Client()
    wrong_password = anon.post(reverse(LOGIN), {"username": "naledi@example.test", "password": "wrong-password-1"})
    no_such_user = anon.post(reverse(LOGIN), {"username": "nobody@example.test", "password": "wrong-password-1"})
    assert wrong_password.status_code == no_such_user.status_code == 200
    assert "did not match" in wrong_password.content.decode()
    assert "did not match" in no_such_user.content.decode()


def test_login_is_rate_limited(client):
    make_user()
    bad = {"username": "naledi@example.test", "password": "wrong-password-1"}
    for _ in range(10):
        assert client.post(reverse(LOGIN), bad).status_code == 200
    assert client.post(reverse(LOGIN), bad).status_code == 429


def test_password_reset_responds_the_same_for_unknown_emails(client):
    make_user()
    known = client.post(reverse("accounts:password_reset"), {"email": "naledi@example.test"})
    unknown = client.post(reverse("accounts:password_reset"), {"email": "nobody@example.test"})
    assert known.status_code == unknown.status_code == 302
    assert known.url == unknown.url
    assert len(mail.outbox) == 1  # only the real account received a message
    assert "/accounts/reset/" in mail.outbox[0].body


@pytest.mark.real_hashing
def test_passwords_are_hashed_with_argon2():
    assert make_user().password.startswith("argon2$")


# ----------------------------------------------------------------- access control
PRIVATE_PAGES = ["safety:plan", "safety:health", "safety:circle", "guardian:page", "shield:page",
                 "evidence:incidents", "core:dashboard", "accounts:security", "accounts:export"]


@pytest.mark.parametrize("name", PRIVATE_PAGES)
def test_private_pages_redirect_anonymous_visitors_to_login(client, name):
    response = client.get(reverse(name))
    assert response.status_code == 302 and "/accounts/login/" in response.url


@pytest.mark.parametrize("name", ["safety:plan", "safety:circle", "guardian:page", "shield:page", "evidence:incidents"])
def test_other_roles_do_not_get_survivor_pages_just_by_having_an_account(client, name):
    for role in (Role.TRUSTED_CONTACT, Role.COMMUNITY_RESPONDER, Role.MODERATOR):
        user = make_user(f"{role}@example.test", "Someone", role=role)
        client.force_login(user)
        assert client.get(reverse(name)).status_code == 403


def test_api_requires_a_logged_in_survivor(client):
    url = reverse("guardian_api:activate")
    assert client.post(url, data="{}", content_type="application/json").status_code in (401, 403)
    client.force_login(make_user("tc@example.test", "Contact", role=Role.TRUSTED_CONTACT))
    assert client.post(url, data="{}", content_type="application/json").status_code == 403


def test_csrf_is_enforced_on_forms_and_on_the_api():
    strict = Client(enforce_csrf_checks=True)
    assert strict.post(reverse(LOGIN), {"username": "x@example.test", "password": "y"}).status_code == 403
    strict.force_login(make_user())
    response = strict.post(reverse("guardian_api:activate"), data="{}", content_type="application/json")
    assert response.status_code == 403


def test_account_export_contains_only_the_owners_data(client):
    mine = make_circle()
    other = make_user("other@example.test", "Other")
    make_circle(other)
    client.force_login(mine.owner)
    data = json.loads(client.get(reverse("accounts:export")).content)
    assert data["account"]["email"] == "naledi@example.test"
    assert "other@example.test" not in json.dumps(data)


def test_account_deletion_needs_the_password_and_removes_the_user(client):
    user = make_user()
    client.force_login(user)
    url = reverse("accounts:delete")
    client.post(url, {"password": "wrong-password-1", "confirm": "on"})
    assert User.objects.filter(pk=user.pk).exists()
    client.post(url, {"password": PASSWORD, "confirm": "on"})
    assert not User.objects.filter(pk=user.pk).exists()


# ----------------------------------------------------------------- headers, health, audit, configuration
def test_security_headers_and_no_store_for_signed_in_pages(client):
    landing = client.get(reverse("core:landing"))
    csp = landing["Content-Security-Policy"]
    assert "unsafe-inline" not in csp and "frame-ancestors 'none'" in csp
    assert landing["X-Frame-Options"] == "DENY"
    client.force_login(make_user())
    assert "no-store" in client.get(reverse("core:dashboard"))["Cache-Control"]


def test_health_endpoint_reveals_no_secrets(client):
    response = client.get(reverse("core:healthz"))
    assert response.status_code == 200
    assert set(response.json()) == {"status", "database"}
    assert django_settings.SECRET_KEY not in response.content.decode()


def test_audit_records_keep_only_allow_listed_metadata():
    record("example.action", metadata={"password": "hunter2", "token": "abc", "phone": "+27 00 000 0001", "state": "ok"})
    assert AuditEvent.objects.get(action="example.action").metadata == {"state": "ok"}


def _import_settings(env):
    """Import config.settings in a clean subprocess with exactly this environment."""
    clean = {"PATH": os.environ.get("PATH", ""), "PYTHON_DOTENV_DISABLED": "1", **env}
    return subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, '.'); import config.settings"],
        cwd=django_settings.BASE_DIR, env=clean, capture_output=True, text=True, timeout=60)


def test_production_refuses_to_start_without_a_secret_key():
    result = _import_settings({"DJANGO_DEBUG": "0"})
    assert result.returncode != 0 and "DJANGO_SECRET_KEY" in result.stderr


def test_production_refuses_to_start_without_an_evidence_encryption_key():
    result = _import_settings({"DJANGO_DEBUG": "0", "DJANGO_SECRET_KEY": "x" * 60})
    assert result.returncode != 0 and "EVIDENCE_ENCRYPTION_KEYS" in result.stderr
