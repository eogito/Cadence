from langgraph.graph import StateGraph, END
from langgraph.types import interrupt, Command
from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from src.workflows.state import AgentState, EmailAnalysis, EmailClassification
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


async def classify_email(state: AgentState) -> AgentState:
    """First pass: bucket the email into actionable / notification / promotion."""
    skip = _empty_body_classification(state)
    if skip is not None:
        print(f"Classifier: empty body -> promotion (no action).")
        return {"classification": skip}

    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        temperature=0,
        api_key=settings.groq_api_key.get_secret_value(),
    )
    structured_llm = llm.with_structured_output(EmailClassification, method="json_mode")

    system_msg = (
        "You are an email triage assistant. Classify the email into EXACTLY ONE category:\n"
        "- 'actionable': a person is communicating with the user and it may need a reply, a task, "
        "or scheduling (meeting requests, deadlines, calls, direct questions from real people).\n"
        "- 'notification': automated but relevant updates the user should see "
        "(LinkedIn messages, account/app notifications, system alerts).\n"
        "- 'promotion': marketing, promotions, newsletters, or pure confirmations/receipts "
        "(booking confirmations, order receipts) that need no action.\n\n"
        "Respond ONLY with valid JSON matching this schema:\n"
        '{{"category": "actionable|notification|promotion", "reason": "one short sentence"}}'
    )
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_msg),
        ("user", "Subject: {subject}\nFrom: {sender}\n\nBody:\n{body}"),
    ])
    chain = prompt | structured_llm

    print("Calling Groq API for email classification...")
    result = await chain.ainvoke({
        "subject": state.get("email_subject", ""),
        "sender": state.get("sender_email", ""),
        "body": state["email_content"][:2000],
    })
    print(f"Classifier: category={result.category} ({result.reason})")
    return {"classification": result.model_dump()}


# --- Nodes ---

async def extract_and_plan(state: AgentState) -> AgentState:
    """Uses LLM to extract tasks and propose calendar events from the email."""

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
        '  "needs_task": boolean,\n'
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
        "Set needs_task=true and populate tasks/events ONLY when there is a clear task AND a date "
        "(a deadline, meeting, or call with a time). Otherwise leave needs_task=false and tasks/events empty.\n"
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

async def notification_review(state: AgentState) -> AgentState:
    """Surface a notification and pause until the user dismisses it.

    The pause is one-way: the user resumes via POST /tasks/approve, and the
    resume value is intentionally ignored — acknowledging a notification has no
    variants (nothing to approve, reject, or modify), so it always ends here.
    """
    interrupt(state.get("classification", {}))  # resume value intentionally ignored
    return {"approval_status": "acknowledged"}

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

    analysis = state.get("analysis", {})

    # needs_task gates calendar/task creation: only act when the LLM flagged a
    # concrete task AND date. Otherwise there is nothing to schedule or persist.
    if not analysis.get("needs_task", True):
        print("Approved plan has needs_task=false — nothing to schedule or persist.")
        return state

    # 1. Fetch the user once (needed for both task persistence and calendar)
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == uuid.UUID(state['user_id'])))
        user = result.scalars().first()
        if not user:
            print("Error: User not found in DB.")
            return state

        # 2. Persist approved tasks to the DB (only happens on approval)
        from src.models.task import Task
        from datetime import datetime as _dt
        analysis_tasks = analysis.get("tasks", [])
        for t in analysis_tasks:
            due = None
            if t.get("due_date"):
                try:
                    due = _dt.fromisoformat(t["due_date"].replace("Z", "+00:00"))
                except Exception:
                    pass
            db.add(Task(
                user_id=user.id,
                email_id=state.get("email_id"),
                title=t.get("title", ""),
                description=t.get("description", ""),
                priority=t.get("priority", "medium"),
                due_date=due,
                urgency_score=analysis.get("urgency_score", 5),
            ))
        if analysis_tasks:
            await db.commit()
            print(f"Persisted {len(analysis_tasks)} approved task(s) to DB.")

    # 3. Create each proposed event via Google Calendar API
    events_to_schedule = analysis.get("events", [])
    if not events_to_schedule:
        print("No events to schedule.")
        return state

    for event in events_to_schedule:
        try:
            print(f"Scheduling: {event['summary']} from {event['start_time']} to {event['end_time']}")
            result = await CalendarService.create_event(
                user=user,
                summary=event['summary'],
                start_time=event['start_time'],
                end_time=event['end_time'],
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

    # Nodes
    workflow.add_node("classifier", classify_email)
    workflow.add_node("extractor", extract_and_plan)
    workflow.add_node("notification_review", notification_review)
    workflow.add_node("human_review", human_review)
    workflow.add_node("executor", execute_plan)

    # Entry: classify first
    workflow.set_entry_point("classifier")
    workflow.add_conditional_edges(
        "classifier",
        route_after_classification,
        {
            "extract": "extractor",
            "notify": "notification_review",
            END: END,
        },
    )

    # Notifications pause then end
    workflow.add_edge("notification_review", END)

    # Actionable: extract -> human review -> execute / re-plan / end
    workflow.add_edge("extractor", "human_review")
    workflow.add_conditional_edges(
        "human_review",
        route_after_human_review,
        {
            "execute": "executor",
            "re_plan": "extractor",
            END: END,
        },
    )
    workflow.add_edge("executor", END)

    return workflow.compile(checkpointer=checkpointer)
