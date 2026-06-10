
import json, base64
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel
from src.workflows.trigger import process_new_email

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

class PubSubMessage(BaseModel):
    data: str
    messageId: str
    publishTime: str

class PubSubRequest(BaseModel):
    message: PubSubMessage
    subscription: str

@router.post("/gmail")
async def gmail_push_notification(payload: PubSubRequest, background_tasks: BackgroundTasks):
    try:
        decoded_data = base64.b64decode(payload.message.data).decode('utf-8')
        event_data = json.loads(decoded_data)
        
        email_address = event_data.get("emailAddress")
        
        # When a webhook arrives, we should ideally query Google's History API 
        # using the historyId to find the newly added message_ids.
        # For MVP brevity, we assume the historyId represents the actual message ID, 
        # but in production, you must call service.users().history().list(...)
        message_id = str(event_data.get("historyId")) # MVP substitution
        
        if email_address and message_id:
            # Dispatch to background task so webhook responds 200 OK immediately
            background_tasks.add_task(process_new_email, email_address, message_id)

        return {"status": "ok"}
    except Exception as e:
        print(f"Webhook error: {e}")
        return {"status": "error"}