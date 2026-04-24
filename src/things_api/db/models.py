from sqlalchemy import Boolean, Column, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Task(Base):
    __tablename__ = "task"

    uuid = Column(String(22), primary_key=True)
    title = Column(Text, nullable=False, default="")
    notes = Column(Text, default="")
    type = Column(Integer, default=0)  # 0=task, 1=project, 2=heading
    status = Column(Integer, default=0)  # 0=pending, 2=cancelled, 3=completed
    schedule = Column(Integer, default=0)  # 0=inbox, 1=anytime, 2=someday
    trashed = Column(Boolean, default=False)
    index = Column(Integer, default=0)
    today_index = Column(Integer, default=0)

    creation_date = Column(Float, nullable=True)
    modification_date = Column(Float, nullable=True)
    start_date = Column(Float, nullable=True)
    deadline = Column(Float, nullable=True)
    completion_date = Column(Float, nullable=True)

    area_uuid = Column(String(22), nullable=True)
    project_uuid = Column(String(22), nullable=True)
    heading_uuid = Column(String(22), nullable=True)

    pending_push = Column(Boolean, default=False)
    local_modified_at = Column(Float, nullable=True)


class Area(Base):
    __tablename__ = "area"

    uuid = Column(String(22), primary_key=True)
    title = Column(Text, nullable=False, default="")
    visible = Column(Boolean, default=True)
    index = Column(Integer, default=0)


class Tag(Base):
    __tablename__ = "tag"

    uuid = Column(String(22), primary_key=True)
    title = Column(Text, nullable=False, default="")
    shortcut = Column(String(10), nullable=True)
    parent_uuid = Column(String(22), nullable=True)
    index = Column(Integer, default=0)


class ChecklistItem(Base):
    __tablename__ = "checklist_item"

    uuid = Column(String(22), primary_key=True)
    title = Column(Text, nullable=False, default="")
    status = Column(Integer, default=0)
    index = Column(Integer, default=0)
    stop_date = Column(Float, nullable=True)
    task_uuid = Column(String(22), nullable=True)


class SyncState(Base):
    __tablename__ = "sync_state"

    id = Column(Integer, primary_key=True, default=1)
    history_key = Column(String(255), nullable=True)
    head_index = Column(Integer, default=0)
    last_sync_at = Column(Float, nullable=True)
    sync_status = Column(String(20), default="never_synced")
    last_error = Column(Text, nullable=True)
