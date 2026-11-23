"""Exact handler bodies with real SQLite/filesystem/logs; no HTTP-auth claim."""
import ast
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from loguru import logger
from sqlalchemy import ForeignKey, String, delete, event, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from starlette.responses import JSONResponse

ROOT = Path(os.environ['WORKSPACE_BACKEND_ROOT'])
if not (ROOT / 'routers/pro/data_connectors.py').is_file():
    raise RuntimeError('Mount the pinned or assembled source; the lite runtime contains Cython binaries.')


def function(relative_path, name, namespace):
    path = ROOT / relative_path
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    node.decorator_list = []
    node.returns = None
    node.args.defaults = [ast.Constant(None) for _ in node.args.defaults]
    node.args.kw_defaults = [ast.Constant(None) if n else None for n in node.args.kw_defaults]
    for arg in [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs, node.args.vararg, node.args.kwarg]:
        if arg:
            arg.annotation = None
    scope = dict(namespace)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(path), 'exec'), scope)
    return scope[name]


class Base(DeclarativeBase):
    pass


class FileWidget(Base):
    # Relevant production query fields; actual SQLite enforces StoredFile cascade.
    __tablename__ = 'file_widget'
    uuid: Mapped[str] = mapped_column(String, primary_key=True)
    user_uuid: Mapped[str] = mapped_column(String)


class StoredFile(Base):
    __tablename__ = 'stored_file'
    uuid: Mapped[str] = mapped_column(String, primary_key=True)
    file_widget_uuid: Mapped[str | None] = mapped_column(ForeignKey('file_widget.uuid', ondelete='CASCADE'))
    bucket: Mapped[str] = mapped_column(String)
    s3_file_name: Mapped[str] = mapped_column(String)


