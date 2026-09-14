"""Upgrade an existing v2 database, retaining saved searches."""

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text, inspect


class MigrationTests(unittest.TestCase):
    def test_upgrade_preserves_existing_search(self):
        with tempfile.TemporaryDirectory() as tmp:
            url = "sqlite:///" + str(Path(tmp) / "migration.db")
            with patch.dict(os.environ, {"DATABASE_URL": url}):
                config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
                command.upgrade(config, "0001_initial")
                engine = create_engine(url)
                with engine.begin() as connection:
                    connection.execute(
                        text(
                            "INSERT INTO searches(name,origin,destinations,departure_from,departure_to,return_from,return_to) VALUES ('Preserved','BCN','[\"EZE\"]','2026-11-25','2026-11-25','2027-01-02','2027-01-02')"
                        )
                    )
                command.upgrade(config, "head")
                with engine.connect() as connection:
                    row = connection.execute(
                        text(
                            "SELECT name,currency,strategy,max_combinations FROM searches"
                        )
                    ).one()
                    self.assertEqual(tuple(row), ("Preserved", "EUR", "waterfall", 12))
                    self.assertIn("query_cache", inspect(connection).get_table_names())
                engine.dispose()
