"""Tests for shared pagination request and response schemas."""

import unittest

from pydantic import ValidationError

from app.schemas.common import Page, PaginationParams


class PaginationSchemaTests(unittest.TestCase):
    def test_defaults_bounds_and_generic_page(self) -> None:
        self.assertEqual(PaginationParams().model_dump(), {"offset": 0, "limit": 100})
        self.assertEqual(
            Page[str](items=["one"], total=3).model_dump(),
            {"items": ["one"], "total": 3},
        )

        for payload in ({"offset": -1}, {"limit": 0}, {"limit": 201}):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                PaginationParams.model_validate(payload)

