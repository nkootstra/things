# things-mcp

Model Context Protocol (MCP) server for Things3. Gives AI agents full read/write access to your tasks through a running [things-api](https://github.com/nkootstra/things) instance.

## Setup

### Prerequisites

A running `things-api` instance with an API key configured.

### Install

```bash
uvx things-mcp
```

Or install from source:

```bash
pip install things-mcp
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
      "args": ["things-mcp"],
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
      "args": ["things-mcp"],
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
      "args": ["things-mcp"],
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
| `list_projects` | All projects |
| `list_tasks_by_tag` | Tasks with a specific tag |
| `list_all_tasks` | Every non-trashed task across the library |

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
| `trigger_sync` | Sync changes to Things Cloud |

## License

Apache-2.0
