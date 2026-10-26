"""Shared pytest fixtures.

Every test gets an empty cache, its own private evidence folder, and simulation-mode notifications, so nothing can
leak between tests and no test can ever send a real message."""
import pytest
from django.core.cache import cache


def pytest_configure(config):
    config.addinivalue_line("markers", "real_hashing: use the production password hasher (Argon2) for this test")


@pytest.fixture(autouse=True)
def _isolated(request, settings, tmp_path):
    cache.clear()
    settings.EVIDENCE_STORAGE_DIR = tmp_path / "vault"
    settings.LESEDI_NOTIFICATION_MODE = "simulation"
    if request.node.get_closest_marker("real_hashing") is None:
        # Argon2 is deliberately slow; use a fast hasher everywhere except the test that checks Argon2 is used.
        settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    yield
    cache.clear()
