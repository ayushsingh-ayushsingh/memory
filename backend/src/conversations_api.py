"""Conversation + account-data REST API (JWT-scoped).

Conversations and messages live in Postgres (see ``src.store``). Every route
here derives ``user_id`` from the verified Better Auth JWT ``sub`` and scopes
all reads/writes to it, so one user can never touch another user's rows.

Two flows the UI depends on:

- Delete a single chat — optionally also forget the facts the agent learned from
  that chat (``?forgetMemory=true``), wiping just that conversation's memory.
- Delete **all** of a user's data — every conversation, message, and everything
  the agent remembers about them, across Postgres, FalkorDB and Qdrant.

Neither flow deletes the Better Auth account itself.
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import store
from .auth import get_current_user
from .memory import wipe_conversation_memory, wipe_user_memory

logger = logging.getLogger(__name__)

router = APIRouter(tags=["conversations"])


def _user_id(user: dict[str, Any]) -> str:
    uid = str(user.get("sub", "")).strip()
    if not uid:
        raise HTTPException(status_code=401, detail="Missing user id in token")
    return uid


class RenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=180)


@router.get("/conversations")
async def list_conversations(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    rows = await store.list_conversations(_user_id(user))
    return {"conversations": rows}


@router.post("/conversations")
async def create_conversation(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    conv = await store.create_conversation(_user_id(user))
    return {"conversation": conv}


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    uid = _user_id(user)
    conv = await store.get_conversation(uid, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = await store.get_messages(uid, conversation_id)
    return {
        "conversation": {
            "id": conv.id,
            "title": conv.title,
            "updatedAt": conv.updated_at.isoformat() if conv.updated_at else None,
        },
        "messages": messages,
    }


@router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    uid = _user_id(user)
    conv = await store.get_conversation(uid, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    messages = await store.get_messages(uid, conversation_id)
    return {"messages": messages}


@router.patch("/conversations/{conversation_id}")
async def rename_conversation(
    conversation_id: str,
    body: RenameRequest,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
) -> dict[str, Any]:
    ok = await store.rename_conversation(_user_id(user), conversation_id, body.title)
    if not ok:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"ok": True}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    forget_memory: bool = False,
) -> dict[str, Any]:
    """Delete one chat. ``forget_memory=true`` also drops what was learned from it."""
    uid = _user_id(user)
    # Check ownership first so we never wipe memory for a foreign conversation.
    conv = await store.get_conversation(uid, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    forgotten = 0
    if forget_memory:
        try:
            report = await wipe_conversation_memory(uid, conversation_id)
            forgotten = int(report.get("edges_flagged", 0) or 0) if isinstance(report, dict) else 0
        except Exception:  # noqa: BLE001 — memory wipe must not block chat deletion
            logger.exception("memory wipe failed for conversation %s", conversation_id)

    deleted = await store.delete_conversation(uid, conversation_id)
    return {"ok": bool(deleted), "memoryFactsForgotten": forgotten}


class DeleteDataRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = Field(default=True, description="Must be true to proceed")


@router.post("/account/delete-data")
async def delete_all_data(
    user: Annotated[dict[str, Any], Depends(get_current_user)],
    body: DeleteDataRequest | None = None,
) -> dict[str, Any]:
    """Delete everything the app stores about this user (not the account)."""
    uid = _user_id(user)
    if body is not None and not body.confirm:
        raise HTTPException(status_code=400, detail="confirmation required")

    counts = await store.delete_all_user_data(uid)
    memory: dict[str, Any] = {}
    try:
        memory = await wipe_user_memory(uid)
    except Exception:  # noqa: BLE001 — still delete the chat data even if memory fails
        logger.exception("memory wipe failed for user %s", uid)
    return {"ok": True, "conversations": counts, "memory": memory}
