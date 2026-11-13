"""Unit tests for the static workspace task permission matrix."""

import unittest
from uuid import uuid4

from app.core.authorization import (
    WORKSPACE_ROLE_PERMISSIONS,
    WORKSPACE_WRITE_PERMISSIONS,
    effective_workspace_role,
    has_workspace_permission,
    is_workspace_write_permission,
)
from app.models.enums import WorkspacePermission, WorkspaceRole


class WorkspacePermissionTests(unittest.TestCase):
    def test_effective_role_uses_owner_field_and_demotes_stale_owner(self) -> None:
        owner_id = uuid4()
        member_id = uuid4()
        self.assertEqual(
            effective_workspace_role(owner_id, owner_id, None), WorkspaceRole.OWNER
        )
        self.assertEqual(
            effective_workspace_role(owner_id, owner_id, WorkspaceRole.VIEWER),
            WorkspaceRole.OWNER,
        )
        self.assertEqual(
            effective_workspace_role(owner_id, member_id, WorkspaceRole.OWNER),
            WorkspaceRole.VIEWER,
        )
        self.assertEqual(
            effective_workspace_role(owner_id, member_id, WorkspaceRole.EDITOR),
            WorkspaceRole.EDITOR,
        )
        self.assertEqual(
            effective_workspace_role(owner_id, member_id, WorkspaceRole.VIEWER),
            WorkspaceRole.VIEWER,
        )
        self.assertIsNone(effective_workspace_role(owner_id, member_id, None))

    def test_role_permission_matrix(self) -> None:
        expected = {
            WorkspaceRole.OWNER: frozenset(WorkspacePermission),
            WorkspaceRole.EDITOR: frozenset(
                {
                    WorkspacePermission.TASK_READ,
                    WorkspacePermission.TASK_CREATE,
                    WorkspacePermission.TASK_UPDATE,
                    WorkspacePermission.TASK_DELETE,
                    WorkspacePermission.LABEL_READ,
                    WorkspacePermission.LABEL_CREATE,
                    WorkspacePermission.LABEL_UPDATE,
                    WorkspacePermission.LABEL_DELETE,
                    WorkspacePermission.TASK_LABEL_UPDATE,
                    WorkspacePermission.COMMENT_READ,
                    WorkspacePermission.COMMENT_CREATE,
                    WorkspacePermission.COMMENT_UPDATE,
                    WorkspacePermission.COMMENT_DELETE,
                    WorkspacePermission.WORKSPACE_READ,
                    WorkspacePermission.MEMBER_READ,
                }
            ),
            WorkspaceRole.VIEWER: frozenset(
                {
                    WorkspacePermission.TASK_READ,
                    WorkspacePermission.LABEL_READ,
                    WorkspacePermission.COMMENT_READ,
                    WorkspacePermission.WORKSPACE_READ,
                    WorkspacePermission.MEMBER_READ,
                }
            ),
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
            frozenset(WorkspacePermission) - {
                WorkspacePermission.TASK_READ,
                WorkspacePermission.LABEL_READ,
                WorkspacePermission.COMMENT_READ,
                WorkspacePermission.WORKSPACE_READ,
                WorkspacePermission.MEMBER_READ,
            },
        )
        read_permissions = frozenset(WorkspacePermission) - WORKSPACE_WRITE_PERMISSIONS
        self.assertEqual(
            read_permissions,
            frozenset(
                {
                    WorkspacePermission.TASK_READ,
                    WorkspacePermission.LABEL_READ,
                    WorkspacePermission.COMMENT_READ,
                    WorkspacePermission.WORKSPACE_READ,
                    WorkspacePermission.MEMBER_READ,
                }
            ),
        )
        for permission in WorkspacePermission:
            with self.subTest(permission=permission):
                self.assertEqual(
                    is_workspace_write_permission(permission),
                    permission in WORKSPACE_WRITE_PERMISSIONS,
                )
