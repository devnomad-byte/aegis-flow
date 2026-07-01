from backend.app.main import create_app
from fastapi.testclient import TestClient


def test_live_health_endpoint_returns_service_status() -> None:
    client = TestClient(create_app())

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "aegis-flow-api",
        "version": "0.1.0",
    }


def test_ready_health_endpoint_returns_service_status() -> None:
    client = TestClient(create_app())

    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
