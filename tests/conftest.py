"""Shared pytest fixtures for the whole test suite."""

import pytest
from fastapi.testclient import TestClient

from scout.api.app import create_app
from scout.database.initialize import initialize_database
from scout.database.seed import seed_database


@pytest.fixture()
def client() -> TestClient:
    """A TestClient wrapping a freshly-built app instance."""
    app = create_app()
    return TestClient(app)


@pytest.fixture()
def seeded_db_path(tmp_path) -> str:
    """Path to a freshly initialized and seeded temporary database.

    Shared by the database and repository test modules so every test
    that needs real seeded data uses the exact same setup, and none of
    them ever read or write the development database.
    """
    db_path = str(tmp_path / "scout_test.db")
    initialize_database(db_path)
    seed_database(db_path)
    return db_path


@pytest.fixture(autouse=True)
def _default_tests_to_rule_based_supervisor(monkeypatch):
    """Keep tests deterministic; production/default Settings remain Ollama-backed."""
    monkeypatch.setenv("SUPERVISOR_POLICY", "rule_based")
    monkeypatch.setenv("PAYMENT_PROVIDER", "mock")