class FileOwnership(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'owner-file.csv'
        self.path.write_text('value\n12\n')
        self.engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        @event.listens_for(self.engine.sync_engine, 'connect')
        def foreign_keys(connection, _):
            cursor = connection.cursor(); cursor.execute('PRAGMA foreign_keys=ON'); cursor.close()
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.db = AsyncSession(self.engine, expire_on_commit=False)
        self.db.add(FileWidget(uuid='owner-widget', user_uuid='owner-A'))
        await self.db.commit()
        self.db.add(StoredFile(uuid='stored-file', file_widget_uuid='owner-widget', bucket='local', s3_file_name=self.path.name))
        await self.db.commit()
        self.storage_calls = []
        async def delete_bytes(bucket, name):
            self.storage_calls.append((bucket, name))
            try:
                (Path(self.directory.name) / name).unlink()
                return True
            except FileNotFoundError:
                return False
        self.route = function('routers/pro/data_connectors.py', 'delete_user_file_widget', {
            'select':select, 'delete':delete, 'FileWidget':FileWidget, 'StoredFile':StoredFile,
            'FileStorage':SimpleNamespace(delete_file=delete_bytes), 'HTTPException':HTTPException,
        })

    async def asyncTearDown(self):
        await self.db.close(); await self.engine.dispose(); self.directory.cleanup()

    async def test_other_owner_is_refused_before_bytes_or_rows_change(self):
        try:
            await self.route('owner-widget', SimpleNamespace(uuid='owner-B'), self.db)
        except HTTPException as error:
            self.assertEqual(error.status_code, 404)
        else:
            self.fail('Non-owner delete returned success')
        self.assertTrue(self.path.exists())
        self.assertEqual(self.storage_calls, [])
        self.assertIsNotNone(await self.db.get(FileWidget, 'owner-widget'))
        self.assertEqual((await self.db.get(StoredFile, 'stored-file')).file_widget_uuid, 'owner-widget')

    async def test_missing_widget_uses_the_same_refusal_without_mutations(self):
        with self.assertRaises(HTTPException) as raised:
            await self.route('missing-widget', SimpleNamespace(uuid='owner-B'), self.db)
        self.assertEqual(raised.exception.status_code, 404)
        self.assertTrue(self.path.exists()); self.assertEqual(self.storage_calls, [])

    async def test_owner_delete_removes_own_bytes_widget_and_cascaded_record(self):
        self.assertEqual(await self.route('owner-widget', SimpleNamespace(uuid='owner-A'), self.db), {'success':True})
        self.assertFalse(self.path.exists())
        self.assertEqual(len(self.storage_calls), 1)
        self.db.expire_all()
        self.assertIsNone(await self.db.get(FileWidget, 'owner-widget'))
        self.assertIsNone(await self.db.get(StoredFile, 'stored-file'))

    async def test_owner_can_remove_widget_without_a_stored_record(self):
        await self.db.execute(delete(StoredFile)); await self.db.commit(); self.path.unlink()
        self.assertEqual(await self.route('owner-widget', SimpleNamespace(uuid='owner-A'), self.db), {'success':True})
        self.assertEqual(self.storage_calls, [])
        self.assertIsNone(await self.db.get(FileWidget, 'owner-widget'))

    async def test_missing_bytes_preserve_the_established_detached_record(self):
        self.path.unlink()
        self.assertEqual(await self.route('owner-widget', SimpleNamespace(uuid='owner-A'), self.db), {'success':True})
        self.assertIsNone(await self.db.get(FileWidget, 'owner-widget'))
        self.assertIsNone((await self.db.get(StoredFile, 'stored-file')).file_widget_uuid)


class SecretSafeLogs(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.records = []
        logger.remove()
        self.sink = logger.add(lambda message:self.records.append(message.record), format='{message}')

    def tearDown(self):
        logger.remove(self.sink)

    def test_request_headers_are_not_logged(self):
        secrets = ['synthetic-session-token','synthetic-cookie-token','synthetic-openbb-token']
        request = Request({'type':'http','method':'GET','path':'/api/example','query_string':b'','headers':[
            (b'authorization',('Bearer '+secrets[0]).encode()),
            (b'cookie',('session='+secrets[1]).encode()),
            (b'x-openbb-authorization',('Bearer '+secrets[2]).encode()),
            (b'user-agent',b'QA-test')], 'client':('127.0.0.1',5000)})
        target = function('api/rate_limit.py','get_remote_address_w_logging',{'logger':logger,'get_remote_address':lambda request:'127.0.0.1'})
        self.assertEqual(target(request),'127.0.0.1')
        text='\n'.join(r['message'] for r in self.records)
        self.assertTrue(self.records)
        for secret in secrets:self.assertNotIn(secret,text)

    async def validation(self, consumed):
        secret='synthetic-password-input'
        async def receive():return {'type':'http.request','body':json.dumps({'password':secret}).encode(),'more_body':False}
        request=Request({'type':'http','method':'POST','path':'/api/example','query_string':b'','headers':[]}, receive)
        request._stream_consumed=consumed
        error=RequestValidationError([{'type':'value_error','loc':('body','password'),'msg':'Value error, invalid credential payload','input':secret}])
        target=function('main.py','validation_exception_handler',{'logger':logger,'JSONResponse':JSONResponse})
        response=await target(request,error)
        self.assertEqual(response.status_code,422)
        self.assertEqual(json.loads(response.body)['detail'],'invalid credential payload')
        self.assertTrue(self.records)
        self.assertNotIn(secret,'\n'.join(r['message'] for r in self.records))
        self.assertTrue(any(r['extra'].get('method')=='POST' and r['extra'].get('path')=='/api/example' and r['extra'].get('status_code')==422 for r in self.records))

    async def test_validation_body_and_inputs_are_not_logged(self):
        await self.validation(False)

    async def test_consumed_body_does_not_expose_validation_input(self):
        await self.validation(True)

    def test_rate_limiter_initialization_does_not_log_storage_credentials(self):
        path=ROOT/'api/rate_limit.py';tree=ast.parse(path.read_text())
        calls=[n for n in tree.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Attribute) and isinstance(n.value.func.value,ast.Name) and n.value.func.value.id=='logger' and n.value.func.attr=='info']
        self.assertTrue(calls)
        secret='synthetic-redis-password'
        exec(compile(ast.fix_missing_locations(ast.Module(body=calls,type_ignores=[])),str(path),'exec'),{'logger':logger,'storage_uri':'redis://:'+secret+'@redis:6379/0'})
        self.assertNotIn(secret,'\n'.join(r['message'] for r in self.records))


class DisabledProxy(unittest.TestCase):
    def tree(self):return ast.parse((ROOT/'routers/pro/index.py').read_text())

    def test_no_network_forwarding_route_is_registered(self):
        routes=[]
        for node in self.tree().body:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if isinstance(decorator,ast.Call) and decorator.args and isinstance(decorator.args[0],ast.Constant) and decorator.args[0].value=='/mcp-proxy':routes.append(node.name)
        self.assertEqual(routes,[])

    def test_unused_global_proxy_client_is_not_constructed(self):
        names=[target.id for node in self.tree().body if isinstance(node,ast.Assign) for target in node.targets if isinstance(target,ast.Name)]
        self.assertNotIn('mcp_proxy_client',names)


if __name__=='__main__':unittest.main(verbosity=2)
