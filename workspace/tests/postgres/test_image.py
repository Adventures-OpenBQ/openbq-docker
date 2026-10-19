# Copyright 2026 SecretoftheUniverse.com LLC. Apache-2.0.
"""Mandatory real compiled-image database probes; synthetic dedicated DB only."""
import asyncio
from datetime import datetime
import secrets
import unittest
from uuid import uuid4

from sqlalchemy import text
from api import database
from api.models import model_helpers
from api.worker_tasks import WriteSession
from utilities import config


class ImageDatabaseTests(unittest.TestCase):
    def test_packaged_message_enum_matches_migrated_type_and_compiled_login_query(self):
        from api import models
        from api.models import tauri_models
        from pathlib import Path
        from routers.pro import helpers
        from routers.pro.helpers import get_user_questions_history
        # Exact-pin setup_compile.py excludes this Pydantic model module.
        self.assertEqual(Path(tauri_models.__file__),Path('/opt/code/api/models/tauri_models.py'))
        self.assertTrue(helpers.__file__.endswith('.so'))
        engine=config.settings.get_read_engine()
        try:
            with engine.connect() as c:
                labels=c.exec_driver_sql("SELECT enumlabel FROM pg_enum e JOIN pg_type t ON t.oid=e.enumtypid WHERE t.typname='message_role' ORDER BY enumsortorder").scalars().all()
        finally:engine.dispose()
        self.assertEqual(models.ChatMessages.role.type.enums,labels)
        self.assertEqual(models.ChatMessages.role.type.name,'message_role')
        async def query():
            manager=config.settings.get_read_session()
            try:
                async with manager.session() as session:
                    self.assertEqual(await get_user_questions_history(session,uuid4()),[])
            finally:await manager.close()
        asyncio.run(query())

    def test_actual_compiled_module_identity(self):
        for module in (database, model_helpers, config):
            self.assertTrue(module.__file__.endswith('.so'), 'test requires the actual compiled image')

    def test_identity_validation_preserves_arbitrary_text_aes_keys(self):
        import os
        from api.aes import AESCipher
        from scripts.workspace_pg import validate_keys
        original=os.environ['OPENBB_AES_KEY']
        try:
            for key in ('short','非ASCII key of arbitrary length'):
                os.environ['OPENBB_AES_KEY']=key
                cipher=AESCipher(key)
                self.assertEqual(cipher.decrypt(cipher.encrypt('synthetic roundtrip')),'synthetic roundtrip')
                validate_keys()
        finally:os.environ['OPENBB_AES_KEY']=original

    def test_actual_sync_and_async_tls_special_credentials(self):
        import os
        async def connect_async(settings):
            manager=settings.get_read_session()
            try:
                async with manager.session() as session:
                    self.assertEqual((await session.execute(text('SELECT 1'))).scalar_one(),1)
            finally:await manager.close()
        def connect_sync(settings):
            engine=settings.get_read_engine()
            try:
                with engine.connect() as c:self.assertEqual(c.exec_driver_sql('SELECT 1').scalar_one(),1)
            finally:engine.dispose()
        base=config.settings.model_dump()
        base['SSL_CA']='/fixture/tls/ca.crt'
        if os.environ.get('WORKSPACE_SPECIAL_DB_USER'):
            base['READ_DB_USER']=os.environ['WORKSPACE_SPECIAL_DB_USER']
        valid=config.DatabaseSettings(**base)
        connect_sync(valid);asyncio.run(connect_async(valid))
        for overrides in ({'SSL_CA':'/fixture/tls/untrusted.crt'},
                          {'DB_HOST':os.environ['WORKSPACE_BAD_TLS_HOST']},
                          {'SSL_CERT':'/fixture/tls/server.crt','SSL_KEY':None}):
            invalid=config.DatabaseSettings(**{**base,**overrides})
            for function in (connect_sync,lambda settings:asyncio.run(connect_async(settings))):
                try:function(invalid)
                except Exception:pass
                else:self.fail('TLS verification failed open')

    def test_real_pool_acquisition_statement_timeouts_and_disposal(self):
        from contextlib import AsyncExitStack
        from time import monotonic
        from sqlalchemy.exc import TimeoutError as PoolTimeout
        settings=config.DatabaseSettings(**{**config.settings.model_dump(),
            'DB_POOL_TIMEOUT':1,'DB_STATEMENT_TIMEOUT':100,'DB_LOCK_TIMEOUT':100})
        for factory in (settings.get_read_engine,settings.get_write_engine):
            engine=factory()
            try:
                self.assertEqual(engine.pool.size(),2)
                with engine.connect() as first,engine.connect() as second:
                    self.assertEqual(first.exec_driver_sql('SHOW statement_timeout').scalar_one(),'100ms')
                    self.assertEqual(first.exec_driver_sql('SHOW lock_timeout').scalar_one(),'100ms')
                    started=monotonic()
                    with self.assertRaises(PoolTimeout):engine.connect()
                    self.assertGreaterEqual(monotonic()-started,.9)
                    self.assertLess(monotonic()-started,3)
                with engine.connect() as connection:
                    with self.assertRaises(Exception):connection.exec_driver_sql('SELECT pg_sleep(1)')
            finally:engine.dispose()
            self.assertEqual(engine.pool.checkedout(),0)
        async def run():
            for factory in (settings.get_read_session,settings.get_write_session,settings.get_validate_user_session):
                manager=factory()
                try:
                    async with AsyncExitStack() as stack:
                        for _ in range(2):
                            session=await stack.enter_async_context(manager.session())
                            await session.execute(text('SELECT 1'))
                        started=monotonic()
                        with self.assertRaises(PoolTimeout):
                            async with manager.session() as third:await third.execute(text('SELECT 1'))
                        self.assertGreaterEqual(monotonic()-started,.9)
                        self.assertLess(monotonic()-started,3)
                    async with manager.session() as session:
                        with self.assertRaises(Exception):await session.execute(text('SELECT pg_sleep(1)'))
                finally:await manager.close()
        asyncio.run(run())

    def test_actual_lock_timeout_and_dead_connection_recovery(self):
        from time import monotonic
        settings=config.DatabaseSettings(**{**config.settings.model_dump(),
            'DB_LOCK_TIMEOUT':100,'DB_STATEMENT_TIMEOUT':1000})
        engine=settings.get_write_engine();killer=settings.get_write_engine()
        try:
            with engine.connect() as first,engine.connect() as second:
                first.exec_driver_sql('UPDATE tier SET has_trial=has_trial')
                started=monotonic()
                with self.assertRaises(Exception) as caught:
                    second.exec_driver_sql('UPDATE tier SET has_trial=has_trial')
                self.assertEqual(caught.exception.orig.pgcode,'55P03')
                self.assertGreaterEqual(monotonic()-started,.08)
                self.assertLess(monotonic()-started,1)
                first.rollback();second.rollback()
            engine.dispose()
            with engine.connect() as victim:pid=victim.exec_driver_sql('SELECT pg_backend_pid()').scalar_one()
            with killer.connect() as c:self.assertTrue(c.exec_driver_sql('SELECT pg_terminate_backend(%s)',(pid,)).scalar_one())
            with engine.connect() as reconnected:
                self.assertNotEqual(reconnected.exec_driver_sql('SELECT pg_backend_pid()').scalar_one(),pid)
        finally:engine.dispose();killer.dispose()
        async def recover():
            manager=settings.get_write_session();terminator=settings.get_write_engine()
            try:
                async with manager.session() as victim:
                    pid=(await victim.execute(text('SELECT pg_backend_pid()'))).scalar_one()
                with terminator.connect() as c:self.assertTrue(c.exec_driver_sql('SELECT pg_terminate_backend(%s)',(pid,)).scalar_one())
                async with manager.session() as reconnected:
                    self.assertNotEqual((await reconnected.execute(text('SELECT pg_backend_pid()'))).scalar_one(),pid)
            finally:await manager.close();terminator.dispose()
        asyncio.run(recover())

    def test_runtime_roles_cannot_ddl_select_owner_or_cross_application(self):
        for factory,read_only in ((config.settings.get_read_engine,True),(config.settings.get_write_engine,False)):
            engine=factory()
            try:
                with engine.connect() as connection:
                    for statement in ('CREATE TABLE public.forbidden_fixture(value integer)',
                                      'SET ROLE openbq_workspace_owner',
                                      'SELECT * FROM workspace_admin.migration_runs'):
                        with self.assertRaises(Exception):connection.exec_driver_sql(statement)
                        connection.rollback()
                    if read_only:
                        with self.assertRaises(Exception):connection.exec_driver_sql('UPDATE public.tier SET has_trial=has_trial')
                        connection.rollback()
                    for database_name in ('openbq_settings_isolation','temporal_catalog_isolation'):
                        self.assertFalse(connection.exec_driver_sql('SELECT has_database_privilege(current_user,%s,\'CONNECT\')',(database_name,)).scalar_one())
            finally:engine.dispose()

    def test_both_message_timestamps_preserve_microseconds_and_nulls(self):
        engine = config.settings.get_write_engine()
        try:
            with engine.connect() as c:
                txn = c.begin()
                chat,user=c.exec_driver_sql('SELECT uuid,user_uuid FROM copilot_chat LIMIT 1').one()
                wanted = datetime(2026,1,2,3,4,5,123456)
                for updated in (wanted, None):
                    values = (str(user),str(chat),'human',str(uuid4()),wanted,updated)
                    got = c.exec_driver_sql('INSERT INTO copilot_messages(user_uuid,chat_uuid,role,uuid,created_date,updated_date) VALUES (%s,%s,%s,%s,%s,%s) RETURNING created_date,updated_date',values).one()
                    self.assertEqual(tuple(got), (wanted, updated))
                txn.rollback()
        finally:
            engine.dispose()

    def test_real_slow_query_never_logs_sql_or_bound_values(self):
        async def run():
            marker = 'workspace_synthetic_' + secrets.token_hex(16)
            async with database.AsyncReadSessionLocal.session() as session:
                await session.execute(text('SELECT pg_sleep(5.1), :private_value'), {'private_value': marker})
            await asyncio.sleep(2)
            engine = config.settings.get_write_engine()
            try:
                with engine.begin() as c:
                    rows = c.exec_driver_sql("SELECT error FROM log WHERE request='query_threshold'").scalars().all()
                    c.exec_driver_sql("DELETE FROM log WHERE request='query_threshold'")
                self.assertTrue(rows, 'actual logging hook was not exercised')
                self.assertTrue(all(marker not in row and 'pg_sleep' not in row for row in rows))
            finally:
                engine.dispose()
                await database.AsyncReadSessionLocal.close()
                await database.AsyncWriteSessionLocal.close()
                WriteSession.close()
                WriteSession.bind.dispose()
        asyncio.run(run())


if __name__ == '__main__':
    unittest.main(verbosity=2)
