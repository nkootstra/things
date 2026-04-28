# things-cloud-mcp

Model Context Protocol (MCP) server for Things3. Gives AI agents full read/write access to your tasks through a running [things-api](https://github.com/nkootstra/things) instance.

## Setup

### Prerequisites

A running `things-api` instance with an API key configured.

### Install

```bash
uvx things-cloud-mcp
```

Or install from source:

```bash
pip install things-cloud-mcp
```

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `THINGS_API_URL` | URL of your things-api instance | `http://localhost:8000` |
| `THINGS_API_KEY` | API key for authentication | (required) |

## Agent Configuration

### Claude Code

Add to your `.claude/settings.json`:

```json
{
  "mcpServers": {
    "things": {
      "command": "uvx",
      "args": ["things-cloud-mcp"],
      "env": {
        "THINGS_API_URL": "http://localhost:8000",
        "THINGS_API_KEY": "your-api-key"
      }
    }
  }
}
```

### Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "things": {
      "command": "uvx",
      "args": ["things-cloud-mcp"],
      "env": {
        "THINGS_API_URL": "http://localhost:8000",
        "THINGS_API_KEY": "your-api-key"
      }
    }
  }
}
```

### Codex

```json
{
  "mcpServers": {
    "things": {
      "command": "uvx",
      "args": ["things-cloud-mcp"],
      "env": {
        "THINGS_API_URL": "http://localhost:8000",
        "THINGS_API_KEY": "your-api-key"
      }
    }
  }
}
```

## Available Tools

### Read Tools
| Tool | Description |
|---|---|
| `list_inbox` | Tasks not yet scheduled |
| `list_today` | Tasks for today or earlier |
| `list_upcoming` | Tasks scheduled for the future |
| `list_anytime` | Tasks available anytime |
| `list_someday` | Low-priority ideas |
| `list_logbook` | Completed tasks (last 30 days) |
| `list_trash` | Trashed tasks |
| `get_task` | Single task by UUID |
| `list_areas` | All areas |
| `list_tags` | All tags |
| `list_projects` | Active projects (with `include_completed` opt-in) |
| `list_tasks_by_tag` | Tasks with a specific tag |
| `list_all_tasks` | Every non-trashed task across the library |
| `search_tasks` | Full-text search across title, notes, and checklist items |
| `search_advanced` | Multi-predicate filter (status, type, schedule, area, project, tag, date ranges, modified/completed since) |

> **Pagination is opt-in.** Every list tool exposes `limit` and `offset`
> arguments, but they default to unset — calling a list tool with no
> arguments returns the full result set in one response. Agents that need
> every task should leave the parameters unset; only page (increment
> `offset` by `limit` until the response is shorter than `limit`) when a
> result set is too large to handle in one chunk.

### Write Tools
| Tool | Description |
|---|---|
| `create_task` | Create a new task |
| `update_task` | Update task fields |
| `complete_task` | Mark task as completed |
| `cancel_task` | Cancel a task |
| `delete_task` | Move task to trash |
| `schedule_task` | Schedule for today/anytime/someday/date |
| `move_to_project` | Move task into a project |
| `assign_tags` | Set tags on a task |
| `create_tag` | Create a new tag |
| `add_checklist_item` | Add a sub-task to a task |
| `complete_checklist_item` | Tick a checklist item |
| `uncomplete_checklist_item` | Untick a checklist item |
| `create_project` | Create a new project |
| `update_project` | Update project fields |
| `complete_project` | Mark a project as completed |
| `delete_project` | Move a project to trash |
| `trigger_sync` | Sync changes to Things Cloud |

## License

Apache-2.0
