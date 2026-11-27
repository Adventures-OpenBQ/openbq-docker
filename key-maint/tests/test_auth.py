# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the GNU Affero General Public License, version 3 only.
# SPDX-License-Identifier: AGPL-3.0-only

import base64

import pytest

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import make_guard


def app_with_guard(auth_file: str) -> TestClient:
    app = FastAPI()

    @app.get("/ping", dependencies=[Depends(make_guard(auth_file))])
    def ping():
        return {"ok": True}

    return TestClient(app)


def basic(user, pw):
    tok = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {tok}"}


def write_auth(tmp_path, user="u1", pw="p1"):
    p = tmp_path / "api-auth.env"
    p.write_text(f"OPENBB_API_AUTH=true\nOPENBB_API_USERNAME={user}\nOPENBB_API_PASSWORD={pw}\n")
    return str(p)


class TestGuard:
    def test_no_header_401(self, tmp_path):
        c = app_with_guard(write_auth(tmp_path))
        assert c.get("/ping").status_code == 401

    def test_initial_utf8_bom_does_not_hide_auth_flag(self, tmp_path):
        p = tmp_path / "credentials.env"
        p.write_text(
            "\ufeffOPENBB_API_AUTH=true\nOPENBB_API_USERNAME=u1\nOPENBB_API_PASSWORD=p1\n",
            encoding="utf-8",
        )
        c = app_with_guard(str(p))
        assert c.get("/ping").status_code == 401
        assert c.get("/ping", headers=basic("u1", "p1")).status_code == 200

    def test_wrong_password_401(self, tmp_path):
        c = app_with_guard(write_auth(tmp_path))
        assert c.get("/ping", headers=basic("u1", "wrong")).status_code == 401

    def test_correct_credentials_200(self, tmp_path):
        c = app_with_guard(write_auth(tmp_path))
        assert c.get("/ping", headers=basic("u1", "p1")).status_code == 200

    def test_missing_auth_file_denies_all(self, tmp_path):
        c = app_with_guard(str(tmp_path / "absent.env"))
        assert c.get("/ping", headers=basic("u1", "p1")).status_code == 401


