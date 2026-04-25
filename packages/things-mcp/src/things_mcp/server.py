"""Things MCP server — stdio transport."""

from __future__ import annotations

import json
import logging

from mcp.server.fastmcp import FastMCP

from things_mcp.client import ThingsAPIClient

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "Things",
    instructions=(
        "Things MCP gives you read/write access to a Things3 task manager. "
        "Use the smart-list tools (list_inbox, list_today, etc.) to see what "
        "the user has on their plate. Use write tools to create, update, "
        "complete, or reschedule tasks. Always trigger_sync after writes "
        "so changes appear on the user's devices."
    ),
)

_client: ThingsAPIClient | None = None


def _get_client() -> ThingsAPIClient:
    global _client
    if _client is None:
        _client = ThingsAPIClient()
    return _client


# ============================================================
# Read tools
# ============================================================


@mcp.tool()
async def list_inbox(limit: int | None = None, offset: int | None = None) -> str:
    """List tasks in the Inbox — tasks not yet scheduled or assigned to a list.

    Inbox = schedule is 'inbox', not completed, not trashed.
    """
    result = await _get_client().list_inbox(limit=limit, offset=offset)
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_today(limit: int | None = None, offset: int | None = None) -> str:
    """List tasks scheduled for today or earlier that aren't completed.

    Today = start date is today or before, not completed, not trashed.
    Ordered by today_index then index.
    """
    result = await _get_client().list_today(limit=limit, offset=offset)
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_upcoming(limit: int | None = None, offset: int | None = None) -> str:
    """List tasks scheduled for a future date.

    Upcoming = start date is after today, not completed, not trashed.
    Ordered by start date, then deadline.
    """
    result = await _get_client().list_upcoming(limit=limit, offset=offset)
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_anytime(limit: int | None = None, offset: int | None = None) -> str:
    """List tasks in the Anytime list — available to work on, no specific date.

    Anytime = schedule is 'anytime', not completed, not trashed.
    """
    result = await _get_client().list_anytime(limit=limit, offset=offset)
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_someday(limit: int | None = None, offset: int | None = None) -> str:
    """List tasks in the Someday list — ideas and tasks without urgency.

    Someday = schedule is 'someday', not completed, not trashed.
    """
    result = await _get_client().list_someday(limit=limit, offset=offset)
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_logbook(since_days: int = 30, limit: int | None = 100) -> str:
    """List completed tasks from the Logbook.

    Shows tasks completed within the last `since_days` days (default 30).
    Ordered by completion date, newest first.
    """
    import time
    since = time.time() - (since_days * 86400)
    result = await _get_client().list_logbook(since=since, limit=limit)
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_trash(limit: int | None = 100) -> str:
    """List trashed tasks. Ordered by modification date, newest first."""
    result = await _get_client().list_trash(limit=limit)
    return json.dumps(result, indent=2)


@mcp.tool()
async def get_task(uuid: str) -> str:
    """Get a single task by its UUID. Returns full task details including tags."""
    result = await _get_client().get_task(uuid)
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_areas() -> str:
    """List all areas. Areas are high-level life categories (e.g., Work, Personal)."""
    result = await _get_client().list_areas()
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_tags() -> str:
    """List all tags. Tags can be hierarchical (e.g., work/errands)."""
    result = await _get_client().list_tags()
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_projects() -> str:
    """List all projects. Projects are multi-step tasks that contain sub-tasks."""
    result = await _get_client().list_projects()
    return json.dumps(result, indent=2)


@mcp.tool()
async def list_tasks_by_tag(tag: str, include_descendants: bool = True) -> str:
    """List tasks with a specific tag.

    Args:
        tag: Tag UUID or name (e.g., 'work' or 'work/errands').
        include_descendants: If True (default), also matches child tags.
    """
    result = await _get_client().list_tasks_by_tag(tag, include_descendants=include_descendants)
    return json.dumps(result, indent=2)


# ============================================================
# Write tools
# ============================================================


