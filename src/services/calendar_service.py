import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from src.services.google_auth import GoogleAuthService
from src.models.user import User

class CalendarService:
    @staticmethod
    async def get_upcoming_events(user: User, days_ahead: int = 7) -> List[Dict[str, Any]]:
        service = await GoogleAuthService.get_calendar_service(user)
        
        now = datetime.now(timezone.utc).isoformat()
        time_max = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).isoformat()

        events_result = await asyncio.to_thread(
            lambda: service.events().list(
                calendarId='primary', timeMin=now, timeMax=time_max,
                singleEvents=True, orderBy='startTime'
            ).execute()
        )
        
        events = events_result.get('items', [])
        return [
            {
                "id": event["id"],
                "summary": event.get("summary", "Busy"),
                "start": event["start"].get("dateTime", event["start"].get("date")),
                "end": event["end"].get("dateTime", event["end"].get("date"))
            } for event in events
        ]

    @staticmethod
    async def create_event(user: User, summary: str, start_time: str, end_time: str) -> dict:
        service = await GoogleAuthService.get_calendar_service(user)
        
        event = {
            'summary': summary,
            'start': {'dateTime': start_time, 'timeZone': 'UTC'},
            'end': {'dateTime': end_time, 'timeZone': 'UTC'},
        }

        created_event = await asyncio.to_thread(
            lambda: service.events().insert(calendarId='primary', body=event).execute()
        )
        return {"event_id": created_event.get('id'), "link": created_event.get('htmlLink')}                                                                                                                                                                                     