from langgraph.graph import StateGraph, END
from langgraph.types import interrupt, Command
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from src.workflows.state import AgentState, EmailAnalysis
from src.config import settings


def _empty_body_classification(state) -> dict | None:
    """If the email has no readable text, classify as promotion (no action) without an LLM call."""
    if not (state.get("email_content") or "").strip():
        return {"category": "promotion", "reason": "Email had no readable text content."}
    return None


def route_after_classification(state) -> str:
    """Route from the classifier: actionable -> extract, notification -> notify, else END."""
    category = (state.get("classification") or {}).get("category", "promotion")
    if category == "actionable":
        return "extract"
    if category == "notification":
        return "notify"
    return END


# --- Nodes ---

async def extract_and_plan(state: AgentState) -> AgentState:
    """Uses LLM to extract tasks and propose calendar events from the email."""

    # Guard: never ask the LLM to extract tasks from an empty body — it will
    # hallucinate. An email with no readable text is simply not actionable.
    if not (state.get("email_content") or "").strip():
        print("Email body empty after extraction — marking non-actionable, skipping LLM.")
        empty = EmailAnalysis(is_actionable=False, urgency_score=1)
        return {"analysis": empty.model_dump(), "approval_status": "pending"}

    feedback_context = f"\nUser Feedback on previous plan: {state.get('human_feedback')}" if state.get('human_feedback') else ""

    # Fetch contact memory context from DB
    contact_context = ""
    sender_raw = state.get("sender_email", "")
    if sender_raw:
        try:
            from src.database import AsyncSessionLocal
            from src.models.user import User
            from sqlalchemy import select
            from src.services.contact_service import get_contact_context
            import uuid as _uuid
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(User).where(User.id == _uuid.UUID(state["user_id"])))
                user = result.scalars().first()
                if user:
                    contact_context = await get_contact_context(db, user, sender_raw)
        except Exception as e:
            print(f"Contact context fetch failed (non-fatal): {e}")

    # Fetch personal rules/schedule from ChromaDB vector store
    personal_context = ""
    try:
        from src.services.user_context_service import query_relevant_context
        relevant = query_relevant_context(state["user_id"], state["email_content"][:500])
        if relevant:
            personal_context = "USER'S PERSONAL RULES & SCHEDULE:\n" + "\n".join(f"- {r}" for r in relevant)
    except Exception as e:
        print(f"Personal context fetch failed (non-fatal): {e}")

    json_schema = (
        '{{\n'
        '  "is_actionable": boolean,\n'
        '  "urgency_score": integer (1-10),\n'
        '  "tasks": [{{"title": string, "description": string, "priority": "low|medium|high", "due_date": "ISO8601 or empty string"}}],\n'
        '  "events": [{{"summary": string, "start_time": "ISO8601", "end_time": "ISO8601", "rationale": string}}],\n'
        '  "needs_reply": boolean,\n'
        '  "suggested_reply": string\n'
        '}}'
    )

    today_str = __import__("datetime").datetime.utcnow().strftime("%Y-%m-%d (UTC)")

    system_msg = (
        f"You are an AI executive assistant. Today is {today_str}.\n"
        "Extract actionable tasks and suggest calendar events from the user's email.\n"
        "For tasks, infer due dates from phrases like 'by Friday', 'EOD', 'next week' — use ISO 8601 UTC format.\n"
        "Rate urgency_score 1-10: 10=needs reply/action today, 1=newsletter/no action needed.\n"
        + (f"\nCONTACT CONTEXT:\n{contact_context}\n" if contact_context else "")
        + (f"\n{personal_context}\n" if personal_context else "")
        + feedback_context
        + "\n\nRespond ONLY with valid JSON matching this exact schema (arrays must be real JSON arrays, not strings):\n"
        + json_schema
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_msg),
        ("user", "Email Content:\n\n{email_content}")
    ])

    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        temperature=0,
        api_key=settings.groq_api_key.get_secret_value()
    )
    structured_llm = llm.with_structured_output(EmailAnalysis, method="json_mode")
    chain = prompt | structured_llm

    try:
        print("Calling Groq API for email analysis...")
        analysis = await chain.ainvoke({"email_content": state["email_content"]})
        print(f"Groq response received: urgency={analysis.urgency_score}, tasks={len(analysis.tasks)}, events={len(analysis.events)}")

        # Persist tasks to DB
        try:
            from src.database import AsyncSessionLocal
            from src.models.user import User
            from src.models.task import Task
            from sqlalchemy import select
            import uuid as _uuid
            from datetime import datetime, timezone
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(User).where(User.id == _uuid.UUID(state["user_id"])))
                user = result.scalars().first()
                if user:
                    for t in analysis.tasks:
                        due = None
                        if t.due_date:
                            try:
                                due = datetime.fromisoformat(t.due_date.replace("Z", "+00:00"))
                            except Exception:
                                pass
                        db.add(Task(
                            user_id=user.id,
                            email_id=state.get("email_id"),
                            title=t.title,
                            description=t.description,
                            priority=t.priority,
                            due_date=due,
                            urgency_score=analysis.urgency_score
                        ))
                    await db.commit()
                    print(f"Saved {len(analysis.tasks)} task(s) to DB.")
        except Exception as e:
            print(f"Task persistence failed (non-fatal): {e}")

        # Update contact memory in background (fire-and-forget)
        if sender_raw:
            try:
                from src.database import AsyncSessionLocal
                from src.models.user import User
                from sqlalchemy import select
                from src.services.contact_service import update_contact_memory, get_contact_context
                import uuid as _uuid
                async with AsyncSessionLocal() as db:
                    result = await db.execute(select(User).where(User.id == _uuid.UUID(state["user_id"])))
                    user = result.scalars().first()
                    if user:
                        existing = await get_contact_context(db, user, sender_raw)
                        await update_contact_memory(
                            db, user, sender_raw,
                            email_subject=state.get("email_subject", ""),
                            email_snippet=state["email_content"][:300],
                            existing_summary=existing
                        )
                        print(f"Contact memory updated for {sender_raw}.")
            except Exception as e:
                print(f"Contact memory update failed (non-fatal): {e}")

        return {"analysis": analysis.model_dump(), "approval_status": "pending"}
    except Exception as e:
        print(f"ERROR in extract_and_plan: {type(e).__name__}: {e}")
        raise

