from __future__ import annotations

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "task"

    uuid: Mapped[str] = mapped_column(String(22), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    type: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[int] = mapped_column(Integer, default=0)
    schedule: Mapped[int] = mapped_column(Integer, default=0)
    trashed: Mapped[bool] = mapped_column(Boolean, default=False)
    index: Mapped[int] = mapped_column(Integer, default=0)
    today_index: Mapped[int] = mapped_column(Integer, default=0)
    start_bucket: Mapped[int] = mapped_column(Integer, default=0)  # 0=morning, 1=evening

    creation_date: Mapped[float | None] = mapped_column(Float, nullable=True)
    modification_date: Mapped[float | None] = mapped_column(Float, nullable=True)
    start_date: Mapped[float | None] = mapped_column(Float, nullable=True)
    deadline: Mapped[float | None] = mapped_column(Float, nullable=True)
    completion_date: Mapped[float | None] = mapped_column(Float, nullable=True)
    reminder_time: Mapped[int | None] = mapped_column(Integer, nullable=True)

    area_uuid: Mapped[str | None] = mapped_column(String(22), nullable=True)
    project_uuid: Mapped[str | None] = mapped_column(String(22), nullable=True)
    heading_uuid: Mapped[str | None] = mapped_column(String(22), nullable=True)
    contact_uuid: Mapped[str | None] = mapped_column(String(22), nullable=True)

    pending_push: Mapped[bool] = mapped_column(Boolean, default=False)
    local_modified_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    leaves_tombstone: Mapped[bool] = mapped_column(Boolean, default=True)
    is_new: Mapped[bool] = mapped_column(Boolean, default=False)


class Area(Base):
    __tablename__ = "area"

    uuid: Mapped[str] = mapped_column(String(22), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    visible: Mapped[bool] = mapped_column(Boolean, default=True)
    index: Mapped[int] = mapped_column(Integer, default=0)


class Tag(Base):
    __tablename__ = "tag"

    uuid: Mapped[str] = mapped_column(String(22), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    shortcut: Mapped[str | None] = mapped_column(String(10), nullable=True)
    parent_uuid: Mapped[str | None] = mapped_column(String(22), nullable=True)
    index: Mapped[int] = mapped_column(Integer, default=0)
    pending_push: Mapped[bool] = mapped_column(Boolean, default=False)
    pending_delete: Mapped[bool] = mapped_column(Boolean, default=False)
    is_new: Mapped[bool] = mapped_column(Boolean, default=False)


class TaskTag(Base):
    __tablename__ = "task_tag"

    task_uuid: Mapped[str] = mapped_column(String(22), primary_key=True)
    tag_uuid: Mapped[str] = mapped_column(String(22), primary_key=True)


class ChecklistItem(Base):
    __tablename__ = "checklist_item"

    uuid: Mapped[str] = mapped_column(String(22), primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[int] = mapped_column(Integer, default=0)
    index: Mapped[int] = mapped_column(Integer, default=0)
    stop_date: Mapped[float | None] = mapped_column(Float, nullable=True)
    task_uuid: Mapped[str | None] = mapped_column(String(22), nullable=True)
    creation_date: Mapped[float | None] = mapped_column(Float, nullable=True)
    modification_date: Mapped[float | None] = mapped_column(Float, nullable=True)
    pending_push: Mapped[bool] = mapped_column(Boolean, default=False)
    is_new: Mapped[bool] = mapped_column(Boolean, default=False)


class SyncState(Base):
    __tablename__ = "sync_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    history_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    head_index: Mapped[int] = mapped_column(Integer, default=0)
    last_sync_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    sync_status: Mapped[str] = mapped_column(String(20), default="never_synced")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_pull_skipped: Mapped[int] = mapped_column(Integer, default=0)
    sync_errors_total: Mapped[int] = mapped_column(Integer, default=0)
    consecutive_sync_errors: Mapped[int] = mapped_column(Integer, default=0)
    circuit_open_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    circuit_probe_active: Mapped[bool] = mapped_column(Boolean, default=False)
    manual_sync_lock_until: Mapped[float | None] = mapped_column(Float, nullable=True)
    scheduler_lock_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scheduler_lock_until: Mapped[float | None] = mapped_column(Float, nullable=True)
