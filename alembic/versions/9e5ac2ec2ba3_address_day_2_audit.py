"""address day-2 audit

Revision ID: 9e5ac2ec2ba3
Revises: 552a3882346e
Create Date: 2026-11-06 21:36:05.111023
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9e5ac2ec2ba3"
down_revision: str | None = "552a3882346e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ENUM_TYPES = (
    "user_role",
    "workspace_role",
    "project_status",
    "task_status",
    "task_priority",
)

ENUM_COLUMNS = (
    ("users", "role"),
    ("workspace_members", "role"),
    ("projects", "status"),
    ("tasks", "status"),
    ("tasks", "priority"),
)


def upgrade() -> None:
    op.alter_column(
        "tasks",
        "description",
        existing_type=sa.Text(),
        type_=sa.String(length=2000),
        existing_nullable=True,
    )
    op.create_index(
        op.f("ix_comments_author_id"), "comments", ["author_id"], unique=False
    )
    op.create_index(op.f("ix_comments_task_id"), "comments", ["task_id"], unique=False)
    op.create_index(
        op.f("ix_labels_workspace_id"), "labels", ["workspace_id"], unique=False
    )
    op.create_index(
        op.f("ix_projects_workspace_id"), "projects", ["workspace_id"], unique=False
    )
    op.create_index(
        op.f("ix_task_labels_label_id"), "task_labels", ["label_id"], unique=False
    )
    op.create_index(
        op.f("ix_tasks_assignee_id"), "tasks", ["assignee_id"], unique=False
    )
    op.create_index(
        op.f("ix_tasks_created_by_id"), "tasks", ["created_by_id"], unique=False
    )
    op.create_index(op.f("ix_tasks_project_id"), "tasks", ["project_id"], unique=False)
    op.create_index(
        op.f("ix_workspace_members_user_id"),
        "workspace_members",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspaces_owner_id"), "workspaces", ["owner_id"], unique=False
    )
    op.drop_constraint(op.f("comments_author_id_fkey"), "comments", type_="foreignkey")
    op.create_foreign_key(
        "comments_author_id_fkey",
        "comments",
        "users",
        ["author_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(op.f("tasks_assignee_id_fkey"), "tasks", type_="foreignkey")
    op.drop_constraint(op.f("tasks_created_by_id_fkey"), "tasks", type_="foreignkey")
    op.create_foreign_key(
        "tasks_assignee_id_fkey",
        "tasks",
        "users",
        ["assignee_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "tasks_created_by_id_fkey",
        "tasks",
        "users",
        ["created_by_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        op.f("workspaces_owner_id_fkey"), "workspaces", type_="foreignkey"
    )
    op.create_foreign_key(
        "workspaces_owner_id_fkey",
        "workspaces",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("comments_author_id_fkey", "comments", type_="foreignkey")
    op.create_foreign_key(
        "comments_author_id_fkey",
        "comments",
        "users",
        ["author_id"],
        ["id"],
    )
    op.drop_constraint("tasks_created_by_id_fkey", "tasks", type_="foreignkey")
    op.drop_constraint("tasks_assignee_id_fkey", "tasks", type_="foreignkey")
    op.create_foreign_key(
        "tasks_created_by_id_fkey",
        "tasks",
        "users",
        ["created_by_id"],
        ["id"],
    )
    op.create_foreign_key(
        "tasks_assignee_id_fkey",
        "tasks",
        "users",
        ["assignee_id"],
        ["id"],
    )
    op.drop_constraint("workspaces_owner_id_fkey", "workspaces", type_="foreignkey")
    op.create_foreign_key(
        "workspaces_owner_id_fkey",
        "workspaces",
        "users",
        ["owner_id"],
        ["id"],
    )
    op.drop_index(op.f("ix_comments_author_id"), table_name="comments")
    op.drop_index(op.f("ix_comments_task_id"), table_name="comments")
    op.drop_index(op.f("ix_labels_workspace_id"), table_name="labels")
    op.drop_index(op.f("ix_projects_workspace_id"), table_name="projects")
    op.drop_index(op.f("ix_task_labels_label_id"), table_name="task_labels")
    op.drop_index(op.f("ix_tasks_assignee_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_created_by_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_project_id"), table_name="tasks")
    op.drop_index(op.f("ix_workspace_members_user_id"), table_name="workspace_members")
    op.drop_index(op.f("ix_workspaces_owner_id"), table_name="workspaces")
    op.alter_column(
        "tasks",
        "description",
        existing_type=sa.String(length=2000),
        type_=sa.Text(),
        existing_nullable=True,
    )
    if op.get_context().opts.get("destination_rev") in (None, "base"):
        for table_name, column_name in ENUM_COLUMNS:
            op.drop_column(table_name, column_name)
        for enum_name in ENUM_TYPES:
            op.execute(sa.text(f"DROP TYPE IF EXISTS {enum_name}"))