async def human_review(state: AgentState) -> AgentState:
    """Pause here and wait for the human to approve, reject, or modify the plan."""
    decision = interrupt(state.get("analysis", {}))
    return {
        "approval_status": decision.get("action", "rejected"),
        "human_feedback": decision.get("feedback", "")
    }

async def execute_plan(state: AgentState) -> AgentState:
    """Executes the approved plan by calling Google Calendar API."""
    from src.database import AsyncSessionLocal
    from src.models.user import User
    from sqlalchemy import select
    from src.services.calendar_service import CalendarService
    import uuid

    print(f"Executing approved plan for user {state['user_id']}!")
    
    # 1. Ensure there are events to schedule
    analysis = state.get("analysis", {})
    events_to_schedule = analysis.get("events", [])
    
    if not events_to_schedule:
        print("No events detected to schedule.")
        return state

    # 2. Fetch User to get OAuth Tokens
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == uuid.UUID(state['user_id'])))
        user = result.scalars().first()
        
        if not user:
            print("Error: User not found in DB.")
            return state

    # 3. Create each event via Google Calendar API
    for event in events_to_schedule:
        try:
            print(f"Scheduling: {event['summary']} from {event['start_time']} to {event['end_time']}")
            result = await CalendarService.create_event(
                user=user,
                summary=event['summary'],
                start_time=event['start_time'],
                end_time=event['end_time']
            )
            print(f"Success! Event link: {result['link']}")
        except Exception as e:
            print(f"Failed to schedule event {event['summary']}. Error: {e}")

    return state

# --- Routing Logic ---

def route_after_human_review(state: AgentState) -> str:
    """Routes after the human makes a decision."""
    status = state.get("approval_status")
    if status == "approved":
        return "execute"
    elif status == "modified":
        return "re_plan"
    return END  # rejected or anything else

# --- Build the Graph ---

def build_agent_graph(checkpointer=None):
    workflow = StateGraph(AgentState)

    # Add Nodes
    workflow.add_node("planner", extract_and_plan)
    workflow.add_node("human_review", human_review)
    workflow.add_node("executor", execute_plan)

    # Define Edges: planner → human_review (pauses) → conditional → executor or END
    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "human_review")
    workflow.add_conditional_edges(
        "human_review",
        route_after_human_review,
        {
            "execute": "executor",
            "re_plan": "planner",
            END: END
        }
    )
    workflow.add_edge("executor", END)

    # interrupt() inside human_review handles pausing — no interrupt_before needed
    return workflow.compile(checkpointer=checkpointer)