# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The exporter emits only named day operations when machine credentials exist."""
import importlib.util
from datetime import date, datetime
from pathlib import Path
import secrets
import sys
import types

import pandas as pd
import pytest


def exporter():
    path = Path(__file__).resolve().parents[1] / "eod_dump.py"
    spec = importlib.util.spec_from_file_location("qualified_eod", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_secured_export_writes_the_named_day_slice_to_parquet(tmp_path, monkeypatch):
    from openbq_kdb import protocol

    token = tmp_path / "token"
    token.write_text(secrets.token_urlsafe(48))
    token.chmod(0o600)
    monkeypatch.setenv("KDB_USERNAME", "eod-export")
    monkeypatch.setenv("KDB_PASSWORD_FILE", str(token))
    frame = pd.DataFrame({"time": [datetime(2026, 11, 20, 14, 30)], "sym": ["AAPL"],
                          "price": [123.0], "size": [2.0]})

    class Symbol(str):
        pass

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def __call__(self, dispatcher, operation, args, request_id, **kwargs):
            assert isinstance(dispatcher, Symbol) and dispatcher == ".openbq.rpc"
            assert args[:2] == [datetime(2026, 11, 20), datetime(2026, 11, 21)]
            if operation == "dayCount":
                return types.SimpleNamespace(py=lambda: 1)
            assert operation == "daySlice" and args[2:] == [0, 250_000]
            return types.SimpleNamespace(pd=lambda: frame)

    def connection(host, port, credentials):
        assert credentials.username == "eod-export"
        return Connection()

    monkeypatch.setattr(protocol, "connect_qualified", connection)
    fake_kx = types.SimpleNamespace(SymbolAtom=Symbol, CharVector=str, List=list,
                                   TimestampAtom=object, toq=lambda value, kind: value)
    monkeypatch.setitem(sys.modules, "pykx", fake_kx)
    output = tmp_path / "day.parquet"
    exporter()._stage_day(date(2026, 11, 20), str(output))
    assert pd.read_parquet(output).to_dict("records") == frame.to_dict("records")


def test_incomplete_identity_configuration_does_not_fall_back_to_legacy(tmp_path, monkeypatch):
    from openbq_kdb.credentials import CredentialConfigurationError

    monkeypatch.setenv("KDB_USERNAME", "eod-export")
    monkeypatch.delenv("KDB_PASSWORD_FILE", raising=False)
    with pytest.raises(CredentialConfigurationError):
        exporter()._stage_day(date(2026, 11, 20), str(tmp_path / "day.parquet"))
