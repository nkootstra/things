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


def test_sdk_does_not_import_things_api():
    """SDK core must not depend on the API layer (except config, which is a known seam)."""
    sdk_root = Path("src/things_sdk")
    allowed_api_imports = {"things_api.config"}
    violations: list[str] = []

    for py_file in sdk_root.rglob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("things_api"):
                if node.module not in allowed_api_imports:
                    violations.append(f"{py_file}:{node.lineno} imports {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("things_api") and alias.name not in allowed_api_imports:
                        violations.append(f"{py_file}:{node.lineno} imports {alias.name}")

    assert not violations, f"SDK imports API layer:\n" + "\n".join(violations)
