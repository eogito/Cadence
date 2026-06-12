import httpx
from typing import Any, Dict, List, Optional
from src.models.user import User
from src.models.email_preferences import VALID_CATEGORIES
from src.services.ms_auth import MicrosoftAuthService
from src.services.text_utils import html_to_text

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class OutlookMailService:
    # A $filter that matches no mail — used when the user tracks no classifications.
    NO_MAIL_FILTER = "id eq 'NONE'"

    @staticmethod
    def build_classification_filter(classes) -> str:
        """Graph $filter fragment for Focused/Other selection.

        - both selected -> "" (no classification filter)
        - one selected  -> inferenceClassification eq '<class>'
        - none selected -> NO_MAIL_FILTER (matches nothing)
        Unknown values are dropped.
        """
        valid = [c for c in classes if c in VALID_CATEGORIES]
        if not valid:
            return OutlookMailService.NO_MAIL_FILTER
        if set(valid) == set(VALID_CATEGORIES):
            return ""
        return f"inferenceClassification eq '{valid[0]}'"

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
    async def get_latest_message_id(user: User, classification=None) -> Optional[str]:
        params = {"$top": "1", "$orderby": "receivedDateTime desc", "$select": "id"}
        if classification is not None:
            filt = OutlookMailService.build_classification_filter(classification)
            if filt == OutlookMailService.NO_MAIL_FILTER:
                return None
            if filt:
                params["$filter"] = filt
        data = await OutlookMailService._graph_get(user, "/me/messages", params)
        items = data.get("value", [])
        return items[0]["id"] if items else None

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
        params = {
            "$filter": "isRead eq false",
            "$top": str(max_results),
            "$orderby": "receivedDateTime desc",
            "$select": "subject,from,bodyPreview,body,receivedDateTime",
        }
        if classification is not None:
            filt = OutlookMailService.build_classification_filter(classification)
            if filt == OutlookMailService.NO_MAIL_FILTER:
                return []
            if filt:
                params["$filter"] = f"isRead eq false and {filt}"
        data = await OutlookMailService._graph_get(user, "/me/messages", params)
        results = []
        for m in data.get("value", []):
            results.append({
                "message_id": m.get("id"),
                "subject": m.get("subject", "No Subject"),
                "sender": OutlookMailService._sender(m),
                "date": m.get("receivedDateTime", ""),
                "snippet": m.get("bodyPreview", ""),
                "body": OutlookMailService._body_text(m).strip()[:500],
            })
        return results
