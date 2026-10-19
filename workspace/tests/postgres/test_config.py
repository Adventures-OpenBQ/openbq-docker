# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Run inside the pinned dependency/runtime image; no database needed here."""
import asyncio
import os
import unittest

# Generated synthetic configuration; never operator environment or credentials.
os.environ.update(DATABASE_TYPE="postgresql", DB_HOST="localhost", DB_PORT="5432",
                  DB_NAME="fixture", READ_DB_USER="fixture", WRITE_DB_USER="fixture",
                  **{'READ_DB_PASSWORD':'fixture', 'WRITE_DB_PASSWORD':'fixture'},
                  OPENBB_AES_KEY="0123456789abcdef", JWT_SECRET="fixture" * 12,
                  DB_POOL_SIZE="2", DB_MAX_OVERFLOW="0", WORKERS="1")
from sqlalchemy.engine import make_url
from utilities.config import DatabaseSettings, DatabaseEngineSettings


class ConfigTests(unittest.TestCase):
    def settings(self, password="fixture", **kwargs):
        kwargs.setdefault("WORKSPACE_POSTGRES_ALLOW_PLAINTEXT", True)  # TLS-free unit fixture
        return DatabaseSettings(DATABASE_TYPE="postgresql", DB_HOST="localhost", DB_PORT=5432,
            DB_NAME="fixture", READ_DB_USER="fixture", WRITE_DB_USER="fixture",
            **{'READ_DB_PASSWORD':password, 'WRITE_DB_PASSWORD':password}, **kwargs)

    def test_url_components_survive_both_driver_factories(self):
        for password in ("@:/%?#", "psycopg2/pymysql@%40", "百分比%2F@:"):
            with self.subTest(case=len(password)):
                config = self.settings(password)
                try:
                    url = make_url(config.get_write_url())
                    self.assertTrue(url.password == password, "sync credential changed")
                    session = config.get_write_session()
                    self.assertTrue(session._engine.url.password == password, "async credential changed")
                    self.assertEqual(session._engine.url.drivername, "postgresql+asyncpg")
                    asyncio.run(session.close())
                except (ValueError, TypeError):
                    self.fail("structured credential construction failed")

    def test_each_factory_keeps_bounded_pool_and_explicit_zero_overflow(self):
        config = self.settings()
        for factory in (config.get_read_engine, config.get_write_engine,
                        config.get_read_session, config.get_write_session, config.get_validate_user_session):
            engine_or_session = factory(DatabaseEngineSettings(pool_size=2, max_overflow=0, pool_timeout=30))
            engine = getattr(engine_or_session, "_engine", engine_or_session)
            try:
                self.assertEqual(engine.pool.size(), 2)
                self.assertEqual(engine.pool._max_overflow, 0)
                self.assertEqual(engine.pool.timeout(), 30)
                self.assertTrue(getattr(engine, "sync_engine", engine).hide_parameters)
            finally:
                if hasattr(engine_or_session, "_engine"):
                    asyncio.run(engine_or_session.close())
                else:
                    engine.dispose()

    def test_instance_defaults_are_not_overridden_by_global_settings(self):
        config=self.settings(DB_POOL_SIZE=3,DB_MAX_OVERFLOW=0,DB_POOL_TIMEOUT=1)
        for factory in (config.get_read_engine,config.get_write_engine,
                        config.get_read_session,config.get_write_session,config.get_validate_user_session):
            value=factory()
            engine=getattr(value,'_engine',value)
            try:
                self.assertEqual(engine.pool.size(),3)
                self.assertEqual(engine.pool.timeout(),1)
                self.assertEqual(engine.pool._max_overflow,0)
            finally:
                if hasattr(value,'_engine'):asyncio.run(value.close())
                else:engine.dispose()

    def test_sync_factory_uses_libpq_supported_connect_arguments(self):
        engine = self.settings().get_write_engine()
        try:
            # SQLAlchemy exposes effective driver arguments through its connect event.
            connection_creator = engine.pool._creator
            args = dict(zip(connection_creator.__code__.co_freevars,
                            [cell.cell_contents for cell in connection_creator.__closure__]))["cparams"]
            self.assertNotIn("ssl", args)
            self.assertGreater(args.get("connect_timeout", 0), 0)
            self.assertIn("statement_timeout", args.get("options", ""))
            self.assertIn("lock_timeout", args.get("options", ""))
        finally:
            engine.dispose()

    def test_missing_tls_material_refuses_every_factory_without_plaintext_opt_out(self):
        config = self.settings(WORKSPACE_POSTGRES_ALLOW_PLAINTEXT=False)
        for factory in (config.get_read_engine, config.get_write_engine,
                        config.get_read_session, config.get_write_session, config.get_validate_user_session):
            with self.subTest(factory=factory.__name__):
                with self.assertRaisesRegex(ValueError, "WORKSPACE_POSTGRES_ALLOW_PLAINTEXT"):
                    factory()

    def test_invalid_pool_limits_are_rejected(self):
        for invalid in ({"DB_POOL_SIZE": 0}, {"DB_MAX_OVERFLOW": -1}, {"DB_POOL_TIMEOUT": 0}):
            with self.subTest(field=next(iter(invalid))):
                with self.assertRaises(ValueError):
                    self.settings(**invalid)


if __name__ == "__main__":
    unittest.main(verbosity=2)
