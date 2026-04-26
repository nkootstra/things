from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_PYPROJECT = ROOT / "pyproject.toml"
SDK_PYPROJECT = ROOT / "packages" / "things-sdk" / "pyproject.toml"
MCP_PYPROJECT = ROOT / "packages" / "things-mcp" / "pyproject.toml"
VERSION_RE = re.compile(r'^(version\s*=\s*")([^"]+)("\s*)$', re.MULTILINE)
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def validate_version(version: str) -> None:
    if not SEMVER_RE.fullmatch(version):
        raise ValueError(f"Version must look like X.Y.Z, got: {version}")


def replace_version(content: str, version: str) -> str:
    replaced, count = VERSION_RE.subn(rf'\g<1>{version}\g<3>', content, count=1)
    if count != 1:
        raise ValueError("Could not find a unique version field to replace")
    return replaced


def update_versions(version: str) -> None:
    validate_version(version)
    for path in (API_PYPROJECT, SDK_PYPROJECT, MCP_PYPROJECT):
        path.write_text(replace_version(path.read_text(), version))


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def ensure_clean_worktree() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        raise RuntimeError("Worktree is not clean. Commit or stash changes first.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Release both things-api and things-sdk with the same version.")
    parser.add_argument("version", help="Semver version, e.g. 0.2.1")
    parser.add_argument("--skip-tests", action="store_true", help="Skip uv sync and test run")
    parser.add_argument("--no-push", action="store_true", help="Do not push commit/tag to origin")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow running with a dirty worktree")
    args = parser.parse_args()

    validate_version(args.version)
    if not args.allow_dirty:
        ensure_clean_worktree()

    update_versions(args.version)

    if not args.skip_tests:
        run(["uv", "sync", "--dev"])
        run(["uv", "run", "python", "-m", "pytest", "-q"])

    run(["git", "add", str(API_PYPROJECT.relative_to(ROOT)), str(SDK_PYPROJECT.relative_to(ROOT)), str(MCP_PYPROJECT.relative_to(ROOT)), "uv.lock"])
    run(["git", "commit", "-m", f"release: v{args.version}"])
    run(["git", "tag", f"v{args.version}"])

    if not args.no_push:
        run(["git", "push"])
        run(["git", "push", "origin", f"v{args.version}"])


if __name__ == "__main__":
    main()
