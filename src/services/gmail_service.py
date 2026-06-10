import base64
import asyncio
from email.mime.text import MIMEText
from typing import Dict, Any, Optional, List
from src.services.google_auth import GoogleAuthService
from src.models.user import User
    
class GmailService:
    @staticmethod
    def _decode_body(payload: dict) -> str:
        """Recursively extract plain-text body from a Gmail message payload."""
        body = ""
        if payload.get("mimeType") == "text/plain" and "data" in payload.get("body", {}):
            body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8")
        for part in payload.get("parts", []):
            body += GmailService._decode_body(part)
        return body

    @staticmethod
    async def get_unread_emails(user: User, max_results: int = 10) -> List[Dict[str, Any]]:
        """Fetch recent unread emails for the daily briefing."""
        service = await GoogleAuthService.get_gmail_service(user)
        response = await asyncio.to_thread(
            lambda: service.users().messages().list(
                userId="me", q="is:unread", maxResults=max_results
            ).execute()
        )
        messages = response.get("messages", [])
        results = []
        for msg in messages:
            full = await asyncio.to_thread(
                lambda m=msg: service.users().messages().get(
                    userId="me", id=m["id"], format="full"
                ).execute()
            )
            headers = {h["name"]: h["value"] for h in full["payload"]["headers"]}
            body = GmailService._decode_body(full["payload"])
            results.append({
                "message_id": msg["id"],
                "subject": headers.get("Subject", "No Subject"),
                "sender": headers.get("From", "Unknown"),
                "date": headers.get("Date", ""),
                "snippet": full.get("snippet", ""),
                "body": body.strip()[:500]  # truncate for LLM context
            })
        return results

    @staticmethod
    async def search_emails_from_sender(user: User, sender_email: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """Find recent emails from a specific sender (for meeting prep)."""
        service = await GoogleAuthService.get_gmail_service(user)
        response = await asyncio.to_thread(
            lambda: service.users().messages().list(
                userId="me", q=f"from:{sender_email}", maxResults=max_results
            ).execute()   
        )
        messages = response.get("messages", [])
        results = []
        for msg in messages:
            full = await asyncio.to_thread(
                lambda m=msg: service.users().messages().get(
                    userId="me", id=m["id"], format="full"
                ).execute()
            )
            headers = {h["name"]: h["value"] for h in full["payload"]["headers"]}
            body = GmailService._decode_body(full["payload"])
            results.append({
                "subject": headers.get("Subject", "No Subject"),
                "date": headers.get("Date", ""),
                "snippet": full.get("snippet", ""),
                "body": body.strip()[:400]
            })
        return results

    @staticmethod
    async def send_email(user: User, to: str, subject: str, body: str) -> dict:
        """Send an email via the Gmail API."""
        service = await GoogleAuthService.get_gmail_service(user)
        mime = MIMEText(body)
        mime["to"] = to
        mime["subject"] = subject
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        result = await asyncio.to_thread(
            lambda: service.users().messages().send(
                userId="me", body={"raw": raw}
            ).execute()
        )
        return {"message_id": result.get("id"), "thread_id": result.get("threadId")}

    @staticmethod
    async def get_email_content(user: User, message_id: str) -> Optional[Dict[str, Any]]:
        service = await GoogleAuthService.get_gmail_service(user)
        
        message = await asyncio.to_thread(
            lambda: service.users().messages().get(
                userId="me", id=message_id, format="full"
            ).execute()
        )
        
        if not message:
            return None

        headers = {header['name']: header['value'] for header in message['payload']['headers']}
        body = GmailService._decode_body(message['payload'])

        return {
            "message_id": message_id,
            "subject": headers.get("Subject", "No Subject"),
            "sender": headers.get("From", "Unknown"),
            "date": headers.get("Date", ""),
            "body": body.strip()
        }