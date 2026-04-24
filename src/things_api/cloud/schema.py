"""Pydantic models for Things Cloud wire format."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TaskPayload(BaseModel):
    title: str | None = Field(None, alias="tt")
    notes: str | None = Field(None, alias="nt")
    status: int | None = Field(None, alias="ss")
    schedule: int | None = Field(None, alias="st")
    is_project: int | None = Field(None, alias="tp")
    trashed: bool | None = Field(None, alias="tr")
    index: int | None = Field(None, alias="ix")
    today_index: int | None = Field(None, alias="ti")
    creation_date: float | None = Field(None, alias="cd")
    modification_date: float | None = Field(None, alias="md")
    start_date: float | None = Field(None, alias="sr")
    deadline: float | None = Field(None, alias="dd")
    completion_date: float | None = Field(None, alias="sp")
    area_ids: list[str] | None = Field(None, alias="ar")
    project_ids: list[str] | None = Field(None, alias="pr")
    tag_ids: list[str] | None = Field(None, alias="tg")
    heading_ids: list[str] | None = Field(None, alias="agr")

    model_config = {"populate_by_name": True}


class AreaPayload(BaseModel):
    title: str | None = Field(None, alias="tt")
    visible: bool | None = Field(None, alias="vs")
    index: int | None = Field(None, alias="ix")
    model_config = {"populate_by_name": True}


class TagPayload(BaseModel):
    title: str | None = Field(None, alias="tt")
    shortcut: str | None = Field(None, alias="sh")
    parent_ids: list[str] | None = Field(None, alias="pn")
    index: int | None = Field(None, alias="ix")
    model_config = {"populate_by_name": True}


class ChecklistItemPayload(BaseModel):
    title: str | None = Field(None, alias="tt")
    status: int | None = Field(None, alias="ss")
    index: int | None = Field(None, alias="ix")
    stop_date: float | None = Field(None, alias="sp")
    task_ids: list[str] | None = Field(None, alias="ts")
    model_config = {"populate_by_name": True}


ACTION_CREATED = 0
ACTION_MODIFIED = 1
ACTION_DELETED = 2
