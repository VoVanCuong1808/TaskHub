"""Pure task authorization policy tests."""

import unittest
from uuid import uuid4

from app.core.exceptions import (
    PermissionDeniedError,
    ProjectArchivedError,
    ProjectNotFoundError,
)
from app.models.enums import ProjectStatus, WorkspacePermission, WorkspaceRole
from app.services.task_authorization import (
    TaskAuthorizationContext,
    authorize_task_access,
)


class TaskAuthorizationPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.owner_id = uuid4()
        self.viewer_id = uuid4()
        self.active = TaskAuthorizationContext(
            ProjectStatus.ACTIVE, self.owner_id, WorkspaceRole.VIEWER
        )
        self.archived = TaskAuthorizationContext(
            ProjectStatus.ARCHIVED, self.owner_id, WorkspaceRole.VIEWER
        )

    def test_viewer_can_read_archived_project(self) -> None:
        authorize_task_access(
            self.archived, self.viewer_id, WorkspacePermission.TASK_READ
        )

    def test_viewer_write_is_forbidden_before_archived_conflict(self) -> None:
        with self.assertRaises(PermissionDeniedError):
            authorize_task_access(
                self.archived, self.viewer_id, WorkspacePermission.TASK_UPDATE
            )

    def test_authorized_writer_on_archived_project_gets_conflict(self) -> None:
        archived_editor = TaskAuthorizationContext(
            ProjectStatus.ARCHIVED, self.owner_id, WorkspaceRole.EDITOR
        )
        with self.assertRaises(ProjectArchivedError):
            authorize_task_access(
                archived_editor, self.viewer_id, WorkspacePermission.TASK_UPDATE
            )

    def test_nonmember_is_hidden(self) -> None:
        with self.assertRaises(ProjectNotFoundError):
            authorize_task_access(
                TaskAuthorizationContext(
                    ProjectStatus.ACTIVE, self.owner_id, None
                ),
                self.viewer_id,
                WorkspacePermission.TASK_READ,
            )
