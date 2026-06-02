"""
会话线程模型 — 保存检索结果，支持多轮追问跳过重复检索。
"""

import uuid
from datetime import datetime

from sqlalchemy import String, Text, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from server.database import Base


class ConversationThread(Base):
    __tablename__ = "conversation_threads"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=True)
    contract_type: Mapped[str] = mapped_column(String(20), nullable=True)
    branches: Mapped[str] = mapped_column(Text, nullable=True)  # JSON list
    retrieval_result: Mapped[str] = mapped_column(Text, nullable=True)  # JSON dict
    file_name: Mapped[str] = mapped_column(String(200), nullable=True)
    input_text: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
