"""Tests for the /health endpoint and basic error handling."""

from fastapi.testclient import TestClient


def test_health_returns_200(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200


def test_health_response_shape(client: TestClient) -> None:
    response = client.get("/health")
    body = response.json()
    assert body["status"] == "ok"
    assert "timestamp" in body
    assert "app_name" in body
    assert body["version"] == "0.1.0"


def test_health_sets_request_id_header(client: TestClient) -> None:
    response = client.get("/health")
    assert "x-request-id" in response.headers


def test_unknown_route_returns_json_404(client: TestClient) -> None:
    response = client.get("/this-route-does-not-exist")
    assert response.status_code == 404
    assert "error" in response.json()
