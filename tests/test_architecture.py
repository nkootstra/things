"""Architecture guardrails for dependency boundaries."""

from __future__ import annotations

import ast
from pathlib import Path


def test_routes_depend_on_service_contracts_not_concrete_classes():
    routes_path = Path("src/things_api/api/routes.py")
    tree = ast.parse(routes_path.read_text())

    imported_from_sync_service: set[str] = set()
    imported_from_task_service: set[str] = set()
    imported_from_mapper_service: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "things_api.services.sync_service":
                imported_from_sync_service.update(alias.name for alias in node.names)
            elif node.module == "things_api.services.task_service":
                imported_from_task_service.update(alias.name for alias in node.names)
            elif node.module == "things_api.services.task_command_mapper":
                imported_from_mapper_service.update(alias.name for alias in node.names)

    # Only provider functions should be imported from concrete service modules.
    assert imported_from_sync_service <= {"get_sync_service"}
    assert imported_from_task_service <= {"get_task_service"}
    assert imported_from_mapper_service <= {"get_task_command_mapper"}
