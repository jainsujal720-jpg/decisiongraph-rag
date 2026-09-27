from fastapi.testclient import TestClient

from relayguard.api.main import app


def test_api_returns_auditable_fallback() -> None:
    response = TestClient(app).post(
        "/v1/chat/completions",
        json={
            "tenant_id": "acme",
            "user_id": "sujal",
            "prompt": "Summarize note",
            "simulate_primary_failure": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["fallback_used"] is True
