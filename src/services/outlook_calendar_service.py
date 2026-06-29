import httpx
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List
from src.models.user import User
from src.services.ms_auth import MicrosoftAuthService
from src.services.calendar_dates import user_tz

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class OutlookCalendarService:
    @staticmethod
    async def _graph_request(user: User, method: str, path: str, params: dict = None, json_body: dict = None, extra_headers: dict = None) -> dict:
        token = await MicrosoftAuthService.get_access_token(user)
        headers = {"Authorization": f"Bearer {token}"}
        if extra_headers:
            headers.update(extra_headers)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(method, f"{GRAPH_BASE}{path}", headers=headers, params=params, json=json_body)
        if resp.status_code >= 400:
            raise RuntimeError(f"Graph error {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else {}

    @staticmethod
    def _event_body(summary: str, start_time: str, end_time: str, tz: str = "UTC") -> dict:
        return {
            "subject": summary,
            "start": {"dateTime": start_time.rstrip("Z"), "timeZone": tz},
            "end": {"dateTime": end_time.rstrip("Z"), "timeZone": tz},
        }

    @staticmethod
    async def get_events_in_range(user: User, start_iso: str, end_iso: str):
        params = {
            "startDateTime": start_iso,
            "endDateTime": end_iso,
            "$orderby": "start/dateTime",
            "$select": "subject,start,end,attendees",
            "$top": "200",
        }
        data = await OutlookCalendarService._graph_request(
            user, "GET", "/me/calendarView", params=params,
            extra_headers={"Prefer": 'outlook.timezone="UTC"'},
        )
        events = []
        for e in data.get("value", []):
            attendees = [
                (a.get("emailAddress", {}) or {}).get("address", "")
                for a in e.get("attendees", [])
            ]
            events.append({
                "id": e.get("id"),
                "summary": e.get("subject", "Busy"),
                "start": (e.get("start", {}) or {}).get("dateTime", ""),
                "end": (e.get("end", {}) or {}).get("dateTime", ""),
                "attendees": [a for a in attendees if a],
            })
        return events

    @staticmethod
    async def get_upcoming_events(user: User, days_ahead: int = 7):
        now = datetime.now(timezone.utc)
        return await OutlookCalendarService.get_events_in_range(
            user, now.isoformat(), (now + timedelta(days=days_ahead)).isoformat()
        )

    @staticmethod
    async def create_event(user: User, summary: str, start_time: str, end_time: str) -> dict:
        data = await OutlookCalendarService._graph_request(
            user, "POST", "/me/events",
            json_body=OutlookCalendarService._event_body(summary, start_time, end_time, user_tz(user)),
        )
        return {"event_id": data.get("id"), "link": data.get("webLink")}
