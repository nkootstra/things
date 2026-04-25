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
    sdk_root = Path("packages/things-sdk/src/things_sdk")
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


def test_examples_only_use_public_sdk_surface():
    """Examples must only import from things_sdk top-level public API."""
    examples_root = Path("examples")
    violations: list[str] = []

    for py_file in examples_root.rglob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("things_sdk."):
                violations.append(f"{py_file}:{node.lineno} imports internal {node.module}")

    assert not violations, "Examples import SDK internals instead of public API:\n" + "\n".join(violations)


def _get_api_imports(root: Path) -> list[tuple[Path, int, str]]:
    hits: list[tuple[Path, int, str]] = []
    for py_file in root.rglob("*.py"):
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                hits.append((py_file, node.lineno, node.module))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    hits.append((py_file, node.lineno, alias.name))
    return hits


def test_api_layer_imports_sdk_public_surface_only():
    """API layer must only import from the SDK's public surface (things_sdk), not SDK internals."""
    api_root = Path("src/things_api")
    sdk_public = "things_sdk"  # allowed: things_sdk (top-level)
    sdk_internal_prefix = "things_sdk."  # forbidden: things_sdk.cloud, things_sdk.db, etc.
    # Re-export shim files are exempt — they exist specifically to bridge the SDK boundary.
    exempt_files = {
        Path("src/things_api/cloud/client.py"),
        Path("src/things_api/cloud/schema.py"),
        Path("src/things_api/cloud/sync.py"),
        Path("src/things_api/db/models.py"),
        Path("src/things_api/db/engine.py"),
        Path("src/things_api/services/task_service.py"),
        Path("src/things_api/services/sync_service.py"),
    }
    violations: list[str] = []

    for py_file, lineno, module in _get_api_imports(api_root):
        if py_file.resolve() in {e.resolve() for e in exempt_files}:
            continue
        if module.startswith(sdk_internal_prefix):
            violations.append(f"{py_file}:{lineno} imports SDK internal {module}")

    assert not violations, "API layer imports SDK internals directly (use shims or top-level things_sdk):\n" + "\n".join(violations)


def test_api_services_do_not_import_routes():
    """Services must not depend on the route layer."""
    services_root = Path("src/things_api/services")
    violations: list[str] = []

    for py_file, lineno, module in _get_api_imports(services_root):
        if module.startswith("things_api.api"):
            violations.append(f"{py_file}:{lineno} imports route layer {module}")

    assert not violations, "Service layer imports route layer (circular dependency):\n" + "\n".join(violations)
