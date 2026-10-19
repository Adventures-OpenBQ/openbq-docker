"""Pure configuration and recognized legacy-format boundaries (real parser/files)."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from openbq_settings_pg.config import Config, SettingsUnavailable, backend, connection_info
from openbq_settings_pg.private_state import valid_json
from openbq_settings_pg.migrate_json import inventory, mapping

PRINCIPAL='aaaaaaaa-1111-4111-8111-111111111111'
STEM='a'*64


class Contracts(unittest.TestCase):
    def test_javascript_json_values_and_raw_decoder(self):
        for raw in (b'1'*5000, b'1e999999', b'null', b'false', b'[]', b'"\xff"', b' {"x":1,"x":2} '):
            valid_json(raw)
        for raw in (b'NaN',b'Infinity',b'-Infinity',b'[1,]',b'\xef\xbb\xbf{}',b'{}{}'):
            with self.assertRaises(ValueError):valid_json(raw)

    def test_deep_json_keeps_javascript_syntax_without_recursive_decoding(self):
        for raw in (b'['*100000+b'0'+b']'*100000, b'{"x":'*30000+b'false'+b'}'*30000):
            valid_json(raw)
            with self.assertRaises(ValueError):valid_json(raw[:-1])
        for raw in (b'[1,]',b'{"x":}',b'{1:2}',b'01',b'1e',b'true false',b'{"x" 1}',b'[[] []]'):
            with self.assertRaises(ValueError):valid_json(raw)

    def test_explicit_configuration_and_secret_safe_repr_errors(self):
        env={'OPENBQ_SETTINGS_BACKEND':'postgresql','OPENBQ_SETTINGS_PRINCIPAL_ID':PRINCIPAL,
             'OPENBQ_SETTINGS_DSN':"host=fixture dbname=openbq_settings user=openbq_settings_runtime password='secret@:/%?#' connect_timeout=3 sslmode=verify-full sslrootcert=/tls/ca.crt",
             'OPENBQ_SETTINGS_GATEWAY_STATE':'1','GATEWAY_TOKEN':'fixture_token_1234567890_1234567890'}
        with patch.dict(os.environ,env,clear=True):
            config=Config.read();self.assertNotIn('secret',repr(config));self.assertNotIn('fixture_token',repr(config))
            self.assertIn('sslmode=verify-full',config.dsn)
            self.assertIn('secret@:/%?#',config.dsn)
        for key,value in [('OPENBQ_SETTINGS_BACKEND',''),('OPENBQ_SETTINGS_PRINCIPAL_ID','wrong'),
                          ('OPENBQ_SETTINGS_DSN','password=secret'),('GATEWAY_TOKEN','short'),('PGHOST','inherited'),('WEB_CONCURRENCY','2')]:
            with patch.dict(os.environ,{**env,key:value},clear=True):
                with self.assertRaises(SettingsUnavailable) as caught:Config.read()
                self.assertEqual(str(caught.exception),'Settings unavailable')
        with patch.dict(os.environ,{},clear=True):self.assertEqual(backend(),'file')

    def test_configured_ca_defaults_to_verify_full(self):
        from psycopg.conninfo import conninfo_to_dict
        base='host=fixture dbname=openbq_settings user=openbq_settings_runtime connect_timeout=3'
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(conninfo_to_dict(connection_info(base+' sslrootcert=/tls/ca.crt'))['sslmode'],'verify-full')
            self.assertEqual(conninfo_to_dict(connection_info(base))['sslmode'],'require')

    def test_inventory_raw_bytes_and_refused_ambiguous_or_unknown_sources(self):
        with tempfile.TemporaryDirectory() as root:
            source=Path(root)/'source';(source/'keys').mkdir(parents=True);(source/'state'/'00042').mkdir(parents=True)
            raw=b' {"x":1,"x":2,"n":1e2} '
            (source/'keys'/(STEM+'.json')).write_bytes(raw)
            browser=source/'state'/'00042'/'dashboards%2Fopaque.json';browser.write_bytes(b'"\xff"')
            documents,manifest=inventory(source,{STEM:PRINCIPAL})
            self.assertEqual(documents[('key',PRINCIPAL,'settings')],raw)
            self.assertEqual(documents[('github','00042','dashboards/opaque.json')],b'"\xff"')
            unknown=source/'unknown.json';unknown.write_text('{}')
            with self.assertRaises(Exception):inventory(source,{STEM:PRINCIPAL})
            unknown.unlink();unknown.symlink_to(browser)
            with self.assertRaises(Exception):inventory(source,{STEM:PRINCIPAL})
            unknown.unlink()
            with self.assertRaises(Exception):inventory(source,{})
            browser.write_bytes(b'x'*262145)
            with self.assertRaises(Exception):inventory(source,{STEM:PRINCIPAL})
            mapping_file=Path(root)/'mapping.json';mapping_file.write_text(json.dumps({STEM:PRINCIPAL,'b'*64:PRINCIPAL}))
            with self.assertRaises(Exception):mapping(mapping_file)
            mapping_file.write_text('{"'+STEM+'":"'+PRINCIPAL+'","'+STEM+'":"bbbbbbbb-1111-4111-8111-111111111111"}')
            with self.assertRaises(Exception):mapping(mapping_file)

    def test_key_inventory_refuses_encodings_unreadable_by_legacy(self):
        for encoding in ('utf-8-sig', 'utf-16', 'utf-32'):
            with self.subTest(encoding=encoding), tempfile.TemporaryDirectory() as root:
                source=Path(root); (source/'keys').mkdir()
                path=source/'keys'/(STEM+'.json')
                raw='{"extension":{"label":"café 雪","number":1e2}}'.encode(encoding)
                path.write_bytes(raw)
                with self.assertRaises((ValueError, UnicodeError)):inventory(source,{STEM:PRINCIPAL})
                self.assertEqual(path.read_bytes(),raw)


if __name__=='__main__': unittest.main()