class TestFollowsTheApi:
    """OpenBQ's API is open unless OPENBB_API_AUTH is on; key-maint follows it."""

    def test_open_when_the_api_is_open(self, tmp_path):
        p = tmp_path / "credentials.env"
        p.write_text("OPENBB_API_AUTH=\nFRED_API_KEY=abc\n")
        assert app_with_guard(str(p)).get("/ping").status_code == 200

    def test_false_is_open(self, tmp_path):
        p = tmp_path / "credentials.env"
        p.write_text("OPENBB_API_AUTH=false\n")
        assert app_with_guard(str(p)).get("/ping").status_code == 200

    @pytest.mark.parametrize("flag", ['"true"', "'true'", 'true'])
    def test_quoted_auth_uses_the_decoded_credentials(self, tmp_path, flag):
        p = tmp_path / "credentials.env"
        p.write_text(
            f"OPENBB_API_AUTH={flag}\n"
            "OPENBB_API_USERNAME = 'u1' # comment\n"
            'OPENBB_API_PASSWORD=" has # comment \\" \\$tag $$suffix " # note\n'
        )
        c = app_with_guard(str(p))
        assert c.get("/ping").status_code == 401
        assert c.get("/ping", headers=basic("u1", ' has # comment " $tag $suffix ')).status_code == 200

    @pytest.mark.parametrize("flag", ['tru', '"tru"', '"false'])
    def test_unknown_or_unterminated_auth_flag_denies_access(self, tmp_path, flag):
        p = tmp_path / "credentials.env"
        p.write_text(f"OPENBB_API_AUTH={flag}\nOPENBB_API_USERNAME=u1\nOPENBB_API_PASSWORD=p1\n")
        c = app_with_guard(str(p))
        assert c.get("/ping").status_code == 401
        assert c.get("/ping", headers=basic("u1", "p1")).status_code == 401

    @pytest.mark.parametrize("assignment", ['OPENBB_API_AUTH = "true"', 'export OPENBB_API_AUTH=true'])
    def test_compose_assignment_forms_require_basic_auth(self, tmp_path, assignment):
        p = tmp_path / "credentials.env"
        p.write_text(f"{assignment}\nOPENBB_API_USERNAME=u1\nOPENBB_API_PASSWORD=p1\n")
        c = app_with_guard(str(p))
        assert c.get("/ping").status_code == 401
        assert c.get("/ping", headers=basic("u1", "p1")).status_code == 200

    def test_auth_flag_inside_a_quoted_value_does_not_open_the_guard(self, tmp_path):
        p = tmp_path / "credentials.env"
        p.write_text(
            "OPENBB_API_AUTH=true\nOPENBB_API_USERNAME=u1\n"
            "OPENBB_API_PASSWORD='first\nOPENBB_API_AUTH=false\nlast'\n"
        )
        c = app_with_guard(str(p))
        assert c.get("/ping").status_code == 401
        assert c.get("/ping", headers=basic("u1", "first\nOPENBB_API_AUTH=false\nlast")).status_code == 200

    @pytest.mark.parametrize("value", [r"$AUTH_FIXTURE", r'"${AUTH_FIXTURE}"'])
    def test_unresolved_host_expansion_is_not_a_basic_password(self, tmp_path, value):
        p = tmp_path / "credentials.env"
        p.write_text(f"OPENBB_API_AUTH=true\nOPENBB_API_USERNAME=u1\nOPENBB_API_PASSWORD={value}\n")
        c = app_with_guard(str(p))
        assert c.get("/ping", headers=basic("u1", value.strip('"'))).status_code == 401

    def test_host_inherited_auth_flag_is_not_treated_as_omitted(self, tmp_path):
        p = tmp_path / "credentials.env"
        p.write_text("OPENBB_API_AUTH\nOPENBB_API_USERNAME=u1\nOPENBB_API_PASSWORD=p1\n")
        c = app_with_guard(str(p))
        assert c.get("/ping").status_code == 401
        assert c.get("/ping", headers=basic("u1", "p1")).status_code == 401

    def test_on_with_empty_credentials_denies_all(self, tmp_path):
        p = tmp_path / "credentials.env"
        p.write_text("OPENBB_API_AUTH=true\nOPENBB_API_USERNAME=\nOPENBB_API_PASSWORD=\n")
        c = app_with_guard(str(p))
        assert c.get("/ping").status_code == 401
        assert c.get("/ping", headers=basic("", "")).status_code == 401


class TestAdminIsNotExempt:
    """The admin (tier 3) surface is a unix socket with no port -- but it is NOT
    header-free. create_app applies the same Basic-auth guard for role="admin"
    as for role="network", so reaching the 0700 socket raises an ALREADY
    AUTHENTICATED caller to tier 3; it does not replace authentication.

    The README and the compose comment both claimed "no port and no header" for
    years. Nothing tested it, so nothing caught it."""

    def test_the_admin_role_is_not_exempt_from_basic_auth(self, tmp_path):
        from app.server import create_app

        auth = write_auth(tmp_path)
        cred = tmp_path / "credentials.env"
        cred.write_text("FMP_API_KEY=abc\n")
        c = TestClient(create_app(role="admin", cred_file=str(cred), auth_file=auth))
        assert c.get("/widgets.json").status_code == 401
        assert c.get("/widgets.json", headers=basic("u1", "p1")).status_code == 200

    def test_the_network_role_is_not_exempt_either(self, tmp_path):
        from app.server import create_app

        auth = write_auth(tmp_path)
        cred = tmp_path / "credentials.env"
        cred.write_text("FMP_API_KEY=abc\n")
        c = TestClient(create_app(role="network", cred_file=str(cred), auth_file=auth))
        assert c.get("/widgets.json").status_code == 401
