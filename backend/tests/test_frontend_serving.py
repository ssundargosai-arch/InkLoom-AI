from fastapi.testclient import TestClient

from app.main import create_app


def test_frontend_serves_assets_and_spa_routes_without_intercepting_api(
    test_engine, tmp_path
):
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    (tmp_path / "index.html").write_text(
        "<!doctype html><title>InkLoom test app</title>", encoding="utf-8"
    )
    (assets_dir / "app.js").write_text(
        "window.inkloomReady = true;", encoding="utf-8"
    )
    app = create_app(test_engine, frontend_static_dir=tmp_path)

    with TestClient(app) as client:
        assert "InkLoom test app" in client.get("/").text
        assert "InkLoom test app" in client.get("/reviews/123").text
        assert client.get("/assets/app.js").text == "window.inkloomReady = true;"

        missing_api = client.get("/api/not-a-route")
        assert missing_api.status_code == 404
        assert missing_api.json() == {"detail": "Not Found"}

        missing_asset = client.get("/assets/missing.js")
        assert missing_asset.status_code == 404
        assert "InkLoom test app" not in missing_asset.text


def test_frontend_fallback_does_not_serve_reserved_endpoints(test_engine, tmp_path):
    (tmp_path / "index.html").write_text(
        "<!doctype html><title>InkLoom test app</title>", encoding="utf-8"
    )
    app = create_app(test_engine, frontend_static_dir=tmp_path)

    with TestClient(app) as client:
        for path in ("/api", "/health", "/docs/unknown", "/openapi.json/unknown"):
            response = client.get(path)
            assert response.status_code == 404
            assert "InkLoom test app" not in response.text