@mcp.tool()
async def create_task(
    title: str,
    notes: str | None = None,
    schedule: str = "inbox",
    tags: list[str] | None = None,
    project_uuid: str | None = None,
    area_uuid: str | None = None,
    deadline: float | None = None,
    start_date: float | None = None,
) -> str:
    """Create a new task in Things3.

    Args:
        title: Task title (required).
        notes: Optional notes/description.
        schedule: One of 'inbox', 'anytime', or 'someday'. Default: 'inbox'.
        tags: Optional list of tag UUIDs or names to assign.
        project_uuid: UUID of the project to add this task to.
        area_uuid: UUID of the area to assign this task to.
        deadline: Unix timestamp for the deadline.
        start_date: Unix timestamp for the start date (schedules for a specific day).
    """
    payload: dict = {"title": title, "schedule": schedule}
    if notes is not None:
        payload["notes"] = notes
    if tags is not None:
        payload["tags"] = tags
    if project_uuid is not None:
        payload["project_uuid"] = project_uuid
    if area_uuid is not None:
        payload["area_uuid"] = area_uuid
    if deadline is not None:
        payload["deadline"] = deadline
    if start_date is not None:
        payload["start_date"] = start_date
    result = await _get_client().create_task(payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def update_task(
    uuid: str,
    title: str | None = None,
    notes: str | None = None,
    schedule: str | None = None,
    tags: list[str] | None = None,
    project_uuid: str | None = None,
    area_uuid: str | None = None,
    deadline: float | None = None,
    start_date: float | None = None,
) -> str:
    """Update an existing task. Only provided fields are changed.

    Args:
        uuid: Task UUID (required).
        title: New title.
        notes: New notes.
        schedule: 'inbox', 'anytime', or 'someday'.
        tags: New tag list (replaces existing tags).
        project_uuid: Move to this project.
        area_uuid: Assign to this area.
        deadline: New deadline (Unix timestamp).
        start_date: New start date (Unix timestamp).
    """
    payload: dict = {}
    if title is not None:
        payload["title"] = title
    if notes is not None:
        payload["notes"] = notes
    if schedule is not None:
        payload["schedule"] = schedule
    if tags is not None:
        payload["tags"] = tags
    if project_uuid is not None:
        payload["project_uuid"] = project_uuid
    if area_uuid is not None:
        payload["area_uuid"] = area_uuid
    if deadline is not None:
        payload["deadline"] = deadline
    if start_date is not None:
        payload["start_date"] = start_date
    result = await _get_client().update_task(uuid, payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def complete_task(uuid: str) -> str:
    """Mark a task as completed.

    Args:
        uuid: Task UUID.
    """
    result = await _get_client().update_task(uuid, {"status": "completed"})
    return json.dumps(result, indent=2)


@mcp.tool()
async def cancel_task(uuid: str) -> str:
    """Cancel a task (mark as cancelled, not deleted).

    Args:
        uuid: Task UUID.
    """
    result = await _get_client().update_task(uuid, {"status": "cancelled"})
    return json.dumps(result, indent=2)


@mcp.tool()
async def delete_task(uuid: str) -> str:
    """Move a task to the trash.

    Args:
        uuid: Task UUID.
    """
    await _get_client().delete_task(uuid)
    return json.dumps({"status": "deleted", "uuid": uuid})


@mcp.tool()
async def schedule_task(uuid: str, schedule: str, start_date: float | None = None) -> str:
    """Schedule a task for today, anytime, someday, or a specific date.

    Args:
        uuid: Task UUID.
        schedule: 'inbox', 'anytime', or 'someday'.
        start_date: Optional Unix timestamp to schedule for a specific day.
    """
    payload: dict = {"schedule": schedule}
    if start_date is not None:
        payload["start_date"] = start_date
    result = await _get_client().update_task(uuid, payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def move_to_project(uuid: str, project_uuid: str) -> str:
    """Move a task into a project.

    Args:
        uuid: Task UUID.
        project_uuid: Target project UUID.
    """
    result = await _get_client().update_task(uuid, {"project_uuid": project_uuid})
    return json.dumps(result, indent=2)


@mcp.tool()
async def assign_tags(uuid: str, tags: list[str]) -> str:
    """Replace the tags on a task.

    Args:
        uuid: Task UUID.
        tags: List of tag UUIDs or names. Pass empty list to remove all tags.
    """
    result = await _get_client().update_task(uuid, {"tags": tags})
    return json.dumps(result, indent=2)


@mcp.tool()
async def create_tag(title: str, parent: str | None = None, shortcut: str | None = None) -> str:
    """Create a new tag.

    Args:
        title: Tag name.
        parent: Optional parent tag UUID or name for hierarchy (e.g., creates 'errands' under 'work').
        shortcut: Optional single-character keyboard shortcut.
    """
    payload: dict = {"title": title}
    if parent is not None:
        payload["parent"] = parent
    if shortcut is not None:
        payload["shortcut"] = shortcut
    result = await _get_client().create_tag(payload)
    return json.dumps(result, indent=2)


@mcp.tool()
async def trigger_sync() -> str:
    """Trigger a full pull + push sync with Things Cloud.

    Call this after making changes so they appear on all your devices.
    """
    result = await _get_client().trigger_sync()
    return json.dumps(result, indent=2)


# ============================================================
# Entry point
# ============================================================


def main() -> None:
    """Run the MCP server over stdio."""
    mcp.run(transport="stdio")
