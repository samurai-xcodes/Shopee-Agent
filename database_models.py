import time
from uuid import UUID, uuid4

from sqlalchemy import JSON, CheckConstraint, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TaskRecord(Base):
    __tablename__ = 'tasks'
    __table_args__ = (
        UniqueConstraint('owner_id', 'idempotency_key', name='uq_task_idempotency'),
        CheckConstraint("status IN ('PENDING','RUNNING','WAITING_APPROVAL','SUCCESS','FAILED')", name='ck_task_status'),
        CheckConstraint('length(trim(prompt)) > 0', name='ck_prompt_nonempty'),
        Index('ix_tasks_queue', 'status', 'available_at'),
        Index('ix_tasks_owner_created', 'owner_id', 'created_at'),
    )
    task_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default='PENDING')
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    updated_at: Mapped[float] = mapped_column(Float, default=time.time)
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64), default='')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[float] = mapped_column(Float, default=time.time)
    lease_until: Mapped[float | None] = mapped_column(Float)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    error: Mapped[str | None] = mapped_column(Text)
    result_ref: Mapped[str | None] = mapped_column(String(200))
    approved_version: Mapped[UUID | None] = mapped_column(Uuid)
    result: Mapped[dict | None] = mapped_column(JSON)
    trace_id: Mapped[str] = mapped_column(String(36), default=lambda: str(uuid4()))
    provider: Mapped[str] = mapped_column(String(20), default='mock')


class VersionRecord(Base):
    __tablename__ = 'versions'
    __table_args__ = (UniqueConstraint('task_id', 'number', name='uq_version_number'),)
    version_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(ForeignKey('tasks.task_id'), index=True)
    number: Mapped[int] = mapped_column(Integer)
    parent_id: Mapped[UUID | None] = mapped_column(Uuid)
    document: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class EventRecord(Base):
    __tablename__ = 'events'
    event_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    task_id: Mapped[UUID] = mapped_column(ForeignKey('tasks.task_id'), index=True)
    kind: Mapped[str] = mapped_column(String(50))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)


class OwnerRecord(Base):
    __tablename__ = 'owners'
    owner_id: Mapped[str] = mapped_column(String(100), primary_key=True)


class RequestRecord(Base):
    __tablename__ = 'request_metrics'
    request_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    owner_id: Mapped[str] = mapped_column(String(100), index=True)
    route: Mapped[str] = mapped_column(String(200))
    status_code: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[float] = mapped_column(Float)
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
