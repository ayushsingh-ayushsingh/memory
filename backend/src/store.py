"""Postgres-backed conversation store (SQLAlchemy, async).

This is the system of record for conversations and messages. The backend owns
history here so a prompt only needs a ``conversation_id`` + the new text: the
full chat history never has to round-trip through the browser. Each user's rows
are isolated by ``user_id`` (the Better Auth ``sub`` from the verified JWT).

Everything is scoped by ``user_id``; every read filters on it so one user can
never see another user's rows.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://chat:chatpgpass@localhost:5432/chat_app",
)


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class ConversationRow(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), default="New chat")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    __table_args__ = (Index("ix_conversations_user", "user_id"),)


class MessageRow(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("ix_messages_conversation", "conversation_id"),
        Index("ix_messages_user", "user_id"),
    )


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _engine, _sessionmaker
    if _sessionmaker is None:
        _engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _sessionmaker


async def init_db() -> None:
    """Create tables if they do not exist. Safe to call repeatedly."""
    factory = _get_sessionmaker()
    async with _engine.begin() as conn:  # type: ignore[union-attr]
        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


def _new_id() -> str:
    return uuid.uuid4().hex


async def create_conversation(user_id: str, title: str = "New chat") -> dict[str, Any]:
    conv = ConversationRow(id=_new_id(), user_id=user_id, title=title[:180])
    async with _get_sessionmaker()() as session:
        session.add(conv)
        await session.commit()
        return {"id": conv.id, "title": conv.title, "updatedAt": conv.updated_at.isoformat()}


async def list_conversations(user_id: str) -> list[dict[str, Any]]:
    stmt = (
        select(ConversationRow)
        .where(ConversationRow.user_id == user_id)
        .order_by(ConversationRow.updated_at.desc())
    )
    async with _get_sessionmaker()() as session:
        rows = (await session.execute(stmt)).scalars().all()
        return [
            {
                "id": r.id,
                "title": r.title,
                "updatedAt": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rows
        ]


async def get_conversation(user_id: str, conversation_id: str) -> ConversationRow | None:
    stmt = select(ConversationRow).where(
        ConversationRow.id == conversation_id,
        ConversationRow.user_id == user_id,
    )
    async with _get_sessionmaker()() as session:
        return (await session.execute(stmt)).scalar_one_or_none()


async def rename_conversation(user_id: str, conversation_id: str, title: str) -> bool:
    async with _get_sessionmaker()() as session:
        stmt = select(ConversationRow).where(
            ConversationRow.id == conversation_id,
            ConversationRow.user_id == user_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return False
        row.title = title[:180]
        row.updated_at = _now()
        await session.commit()
        return True


async def touch_conversation(user_id: str, conversation_id: str) -> None:
    async with _get_sessionmaker()() as session:
        stmt = select(ConversationRow).where(
            ConversationRow.id == conversation_id,
            ConversationRow.user_id == user_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is not None:
            row.updated_at = _now()
            await session.commit()


async def add_message(
    user_id: str, conversation_id: str, role: str, content: str
) -> dict[str, Any]:
    msg = MessageRow(
        id=_new_id(),
        conversation_id=conversation_id,
        user_id=user_id,
        role=role,
        content=content,
    )
    async with _get_sessionmaker()() as session:
        session.add(msg)
        # bump the parent's updated_at so the sidebar sorts active chats first
        conv = await session.get(ConversationRow, conversation_id)
        if conv is not None and conv.user_id == user_id:
            conv.updated_at = _now()
        await session.commit()
        return {
            "id": msg.id,
            "role": role,
            "content": content,
            "createdAt": msg.created_at.isoformat() if msg.created_at else None,
        }


async def get_messages(
    user_id: str, conversation_id: str, limit: int | None = None
) -> list[dict[str, Any]]:
    stmt = (
        select(MessageRow)
        .where(
            MessageRow.conversation_id == conversation_id,
            MessageRow.user_id == user_id,
        )
        .order_by(MessageRow.created_at.asc())
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    async with _get_sessionmaker()() as session:
        rows = (await session.execute(stmt)).scalars().all()
        return [
            {
                "id": r.id,
                "role": r.role,
                "content": r.content,
                "createdAt": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


async def delete_conversation(user_id: str, conversation_id: str) -> bool:
    """Delete one conversation and its messages (FK cascade). Scoped to user."""
    async with _get_sessionmaker()() as session:
        stmt = select(ConversationRow).where(
            ConversationRow.id == conversation_id,
            ConversationRow.user_id == user_id,
        )
        row = (await session.execute(stmt)).scalar_one_or_none()
        if row is None:
            return False
        await session.delete(row)  # messages cascade
        await session.commit()
        return True


async def delete_all_user_data(user_id: str) -> dict[str, int]:
    """Delete every conversation and message for one user. Returns counts."""
    async with _get_sessionmaker()() as session:
        from sqlalchemy import delete as _delete

        result_msgs = await session.execute(
            _delete(MessageRow).where(MessageRow.user_id == user_id)
        )
        result_convs = await session.execute(
            _delete(ConversationRow).where(ConversationRow.user_id == user_id)
        )
        await session.commit()
        return {
            "messages": int(result_msgs.rowcount or 0),
            "conversations": int(result_convs.rowcount or 0),
        }


async def conversation_exists(user_id: str, conversation_id: str) -> bool:
    return await get_conversation(user_id, conversation_id) is not None
