"""Unit tests for the static workspace task permission matrix."""

import unittest

from app.core.authorization import (
    WORKSPACE_ROLE_PERMISSIONS,
    WORKSPACE_WRITE_PERMISSIONS,
    has_workspace_permission,
    is_workspace_write_permission,
)
from app.models.enums import WorkspacePermission, WorkspaceRole


class WorkspacePermissionTests(unittest.TestCase):
    def test_role_permission_matrix(self) -> None:
        expected = {
            WorkspaceRole.OWNER: frozenset(WorkspacePermission),
            WorkspaceRole.EDITOR: frozenset(WorkspacePermission),
            WorkspaceRole.VIEWER: frozenset({WorkspacePermission.TASK_READ}),
        }
        self.assertEqual(set(WORKSPACE_ROLE_PERMISSIONS), set(WorkspaceRole))
        for role in WorkspaceRole:
            for permission in WorkspacePermission:
                with self.subTest(role=role, permission=permission):
                    self.assertEqual(
                        has_workspace_permission(role, permission),
                        permission in expected[role],
                    )

    def test_permission_mapping_is_immutable(self) -> None:
        with self.assertRaises(TypeError):
            WORKSPACE_ROLE_PERMISSIONS[WorkspaceRole.VIEWER] = frozenset()
        with self.assertRaises(AttributeError):
            WORKSPACE_ROLE_PERMISSIONS[WorkspaceRole.VIEWER].add(
                WorkspacePermission.TASK_CREATE
            )

    def test_read_write_classification_covers_every_permission(self) -> None:
        self.assertEqual(
            WORKSPACE_WRITE_PERMISSIONS,
            frozenset(
                {
                    WorkspacePermission.TASK_CREATE,
                    WorkspacePermission.TASK_UPDATE,
                    WorkspacePermission.TASK_DELETE,
                }
            ),
        )
        read_permissions = frozenset(WorkspacePermission) - WORKSPACE_WRITE_PERMISSIONS
        self.assertEqual(read_permissions, frozenset({WorkspacePermission.TASK_READ}))
        for permission in WorkspacePermission:
            with self.subTest(permission=permission):
                self.assertEqual(
                    is_workspace_write_permission(permission),
                    permission in WORKSPACE_WRITE_PERMISSIONS,
                )
