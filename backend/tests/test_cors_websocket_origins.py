import pytest
from starlette.websockets import WebSocketDisconnect
from fastapi.testclient import TestClient

from app.config import CORS_ORIGINS


FRONTEND_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


@pytest.mark.parametrize("origin", FRONTEND_ORIGINS)
def test_http_errors_and_preflight_include_credentialed_cors_headers(client, origin):
    for path in (
        "/api/reviews/999999",
        "/api/reviews/999999/activity",
    ):
        response = client.get(path, headers={"Origin": origin})
        assert response.status_code == 404
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["access-control-allow-credentials"] == "true"

    preflight = client.options(
        "/api/reviews/1",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == origin
    assert preflight.headers["access-control-allow-credentials"] == "true"


def test_cors_configuration_has_explicit_local_origins_without_wildcard():
    assert set(FRONTEND_ORIGINS).issubset(CORS_ORIGINS)
    assert "*" not in CORS_ORIGINS


@pytest.mark.parametrize("origin", FRONTEND_ORIGINS)
def test_websocket_accepts_both_local_origins_without_weakening_auth(
    client, origin
):
    review_id = client.post(
        "/api/analyze",
        json={"content": "Origin validation remains separate from session auth."},
    ).json()["id"]

    with client.websocket_connect(
        f"/api/reviews/{review_id}/collaboration",
        headers={"origin": origin},
    ) as socket:
        message = socket.receive_json()
        assert message["type"] == "presence"
        assert message["payload"]["review_id"] == review_id

    unauthenticated = TestClient(client.app)
    try:
        try:
            with unauthenticated.websocket_connect(
                f"/api/reviews/{review_id}/collaboration",
                headers={"origin": origin},
            ):
                pytest.fail("An unauthenticated WebSocket was accepted.")
        except WebSocketDisconnect as exc:
            assert exc.code == 4401
    finally:
        unauthenticated.close()


def test_websocket_rejects_unconfigured_origin(client):
    review_id = client.post(
        "/api/analyze",
        json={"content": "Untrusted browser origins remain blocked."},
    ).json()["id"]
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect(
            f"/api/reviews/{review_id}/collaboration",
            headers={"origin": "http://untrusted.example"},
        ):
            pytest.fail("An unconfigured WebSocket origin was accepted.")
    assert error.value.code == 4403
