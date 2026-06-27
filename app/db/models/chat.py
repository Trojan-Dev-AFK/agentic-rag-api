"""Chat conversation and message ORM models for persisted history."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import relationship

from app.db.models.base import Base


class ChatConversation(Base):
    """A user-owned conversation thread scoped to a single company."""

    __tablename__ = "chat_conversations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    company_id = Column(String, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    messages = relationship("ChatMessage", back_populates="conversation", cascade="all, delete-orphan")


class ChatMessage(Base):
    """A single persisted Q/A turn in a conversation."""

    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(
        String, ForeignKey("chat_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_query = Column(Text, nullable=False)
    assistant_response = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    conversation = relationship("ChatConversation", back_populates="messages")
