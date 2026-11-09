"""Explicit, transactional conversion of the two pre-review Day 2 schemas."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.db.seed import disabled_password_hash

LEGACY_REVISIONS = {"552a3882346e", "9e5ac2ec2ba3"}
TARGET_REVISION = "552a3882346e"
DEFAULT_LABEL_COLOR = "#777777"
REQUIRED_COLUMNS = {
    "users": {"id", "email", "name", "role", "is_active", "created_at"},
    "workspaces": {"id", "name", "owner_id", "created_at"},
    "projects": {"id", "workspace_id", "name", "status", "created_at"},
    "labels": {"id", "workspace_id", "name"},
    "tasks": {"id", "project_id", "created_by_id", "created_at"},
    "comments": {"id", "task_id", "author_id", "body", "created_at"},
    "task_labels": {"task_id", "label_id"},
    "workspace_members": {"workspace_id", "user_id", "role"},
}


async def _columns(connection: AsyncConnection) -> dict[str, set[str]]:
    rows = await connection.execute(
        text(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema()"
        )
    )
    result: dict[str, set[str]] = defaultdict(set)
    for table_name, column_name in rows:
        result[table_name].add(column_name)
    return result


async def _preflight(connection: AsyncConnection) -> str:
    columns = await _columns(connection)
    missing = {
        table: sorted(required - columns.get(table, set()))
        for table, required in REQUIRED_COLUMNS.items()
        if required - columns.get(table, set())
    }
    if missing:
        raise ValueError(f"Not a supported legacy schema; missing columns: {missing}")
    version = await connection.scalar(text("SELECT version_num FROM alembic_version"))
    if version not in LEGACY_REVISIONS:
        raise ValueError(f"Unsupported Alembic revision: {version!r}")
    enum_values = await connection.execute(
        text(
            "SELECT t.typname, e.enumlabel FROM pg_type t "
            "JOIN pg_enum e ON e.enumtypid = t.oid "
            "WHERE t.typname IN ('user_role','workspace_role','project_status',"
            "'task_status','task_priority')"
        )
    )
    enums: dict[str, set[str]] = defaultdict(set)
    for enum_name, label in enum_values:
        enums[enum_name].add(label)
    expected = {
        "user_role": {"ADMIN", "MEMBER"},
        "workspace_role": {"OWNER", "EDITOR", "VIEWER"},
        "project_status": {"ACTIVE", "ARCHIVED"},
        "task_status": {"TODO", "IN_PROGRESS", "IN_REVIEW", "DONE"},
        "task_priority": {"LOW", "MEDIUM", "HIGH", "URGENT"},
    }
    if enums != expected:
        raise ValueError(f"Unexpected enum definitions; found {dict(enums)}")
    long_description = await connection.scalar(
        text("SELECT EXISTS (SELECT 1 FROM tasks WHERE length(description) > 2000)")
    )
    if long_description:
        raise ValueError("Cannot narrow tasks.description: rows exceed 2000 characters")
    ambiguous = await connection.execute(
        text(
            "SELECT l.id, count(p.id) AS project_count FROM labels l "
            "LEFT JOIN projects p ON p.workspace_id = l.workspace_id "
            "GROUP BY l.id HAVING count(p.id) <> 1 LIMIT 1"
        )
    )
    row = ambiguous.first()
    if row:
        raise ValueError(
            f"Cannot map label {row.id}: its workspace has {row.project_count} "
            "projects; each legacy label must map to exactly one project"
        )
    mismatch = await connection.execute(
        text(
            "SELECT tl.task_id, tl.label_id FROM task_labels tl "
            "JOIN tasks t ON t.id = tl.task_id "
            "JOIN labels l ON l.id = tl.label_id "
            "JOIN projects p ON p.workspace_id = l.workspace_id "
            "WHERE t.project_id <> p.id LIMIT 1"
        )
    )
    row = mismatch.first()
    if row:
        raise ValueError(
            f"Cannot map task-label link {row.task_id}/{row.label_id}: "
            "the task project differs from the label's unique workspace project"
        )
    return version


async def upgrade_legacy_schema(connection: AsyncConnection) -> str:
    """Upgrade a supported legacy schema within the caller's transaction."""
    version = await _preflight(connection)
    if version == TARGET_REVISION:
        await connection.execute(
            text("ALTER TABLE users RENAME COLUMN name TO full_name")
        )
        await connection.execute(
            text("ALTER TABLE tasks RENAME COLUMN created_by_id TO created_by")
        )
        await connection.execute(
            text("ALTER TABLE comments RENAME COLUMN body TO content")
        )
        await connection.execute(
            text("ALTER TABLE projects ADD COLUMN description VARCHAR(2000)")
        )
        await connection.execute(
            text("ALTER TABLE tasks ALTER COLUMN description TYPE VARCHAR(2000)")
        )
        await connection.execute(
            text("ALTER TABLE users ADD COLUMN hashed_password VARCHAR(255)")
        )
        users = await connection.execute(text("SELECT id FROM users"))
        for (user_id,) in users:
            await connection.execute(
                text("UPDATE users SET hashed_password = :value WHERE id = :id"),
                {"value": disabled_password_hash(), "id": user_id},
            )
        await connection.execute(
            text("ALTER TABLE users ALTER COLUMN hashed_password SET NOT NULL")
        )
        await connection.execute(text("ALTER TABLE labels ADD COLUMN project_id UUID"))
        await connection.execute(
            text("ALTER TABLE labels ADD COLUMN color VARCHAR(32)")
        )
        await connection.execute(
            text(
                "UPDATE labels l SET project_id = p.id FROM projects p "
                "WHERE p.workspace_id = l.workspace_id"
            )
        )
        await connection.execute(
            text("UPDATE labels SET color = :color"), {"color": DEFAULT_LABEL_COLOR}
        )
        await connection.execute(
            text("ALTER TABLE labels ALTER COLUMN project_id SET NOT NULL")
        )
        await connection.execute(
            text("ALTER TABLE labels ALTER COLUMN color SET NOT NULL")
        )
        await connection.execute(
            text("ALTER TABLE labels DROP CONSTRAINT labels_workspace_id_fkey")
        )
        await connection.execute(text("DROP INDEX IF EXISTS ix_labels_workspace_id"))
        await connection.execute(text("ALTER TABLE labels DROP COLUMN workspace_id"))
        await connection.execute(
            text(
                "ALTER TABLE labels ADD CONSTRAINT labels_project_id_fkey "
                "FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE"
            )
        )
        await connection.execute(
            text("CREATE INDEX ix_labels_project_id ON labels(project_id)")
        )
        await connection.execute(
            text("ALTER TABLE tasks DROP CONSTRAINT tasks_created_by_id_fkey")
        )
        await connection.execute(text("DROP INDEX IF EXISTS ix_tasks_created_by_id"))
        await connection.execute(
            text(
                "ALTER TABLE tasks ADD CONSTRAINT tasks_created_by_fkey "
                "FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE RESTRICT"
            )
        )
        await connection.execute(
            text("CREATE INDEX ix_tasks_created_by ON tasks(created_by)")
        )
    else:
        await connection.execute(
            text("ALTER TABLE users RENAME COLUMN name TO full_name")
        )
        await connection.execute(
            text("ALTER TABLE tasks RENAME COLUMN created_by_id TO created_by")
        )
        await connection.execute(
            text("ALTER TABLE comments RENAME COLUMN body TO content")
        )
        await connection.execute(
            text("ALTER TABLE projects ADD COLUMN description VARCHAR(2000)")
        )
        await connection.execute(
            text("ALTER TABLE tasks ALTER COLUMN description TYPE VARCHAR(2000)")
        )
        await connection.execute(
            text("ALTER TABLE users ADD COLUMN hashed_password VARCHAR(255)")
        )
        users = await connection.execute(text("SELECT id FROM users"))
        for (user_id,) in users:
            await connection.execute(
                text("UPDATE users SET hashed_password = :value WHERE id = :id"),
                {"value": disabled_password_hash(), "id": user_id},
            )
        await connection.execute(
            text("ALTER TABLE users ALTER COLUMN hashed_password SET NOT NULL")
        )
        await connection.execute(text("ALTER TABLE labels ADD COLUMN project_id UUID"))
        await connection.execute(
            text("ALTER TABLE labels ADD COLUMN color VARCHAR(32)")
        )
        await connection.execute(
            text(
                "UPDATE labels l SET project_id = p.id FROM projects p WHERE p.workspace_id = l.workspace_id"
            )
        )
        await connection.execute(
            text("UPDATE labels SET color = :color"), {"color": DEFAULT_LABEL_COLOR}
        )
        await connection.execute(
            text("ALTER TABLE labels ALTER COLUMN project_id SET NOT NULL")
        )
        await connection.execute(
            text("ALTER TABLE labels ALTER COLUMN color SET NOT NULL")
        )
        await connection.execute(
            text("ALTER TABLE labels DROP CONSTRAINT labels_workspace_id_fkey")
        )
        await connection.execute(text("DROP INDEX IF EXISTS ix_labels_workspace_id"))
        await connection.execute(text("ALTER TABLE labels DROP COLUMN workspace_id"))
        await connection.execute(
            text(
                "ALTER TABLE labels ADD CONSTRAINT labels_project_id_fkey FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE"
            )
        )
        await connection.execute(
            text("CREATE INDEX ix_labels_project_id ON labels(project_id)")
        )
        await connection.execute(
            text("ALTER TABLE tasks DROP CONSTRAINT tasks_created_by_id_fkey")
        )
        await connection.execute(text("DROP INDEX IF EXISTS ix_tasks_created_by_id"))
        await connection.execute(
            text(
                "ALTER TABLE tasks ADD CONSTRAINT tasks_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE RESTRICT"
            )
        )
        await connection.execute(
            text("CREATE INDEX ix_tasks_created_by ON tasks(created_by)")
        )
    columns = await _columns(connection)
    for table in ("comments", "labels", "workspace_members"):
        if "updated_at" not in columns[table]:
            await connection.execute(
                text(f"ALTER TABLE {table} ADD COLUMN updated_at TIMESTAMPTZ")
            )
        await connection.execute(
            text(f"UPDATE {table} SET updated_at = created_at WHERE updated_at IS NULL")
        )
        await connection.execute(
            text(f"ALTER TABLE {table} ALTER COLUMN updated_at SET NOT NULL")
        )
    for column in ("created_at", "updated_at"):
        if column not in columns["task_labels"]:
            await connection.execute(
                text(f"ALTER TABLE task_labels ADD COLUMN {column} TIMESTAMPTZ")
            )
    await connection.execute(
        text(
            "UPDATE task_labels tl SET "
            "created_at = COALESCE(tl.created_at, t.created_at), "
            "updated_at = COALESCE(tl.updated_at, t.created_at) "
            "FROM tasks t WHERE t.id = tl.task_id "
            "AND (tl.created_at IS NULL OR tl.updated_at IS NULL)"
        )
    )
    await connection.execute(
        text("ALTER TABLE task_labels ALTER COLUMN created_at SET NOT NULL")
    )
    await connection.execute(
        text("ALTER TABLE task_labels ALTER COLUMN updated_at SET NOT NULL")
    )
    for table, name, column in (
        ("workspaces", "workspaces_owner_id_fkey", "owner_id"),
        ("comments", "comments_author_id_fkey", "author_id"),
    ):
        await connection.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT {name}"))
        await connection.execute(
            text(
                f"ALTER TABLE {table} ADD CONSTRAINT {name} "
                f"FOREIGN KEY ({column}) REFERENCES users(id) ON DELETE RESTRICT"
            )
        )
    await connection.execute(
        text("ALTER TABLE tasks DROP CONSTRAINT tasks_assignee_id_fkey")
    )
    await connection.execute(
        text(
            "ALTER TABLE tasks ADD CONSTRAINT tasks_assignee_id_fkey "
            "FOREIGN KEY (assignee_id) REFERENCES users(id) ON DELETE SET NULL"
        )
    )
    for table, index, indexed_columns in (
        ("workspaces", "ix_workspaces_owner_id", "owner_id"),
        ("workspace_members", "ix_workspace_members_user_id", "user_id"),
        ("projects", "ix_projects_workspace_id", "workspace_id"),
        ("tasks", "ix_tasks_project_id", "project_id"),
        ("tasks", "ix_tasks_assignee_id", "assignee_id"),
        ("task_labels", "ix_task_labels_label_id", "label_id"),
        ("comments", "ix_comments_task_id", "task_id"),
        ("comments", "ix_comments_author_id", "author_id"),
    ):
        await connection.execute(
            text(f"CREATE INDEX IF NOT EXISTS {index} ON {table}({indexed_columns})")
        )
    await connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_tasks_status_created_at_id "
            "ON tasks(status, created_at, id)"
        )
    )
    await connection.execute(
        text("UPDATE alembic_version SET version_num = :revision"),
        {"revision": TARGET_REVISION},
    )
    return TARGET_REVISION
