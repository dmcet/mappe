from fastapi.testclient import TestClient

from application_crew.config import get_settings


def test_health_and_index(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    from application_crew.web.app import app

    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        page = client.get("/")
        assert page.status_code == 200
        assert "New application" in page.text
    get_settings.cache_clear()
