"""
A first taste of testing in Python with pytest.

Run it with:   pytest
(pytest automatically finds files named test_*.py and functions named test_*.)

This tests the /health endpoint, which needs no API key — so it passes immediately.
Testing the /chat endpoint properly means "mocking" the Claude call so tests don't cost
money or need the network; we'll add that when we build the evaluations node.
"""

from fastapi.testclient import TestClient

from main import app

# TestClient lets us call the app in-process, without starting a real server.
client = TestClient(app)


def test_health_returns_ok():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
