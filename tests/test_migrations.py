from pathlib import Path


def test_alembic_baseline_migration_exists():
    root = Path(__file__).resolve().parents[1]
    migration_file = root / "alembic" / "versions" / "0001_initial.py"

    assert migration_file.exists()

    content = migration_file.read_text()
    assert '"task",' in content
    assert '"sync_state",' in content
    assert "last_pull_skipped" in content
    assert "sync_errors_total" in content
    assert "consecutive_sync_errors" in content
    assert "circuit_open_until" in content
    assert "circuit_probe_active" in content
    assert "manual_sync_lock_until" in content
    assert "scheduler_lock_owner" in content
    assert "scheduler_lock_until" in content
