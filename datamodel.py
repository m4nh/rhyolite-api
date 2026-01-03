from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)
from sqlalchemy import create_engine


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Kind(Base):
    __tablename__ = "kinds"

    name: Mapped[str] = mapped_column(String, primary_key=True)
    schema: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)

    nodes: Mapped[List["Node"]] = relationship(back_populates="kind_rel")


class Node(Base):
    __tablename__ = "nodes"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    kind: Mapped[str] = mapped_column(
        String, ForeignKey("kinds.name", ondelete="RESTRICT"), nullable=False
    )
    payload: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    kind_rel: Mapped[Kind] = relationship(back_populates="nodes")
    outgoing_edges: Mapped[List["Edge"]] = relationship(
        foreign_keys="Edge.from_id",
        back_populates="from_node",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    incoming_edges: Mapped[List["Edge"]] = relationship(
        foreign_keys="Edge.to_id",
        back_populates="to_node",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    attachments: Mapped[List["Attachment"]] = relationship(
        back_populates="node",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (Index("ix_nodes_kind", "kind"),)


class EdgesKind(Base):
    __tablename__ = "edges_kinds"

    from_kind: Mapped[str] = mapped_column(
        String,
        ForeignKey("kinds.name", ondelete="CASCADE"),
        primary_key=True,
    )
    to_kind: Mapped[str] = mapped_column(
        String,
        ForeignKey("kinds.name", ondelete="CASCADE"),
        primary_key=True,
    )
    relation: Mapped[str] = mapped_column(String, primary_key=True)


class Edge(Base):
    __tablename__ = "edges"

    from_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    to_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        primary_key=True,
    )
    relation: Mapped[str] = mapped_column(String, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    from_node: Mapped[Node] = relationship(
        foreign_keys=[from_id], back_populates="outgoing_edges"
    )
    to_node: Mapped[Node] = relationship(
        foreign_keys=[to_id], back_populates="incoming_edges"
    )

    __table_args__ = (
        Index("ix_edges_from_id", "from_id"),
        Index("ix_edges_to_id", "to_id"),
        Index("ix_edges_from_to", "from_id", "to_id"),
    )


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    node_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Store a relative path/key, resolved using ATTACHMENTS_DIR at runtime.
    file_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    node: Mapped[Node] = relationship(back_populates="attachments")

    __table_args__ = (Index("ix_attachments_node_id", "node_id"),)


def create_session_factory(database_url: str) -> sessionmaker:
    engine: Engine = create_engine(database_url, pool_pre_ping=True)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


# -----------------
# Pydantic schemas
# -----------------


class KindCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    schema_: Dict[str, Any] = Field(
        validation_alias="schema", serialization_alias="schema"
    )


class KindOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    schema_: Dict[str, Any] = Field(
        validation_alias="schema", serialization_alias="schema"
    )


class EdgesKindCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_kind: str
    to_kind: str
    relation: str


class EdgesKindOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_kind: str
    to_kind: str
    relation: str


class NodeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class NodeUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload: Dict[str, Any]


class NodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    created_at: datetime
    updated_at: datetime
    payload: Dict[str, Any]


class SearchDatamodel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # If omitted or empty, search across all kinds
    kinds: Optional[List[str]] = Field(default=None)
    # Dot-notation keys mapping to values to match. Values may be strings with
    # '*' wildcards (e.g. "*alpha*") for ILIKE matching, numbers, booleans or null.
    query: Dict[str, Any] = Field(default_factory=dict)

    # Optional pagination limit (no limit if None)
    limit: Optional[int] = Field(default=None)


class EdgeCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_id: UUID
    to_id: UUID
    relation: str


class EdgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    from_id: UUID
    to_id: UUID
    relation: str
    created_at: datetime


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    node_id: UUID
    mime_type: str
    name: str
    created_at: datetime
