"""
fetch_sources · Pipeline 1 (daily-job-schedule) 機械抓取層

Fetches today's data from Google Calendar / Notion / GitHub and merges it
into one JSON artifact for the generate_note step.

啟用前環境設定（見 config/.env.template）：
- Google Calendar: GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_OAUTH_REFRESH_TOKEN
- Notion:          NOTION_INTEGRATION_TOKEN / NOTION_TASKS_DATABASE_ID
- GitHub:          GITHUB_TOKEN

Sources without credentials are reported as "not_configured" so the pipeline
still runs end-to-end in skeleton mode; a failing source is reported as
"error" and never aborts the whole fetch (the note step flags degraded
sources at the top of the daily note).
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

TIMEOUT = 30


def fetch_google_calendar(now: datetime) -> dict:
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")
    refresh_token = os.environ.get("GOOGLE_OAUTH_REFRESH_TOKEN")
    if not (client_id and client_secret and refresh_token):
        return {"status": "not_configured",
                "reason": "missing GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET/GOOGLE_OAUTH_REFRESH_TOKEN"}

    token_resp = requests.post(
        "https://oauth2.googleapis.com/token",
        data={"grant_type": "refresh_token", "refresh_token": refresh_token,
              "client_id": client_id, "client_secret": client_secret},
        timeout=TIMEOUT)
    token_resp.raise_for_status()
    access_token = token_resp.json()["access_token"]

    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    events_resp = requests.get(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
        params={"timeMin": day_start.isoformat(),
                "timeMax": (day_start + timedelta(days=1)).isoformat(),
                "singleEvents": "true", "orderBy": "startTime", "maxResults": 50},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=TIMEOUT)
    events_resp.raise_for_status()
    items = events_resp.json().get("items", [])
    return {
        "status": "ok",
        "count": len(items),
        "events": [{"summary": e.get("summary", ""),
                    "start": e.get("start", {}),
                    "end": e.get("end", {}),
                    "attendee_count": len(e.get("attendees", []))}
                   for e in items],
    }


def fetch_notion(now: datetime) -> dict:
    token = os.environ.get("NOTION_INTEGRATION_TOKEN")
    database_id = os.environ.get("NOTION_TASKS_DATABASE_ID")
    if not (token and database_id):
        return {"status": "not_configured",
                "reason": "missing NOTION_INTEGRATION_TOKEN/NOTION_TASKS_DATABASE_ID"}

    # TODO(啟用前確認): Notion Tasks 資料庫欄位命名（status/due date）——架構文件第九節。
    # v1 先取全量 open tasks，欄位確認後再補 server-side filter。
    resp = requests.post(
        f"https://api.notion.com/v1/databases/{database_id}/query",
        headers={"Authorization": f"Bearer {token}",
                 "Notion-Version": "2022-06-28",
                 "Content-Type": "application/json"},
        json={"page_size": 100},
        timeout=TIMEOUT)
    resp.raise_for_status()
    pages = resp.json().get("results", [])
    return {
        "status": "ok",
        "count": len(pages),
        "tasks": [{"id": p.get("id"), "properties": p.get("properties")} for p in pages],
    }


def fetch_github(now: datetime) -> dict:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return {"status": "not_configured", "reason": "missing GITHUB_TOKEN"}

    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/vnd.github+json",
               "User-Agent": "AI-Pipeline-Hook"}
    queries = {
        "assigned_issues": "is:issue is:open assignee:@me",
        "review_requested_prs": "is:pr is:open review-requested:@me",
    }
    result: dict = {"status": "ok"}
    for key, query in queries.items():
        resp = requests.get("https://api.github.com/search/issues",
                            params={"q": query, "per_page": 50},
                            headers=headers, timeout=TIMEOUT)
        resp.raise_for_status()
        payload = resp.json()
        items = payload.get("items", [])
        result[key] = {
            "total_count": payload.get("total_count", len(items)),
            "items": [{"number": it.get("number"), "title": it.get("title"),
                       "url": it.get("html_url"), "updated_at": it.get("updated_at")}
                      for it in items],
        }
    return result


FETCHERS = {
    "google-calendar": fetch_google_calendar,
    "notion": fetch_notion,
    "github": fetch_github,
}


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass

    parser = argparse.ArgumentParser(description="Fetch Pipeline 1 sources into one JSON artifact")
    parser.add_argument("--output", required=True, help="Path of the merged JSON artifact")
    args = parser.parse_args()

    now = datetime.now().astimezone()
    sources = {}
    for name, fetcher in FETCHERS.items():
        try:
            sources[name] = fetcher(now)
        except requests.RequestException as e:
            sources[name] = {"status": "error", "error": str(e)}
        except Exception as e:  # noqa: BLE001 — one bad source must not kill the fetch
            sources[name] = {"status": "error", "error": str(e)}

        entry = sources[name]
        detail = entry.get("reason") or entry.get("error") or f"{entry.get('count', 0)} items"
        print(f"  [{name}] {entry['status']} — {detail}")

    artifact = {
        "generated_at": now.isoformat(timespec="seconds"),
        "date": now.strftime("%Y-%m-%d"),
        "sources": sources,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  Saved: {output}")


if __name__ == "__main__":
    sys.exit(main())
