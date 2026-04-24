"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task",
        sa.Column("uuid", sa.String(length=22), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("type", sa.Integer(), nullable=True),
        sa.Column("status", sa.Integer(), nullable=True),
        sa.Column("schedule", sa.Integer(), nullable=True),
        sa.Column("trashed", sa.Boolean(), nullable=True),
        sa.Column("index", sa.Integer(), nullable=True),
        sa.Column("today_index", sa.Integer(), nullable=True),
        sa.Column("creation_date", sa.Float(), nullable=True),
        sa.Column("modification_date", sa.Float(), nullable=True),
        sa.Column("start_date", sa.Float(), nullable=True),
        sa.Column("deadline", sa.Float(), nullable=True),
        sa.Column("completion_date", sa.Float(), nullable=True),
        sa.Column("area_uuid", sa.String(length=22), nullable=True),
        sa.Column("project_uuid", sa.String(length=22), nullable=True),
        sa.Column("heading_uuid", sa.String(length=22), nullable=True),
        sa.Column("pending_push", sa.Boolean(), nullable=True),
        sa.Column("local_modified_at", sa.Float(), nullable=True),
    )

    op.create_table(
        "area",
        sa.Column("uuid", sa.String(length=22), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("visible", sa.Boolean(), nullable=True),
        sa.Column("index", sa.Integer(), nullable=True),
    )

    op.create_table(
        "tag",
        sa.Column("uuid", sa.String(length=22), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("shortcut", sa.String(length=10), nullable=True),
        sa.Column("parent_uuid", sa.String(length=22), nullable=True),
        sa.Column("index", sa.Integer(), nullable=True),
    )

    op.create_table(
        "checklist_item",
        sa.Column("uuid", sa.String(length=22), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Integer(), nullable=True),
        sa.Column("index", sa.Integer(), nullable=True),
        sa.Column("stop_date", sa.Float(), nullable=True),
        sa.Column("task_uuid", sa.String(length=22), nullable=True),
    )

    op.create_table(
        "sync_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("history_key", sa.String(length=255), nullable=True),
        sa.Column("head_index", sa.Integer(), nullable=True),
        sa.Column("last_sync_at", sa.Float(), nullable=True),
        sa.Column("sync_status", sa.String(length=20), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_pull_skipped", sa.Integer(), nullable=True),
        sa.Column("sync_errors_total", sa.Integer(), nullable=True),
        sa.Column("consecutive_sync_errors", sa.Integer(), nullable=True),
        sa.Column("circuit_open_until", sa.Float(), nullable=True),
        sa.Column("circuit_probe_active", sa.Boolean(), nullable=True),
        sa.Column("manual_sync_lock_until", sa.Float(), nullable=True),
        sa.Column("scheduler_lock_owner", sa.String(length=64), nullable=True),
        sa.Column("scheduler_lock_until", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("sync_state")
    op.drop_table("checklist_item")
    op.drop_table("tag")
    op.drop_table("area")
    op.drop_table("task")
