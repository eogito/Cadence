import uuid
from sqlalchemy import select
from langgraph.checkpoint.memory import MemorySaver
from src.database import AsyncSessionLocal
from src.models.user import User
from src.services.gmail_service import GmailService
from src.workflows.agent import build_agent_graph

# MemorySaver avoids psycopg3 Windows event loop deadlocks during local development
# Switch to AsyncPostgresSaver when deploying to production Linux servers
memory_checkpointer = MemorySaver()

async def process_new_email(email_address: str, message_id: str) -> str:
    """Fetches the email, starts the LangGraph workflow, and returns the thread_id."""
    
    # 1. Find user by email
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email_address))
        user = result.scalars().first()
        
        if not user:
            print(f"User {email_address} not found.")
            return

    # 2. Extract email content securely
    email_data = await GmailService.get_email_content(user, message_id)
    if not email_data:
        print("Could not fetch email content.")
        return

    # 3. Start LangGraph with in-memory checkpointer
    thread_id = str(uuid.uuid4())
    app = build_agent_graph(memory_checkpointer)
    config = {"configurable": {"thread_id": thread_id}}
    
    initial_state = {
        "user_id": str(user.id),
        "email_id": message_id,
        "email_content": email_data["body"],
        "sender_email": email_data.get("sender", ""),
        "email_subject": email_data.get("subject", "")
    }
    
    print(f"4. Triggering AI workflow {thread_id} for {email_address}...")
    await app.ainvoke(initial_state, config)
    print(f"5. Done! Workflow {thread_id} is at a stopping point.")
    print(f"   Fetch the result at: GET /tasks/pending/{thread_id}")
    return thread_id
