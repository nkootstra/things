"""add task_tag association and tag push columns

Revision ID: 0002_task_tags
Revises: 0001_initial
Create Date: 2026-04-25
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_task_tags"
down_revision: str | Sequence[str] | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "task_tag",
        sa.Column("task_uuid", sa.String(length=22), nullable=False),
        sa.Column("tag_uuid", sa.String(length=22), nullable=False),
        sa.PrimaryKeyConstraint("task_uuid", "tag_uuid"),
    )
    op.create_index("ix_task_tag_task_uuid", "task_tag", ["task_uuid"])
    op.create_index("ix_task_tag_tag_uuid", "task_tag", ["tag_uuid"])

    op.add_column("tag", sa.Column("pending_push", sa.Boolean(), server_default="0"))
    op.add_column("tag", sa.Column("pending_delete", sa.Boolean(), server_default="0"))


def downgrade() -> None:
    op.drop_column("tag", "pending_delete")
    op.drop_column("tag", "pending_push")
    op.drop_index("ix_task_tag_tag_uuid", table_name="task_tag")
    op.drop_index("ix_task_tag_task_uuid", table_name="task_tag")
    op.drop_table("task_tag")
