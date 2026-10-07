"""Tests for scripts/fetch_sources.py (degradation and mocked fetchers)."""
import importlib.util
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location(
    "fetch_sources", REPO_ROOT / "scripts" / "fetch_sources.py")
fetch_sources = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch_sources)

ALL_ENV_VARS = [
    "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN",
    "NOTION_INTEGRATION_TOKEN", "NOTION_TASKS_DATABASE_ID",
    "GITHUB_TOKEN",
]


def clear_all_credentials(monkeypatch):
    for var in ALL_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def fake_response(payload):
    return SimpleNamespace(json=lambda: payload, raise_for_status=lambda: None)


class TestSkeletonMode:
    def test_no_credentials_all_not_configured(self, tmp_path, monkeypatch):
        clear_all_credentials(monkeypatch)
        output = tmp_path / "fetch.json"

        fetch_sources.main(["--output", str(output)])

        artifact = json.loads(output.read_text(encoding="utf-8"))
        assert set(artifact["sources"]) == {"google-calendar", "notion", "github"}
        assert all(s["status"] == "not_configured" for s in artifact["sources"].values())
        assert artifact["date"] == datetime.now().strftime("%Y-%m-%d")


class TestMockedFetchers:
    def test_google_calendar(self, monkeypatch):
        for var in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_OAUTH_REFRESH_TOKEN"):
            monkeypatch.setenv(var, "x")
        monkeypatch.setattr(fetch_sources.requests, "post",
                            lambda url, **kw: fake_response({"access_token": "tok"}))
        monkeypatch.setattr(fetch_sources.requests, "get",
                            lambda url, **kw: fake_response(
                                {"items": [{"summary": "standup"}]}))

        result = fetch_sources.fetch_google_calendar(datetime(2026, 10, 7, 9, 0))
        assert result["status"] == "ok"
        assert result["count"] == 1
        assert result["events"][0]["summary"] == "standup"

    def test_notion(self, monkeypatch):
        monkeypatch.setenv("NOTION_INTEGRATION_TOKEN", "x")
        monkeypatch.setenv("NOTION_TASKS_DATABASE_ID", "db")
        monkeypatch.setattr(fetch_sources.requests, "post",
                            lambda url, **kw: fake_response(
                                {"results": [{"id": "page-1", "properties": {}}]}))

        result = fetch_sources.fetch_notion(datetime(2026, 10, 7, 9, 0))
        assert result["status"] == "ok"
        assert result["tasks"][0]["id"] == "page-1"

    def test_github(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "x")
        monkeypatch.setattr(fetch_sources.requests, "get",
                            lambda url, **kw: fake_response(
                                {"total_count": 1, "items": [{"number": 3,
                                                              "title": "fix",
                                                              "html_url": "u"}]}))

        result = fetch_sources.fetch_github(datetime(2026, 10, 7, 9, 0))
        assert result["status"] == "ok"
        assert result["assigned_issues"]["total_count"] == 1
        assert result["review_requested_prs"]["items"][0]["number"] == 3

    def test_error_source_does_not_abort_fetch(self, tmp_path, monkeypatch):
        clear_all_credentials(monkeypatch)

        def boom(now):
            raise fetch_sources.requests.HTTPError("boom")

        monkeypatch.setattr(fetch_sources, "FETCHERS", {
            "a": boom, "b": lambda now: {"status": "ok"}})
        output = tmp_path / "fetch.json"

        fetch_sources.main(["--output", str(output)])

        artifact = json.loads(output.read_text(encoding="utf-8"))
        assert artifact["sources"]["a"]["status"] == "error"
        assert artifact["sources"]["b"]["status"] == "ok"


class TestCredentialDetection:
    def test_partial_credentials_reported_per_source(self, monkeypatch):
        clear_all_credentials(monkeypatch)

        result = fetch_sources.fetch_notion(datetime(2026, 10, 7, 9, 0))
        assert result["status"] == "not_configured"
        assert "NOTION_INTEGRATION_TOKEN" in result["reason"]

        result = fetch_sources.fetch_google_calendar(datetime(2026, 10, 7, 9, 0))
        assert result["status"] == "not_configured"
