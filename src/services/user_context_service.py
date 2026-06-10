"""
User Context Service — ChromaDB vector store for personal rules, schedules, and preferences.

Stores things like:
  - "I have CS101 every Monday and Wednesday 9-11am"
  - "Final exam is June 20"
  - "Every day at 4PM I want to send 5 cold emails"
  - "I prefer morning meetings before noon"

When the AI processes an email, it queries this store for relevant context
so it can avoid scheduling conflicts and respect personal preferences.
"""

import os
import chromadb
from chromadb.config import Settings
from typing import List, Dict, Any

# Store the ChromaDB data in the project folder so it persists across restarts
CHROMA_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "chroma")

_client = None

def _get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        os.makedirs(CHROMA_PATH, exist_ok=True)
        _client = chromadb.PersistentClient(path=CHROMA_PATH)
    return _client


def _get_collection(user_id: str):
    """Each user gets their own ChromaDB collection."""
    client = _get_client()
    # Collection names must be alphanumeric + underscores
    safe_id = "user_" + str(user_id).replace("-", "_")
    return client.get_or_create_collection(name=safe_id)


def add_context(user_id: str, text: str, category: str, item_id: str = None) -> str:
    """
    Add a personal rule, schedule entry, or preference.

    Args:
        user_id: The user's UUID string
        text: Natural language description e.g. "CS101 every Monday 9-11am"
        category: One of: schedule, important_date, recurring_rule, preference
        item_id: Optional stable ID for updates (auto-generated if not provided)

    Returns:
        The item_id used
    """
    import uuid
    if not item_id:
        item_id = str(uuid.uuid4())

    collection = _get_collection(user_id)
    collection.upsert(
        ids=[item_id],
        documents=[text],
        metadatas=[{"category": category, "text": text}]
    )
    return item_id


def query_relevant_context(user_id: str, query: str, n_results: int = 5) -> List[str]:
    """
    Semantic search: given an email topic/content, find relevant user rules.
    e.g. "schedule a meeting on Monday morning" → returns "CS101 every Monday 9-11am"
    """
    collection = _get_collection(user_id)
    count = collection.count()
    if count == 0:
        return []

    results = collection.query(
        query_texts=[query],
        n_results=min(n_results, count)
    )
    return results["documents"][0] if results["documents"] else []


def list_all_context(user_id: str) -> List[Dict[str, Any]]:
    """Return all stored context items for a user."""
    collection = _get_collection(user_id)
    if collection.count() == 0:
        return []

    results = collection.get(include=["documents", "metadatas"])
    items = []
    for i, doc_id in enumerate(results["ids"]):
        items.append({
            "id": doc_id,
            "text": results["documents"][i],
            "category": results["metadatas"][i].get("category", "other")
        })
    return items


def delete_context(user_id: str, item_id: str) -> None:
    """Delete a specific context item."""
    collection = _get_collection(user_id)
    collection.delete(ids=[item_id])


# ── PostgreSQL sync ────────────────────────────────────────────────────────────

async def rebuild_chroma_from_db() -> None:
    """
    Called on server startup: reads all UserContext rows from PostgreSQL and
    re-populates ChromaDB so semantic search is always in sync with the DB.
    """
    from sqlalchemy import select
    from src.database import AsyncSessionLocal
    from src.models.user_context import UserContext  # noqa: avoid circular at module level

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(UserContext))
        rows = result.scalars().all()

    for row in rows:
        collection = _get_collection(str(row.user_id))
        collection.upsert(
            ids=[row.item_id],
            documents=[row.text],
            metadatas=[{"category": row.category, "text": row.text}]
        )
