"""Things MCP — Model Context Protocol server for Things3.

Connects to a running things-api instance over HTTP and exposes
task management tools to AI agents via the MCP stdio transport.
"""

from things_mcp.server import main

__all__ = ["main"]
