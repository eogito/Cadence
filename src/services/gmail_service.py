import base64
import asyncio
from html.parser import HTMLParser
from email.mime.text import MIMEText
from typing import Dict, Any, Optional, List, Tuple
from src.services.google_auth import GoogleAuthService
from src.models.user import User


class _HTMLTextExtractor(HTMLParser):
    """Strips tags from an HTML email, dropping <script>/<style> contents."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._chunks: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip_depth += 1
        elif tag in ("br", "p", "div", "tr", "li"):
            self._chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            self._chunks.append(data)

    def get_text(self) -> str:
        return "".join(self._chunks)


class GmailService:
    @staticmethod
    def _html_to_text(html: str) -> str:
        """Convert an HTML email body to readable plain text using only the stdlib."""
        parser = _HTMLTextExtractor()
        try:
            parser.feed(html)
        except Exception:
            # Malformed HTML shouldn't crash extraction; return whatever was parsed.
            pass
        lines = [ln.strip() for ln in parser.get_text().splitlines()]
        return "\n".join(ln for ln in lines if ln)

    @staticmethod
    def _collect_parts(payload: dict) -> Tuple[str, str]:
        """Recursively gather decoded text/plain and text/html content separately."""
        plain, html = "", ""
        data = payload.get("body", {}).get("data")
        if data:
            mime = payload.get("mimeType", "")
            if mime == "text/plain":
                plain += base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            elif mime == "text/html":
                html += base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        for part in payload.get("parts", []):
            p, h = GmailService._collect_parts(part)
            plain += p
            html += h
        return plain, html

    @staticmethod
    def _decode_body(payload: dict) -> str:
        """Extract a readable body from a Gmail payload.

        Prefers text/plain, but falls back to stripped text/html so that
        HTML-only emails (newsletters, promos, news) aren't returned empty.
        """
        plain, html = GmailService._collect_parts(payload)
        if plain.strip():
            return plain
        if html.strip():
            return GmailService._html_to_text(html)
        return ""

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