"""Maps HTTP task payloads into service command payloads."""

from __future__ import annotations

from enum import IntEnum

from fastapi import HTTPException

from things_api.services.contracts import TaskCommandMapperProtocol


class TaskCommandMapper:
    def to_create_payload(
        self,
        body,
        *,
        status_enum: type[IntEnum],
        schedule_enum: type[IntEnum],
        type_enum: type[IntEnum],
    ) -> dict:
        return {
            "title": body.title,
            "notes": body.notes,
            "status": self._resolve_enum(body.status, status_enum),
            "schedule": self._resolve_enum(body.schedule, schedule_enum),
            "type": self._resolve_enum(body.type, type_enum),
            "area_uuid": body.area_uuid,
            "project_uuid": body.project_uuid,
            "heading_uuid": body.heading_uuid,
            "contact_uuid": body.contact_uuid,
            "deadline": body.deadline,
            "start_date": body.start_date,
            "reminder_time": body.reminder_time,
            "tags": body.tags,
            "auto_create_tags": body.auto_create_tags,
        }

    def to_update_payload(
        self,
        updates: dict,
        *,
        status_enum: type[IntEnum],
        schedule_enum: type[IntEnum],
        type_enum: type[IntEnum],
    ) -> dict:
        if "status" in updates and updates["status"] is not None:
            updates["status"] = self._resolve_enum(updates["status"], status_enum)
        if "schedule" in updates and updates["schedule"] is not None:
            updates["schedule"] = self._resolve_enum(updates["schedule"], schedule_enum)
        if "type" in updates and updates["type"] is not None:
            updates["type"] = self._resolve_enum(updates["type"], type_enum)
        return updates

    def _resolve_enum(self, value, enum_cls: type[IntEnum]) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            try:
                return enum_cls[value].value
            except KeyError:
                valid = ", ".join(e.name for e in enum_cls)
                raise HTTPException(status_code=422, detail=f"Invalid value '{value}'. Valid: {valid}")
        return value


def get_task_command_mapper() -> TaskCommandMapperProtocol:
    return TaskCommandMapper()
