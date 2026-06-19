import httpx
from typing import Any, Dict, List, Optional
from src.models.user import User
from src.models.email_preferences import VALID_CATEGORIES
from src.services.ms_auth import MicrosoftAuthService
from src.services.text_utils import html_to_text
from src.services.calendar_dates import parse_graph_dt

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class OutlookMailService:
    @staticmethod
    def _allowed_classifications(classes):
        """Which inferenceClassification values to keep, decided client-side.

        Returns None to keep all (both selected), an empty set to keep none
        (nothing selected), or the set of selected values. Filtering is done in
        Python because Graph rejects a $filter on inferenceClassification combined
        with an $orderby on receivedDateTime (error: InefficientFilter). Unknown
        values are dropped.
        """
        valid = [c for c in classes if c in VALID_CATEGORIES]
        if not valid:
            return set()
        if set(valid) == set(VALID_CATEGORIES):
            return None
        return set(valid)

    @staticmethod
    async def _graph_post(user: User, path: str, json_body: dict) -> dict:
        token = await MicrosoftAuthService.get_access_token(user)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{GRAPH_BASE}{path}",
                headers={"Authorization": f"Bearer {token}"},
                json=json_body,
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Graph error {resp.status_code}: {resp.text[:300]}")
        return resp.json() if resp.content else {}

    @staticmethod
    async def _graph_get(user: User, path: str, params: dict) -> dict:
        token = await MicrosoftAuthService.get_access_token(user)
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{GRAPH_BASE}{path}",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"Graph error {resp.status_code}: {resp.text[:300]}")
        return resp.json()

    @staticmethod
    def _body_text(message: dict) -> str:
        body = message.get("body", {})
        content = body.get("content", "") or ""
        if body.get("contentType", "").lower() == "html":
            return html_to_text(content)
        return content

    @staticmethod
    def _sender(message: dict) -> str:
        return (message.get("from", {}) or {}).get("emailAddress", {}).get("address", "Unknown")

    @staticmethod
    def _in_received_range(messages, start_iso: str, end_iso: str):
        start, end = parse_graph_dt(start_iso), parse_graph_dt(end_iso)
        out = []
        for m in messages:
            r = parse_graph_dt(m.get("receivedDateTime", ""))
            if r is not None and start <= r < end:
                out.append(m)
        return out

    @staticmethod
    async def get_messages_in_range(user: User, start_iso: str, end_iso: str,
                                    unread_only: bool = False, max_fetch: int = 80):
        """Messages received within [start, end). Filtered client-side to avoid Graph's
        $filter + $orderby restriction."""
        params = {
            "$top": str(max_fetch),
            "$orderby": "receivedDateTime desc",
            "$select": "subject,from,bodyPreview,receivedDateTime,isRead",
        }
        data = await OutlookMailService._graph_get(user, "/me/messages", params)
        msgs = data.get("value", [])
        if unread_only:
            msgs = [m for m in msgs if not m.get("isRead", True)]
        msgs = OutlookMailService._in_received_range(msgs, start_iso, end_iso)
        return [{
            "message_id": m.get("id"),
            "subject": m.get("subject", "No Subject"),
            "sender": OutlookMailService._sender(m),
            "snippet": m.get("bodyPreview", ""),
            "date": m.get("receivedDateTime", ""),
        } for m in msgs]

    @staticmethod
    async def get_latest_message_id(user: User, classification=None) -> Optional[str]:
        allowed = None
        if classification is not None:
            allowed = OutlookMailService._allowed_classifications(classification)
            if allowed is not None and not allowed:
                return None  # user tracks no sections
        # Order by date only (no inferenceClassification $filter); match client-side.
        params = {"$top": "25", "$orderby": "receivedDateTime desc", "$select": "id,inferenceClassification"}
        data = await OutlookMailService._graph_get(user, "/me/messages", params)
        for m in data.get("value", []):
            if allowed is None or m.get("inferenceClassification") in allowed:
                return m.get("id")
        return None

    @staticmethod
    async def get_email_content(user: User, message_id: str) -> Optional[Dict[str, Any]]:
        params = {"$select": "subject,from,body,receivedDateTime"}
        message = await OutlookMailService._graph_get(user, f"/me/messages/{message_id}", params)
        if not message:
            return None
        return {
            "message_id": message_id,
            "subject": message.get("subject", "No Subject"),
            "sender": OutlookMailService._sender(message),
            "date": message.get("receivedDateTime", ""),
            "body": OutlookMailService._body_text(message).strip(),
        }

    @staticmethod
    def _sendmail_payload(to: str, subject: str, body: str) -> dict:
        return {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": to}}],
            },
            "saveToSentItems": True,
        }

    @staticmethod
    async def send_email(user: User, to: str, subject: str, body: str) -> dict:
        await OutlookMailService._graph_post(user, "/me/sendMail", OutlookMailService._sendmail_payload(to, subject, body))
        return {"status": "sent"}

    @staticmethod
    async def search_emails_from_sender(user: User, sender_email: str, max_results: int = 5):
        # No $orderby here: Graph rejects $filter + $orderby on different properties.
        params = {
            "$filter": f"from/emailAddress/address eq '{sender_email}'",
            "$top": str(max_results),
            "$select": "subject,bodyPreview,receivedDateTime",
        }
        data = await OutlookMailService._graph_get(user, "/me/messages", params)
        return [
            {
                "subject": m.get("subject", "No Subject"),
                "date": m.get("receivedDateTime", ""),
                "snippet": m.get("bodyPreview", ""),
            }
            for m in data.get("value", [])
        ]

    @staticmethod
    async def get_unread_emails(user: User, max_results: int = 10, classification=None) -> List[Dict[str, Any]]:
        allowed = None
        if classification is not None:
            allowed = OutlookMailService._allowed_classifications(classification)
            if allowed is not None and not allowed:
                return []  # user tracks no sections
        # isRead filter is fine with the date orderby; classification is matched client-side.
        fetch_n = max_results if allowed is None else max(max_results * 3, 30)
        params = {
            "$filter": "isRead eq false",
            "$top": str(fetch_n),
            "$orderby": "receivedDateTime desc",
            "$select": "subject,from,bodyPreview,body,receivedDateTime,inferenceClassification",
        }
        data = await OutlookMailService._graph_get(user, "/me/messages", params)
        results = []
        for m in data.get("value", []):
            if allowed is not None and m.get("inferenceClassification") not in allowed:
                continue
            results.append({
                "message_id": m.get("id"),
                "subject": m.get("subject", "No Subject"),
                "sender": OutlookMailService._sender(m),
                "date": m.get("receivedDateTime", ""),
                "snippet": m.get("bodyPreview", ""),
                "body": OutlookMailService._body_text(m).strip()[:500],
            })
            if len(results) >= max_results:
                break
        return results
