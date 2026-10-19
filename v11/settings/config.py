"""Private, explicit libpq configuration; errors never include input values."""
from dataclasses import dataclass, field
import os
import re
import uuid


class SettingsUnavailable(Exception):
    def __init__(self):
        super().__init__("Settings unavailable")


def backend():
    value = os.environ.get("OPENBQ_SETTINGS_BACKEND", "file")
    if value not in ("file", "postgresql"):
        raise SettingsUnavailable()
    return value


def connection_info(value):
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    try:
        values = conninfo_to_dict(value)
        if any(os.environ.get(k) for k in os.environ if k.startswith("PG")):
            raise ValueError()
        if not all(values.get(k) for k in ("dbname", "user", "host", "connect_timeout")):
            raise ValueError()
        if not 1 <= int(values["connect_timeout"]) <= 10 or values.get("service"):
            raise ValueError()
        # Explicit values prevent ambient libpq defaults changing the endpoint.
        values.setdefault("port", "5432")
        values.setdefault("sslmode", "verify-full" if values.get("sslrootcert") else "require")
        values["application_name"] = "openbq-settings"
        values["options"] = "-c search_path=pg_catalog -c statement_timeout=8000 -c lock_timeout=5000 -c idle_in_transaction_session_timeout=10000"
        return make_conninfo(**values)
    except Exception:
        raise SettingsUnavailable() from None


@dataclass(frozen=True)
class Config:
    dsn: str = field(repr=False)
    principal: str
    gateway: bool
    token: str = field(repr=False)

    @classmethod
    def read(cls):
        try:
            if backend() != "postgresql":
                raise ValueError()
            if os.environ.get("WEB_CONCURRENCY", "1") != "1":
                raise ValueError()
            principal = os.environ["OPENBQ_SETTINGS_PRINCIPAL_ID"]
            if str(uuid.UUID(principal)) != principal:
                raise ValueError()
            gateway = os.environ.get("OPENBQ_SETTINGS_GATEWAY_STATE", "0")
            if gateway not in ("0", "1"):
                raise ValueError()
            token = os.environ.get("GATEWAY_TOKEN", "")
            if gateway == "1" and not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
                raise ValueError()
            return cls(connection_info(os.environ["OPENBQ_SETTINGS_DSN"]), principal, gateway == "1", token)
        except Exception:
            raise SettingsUnavailable() from None
