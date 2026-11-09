"""Opt-in data-preserving conversion for pre-review Day 2 databases."""

from __future__ import annotations

import argparse
import asyncio
import logging

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app.db.legacy_upgrade import upgrade_legacy_schema

logger = logging.getLogger("taskhub.legacy_upgrade")


async def run(database_url: str, apply: bool, allow_non_test_database: bool) -> None:
    database = make_url(database_url).database
    if not database or (not database.endswith("_test") and not allow_non_test_database):
        raise SystemExit(
            "Refusing target without _test suffix; pass explicit opt-in to proceed"
        )
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            if not apply:
                from app.db.legacy_upgrade import _preflight

                revision = await _preflight(connection)
                logger.info(
                    "Preflight passed for %s at %s; no writes made", database, revision
                )
                return
            revision = await upgrade_legacy_schema(connection)
            logger.info("Converted %s to %s; transaction committed", database, revision)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--allow-non-test-database", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.database_url, args.apply, args.allow_non_test_database))


if __name__ == "__main__":
    main()
