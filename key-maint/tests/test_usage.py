# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the GNU Affero General Public License, version 3 only.
# SPDX-License-Identifier: AGPL-3.0-only

from datetime import UTC, datetime

import httpx

from app.usage import parse_usage

NOW = datetime(2026, 10, 17, 14, 48, tzinfo=UTC)


def _json(body, headers=None):
    return httpx.Response(200, json=body, headers=headers or {})


def _eodhd(**over):
    body = {"apiRequests": 1234, "apiRequestsDate": "2026-10-17",
            "dailyRateLimit": 100000, "extraLimit": 5000}
    body.update(over)
    return body


class TestEodhd:
    def test_eodhd_today(self):
        assert parse_usage("eodhd", _json(_eodhd()), NOW) == {
            "used": 1234, "limit": 100000, "window": "day",
            "resets_at": "2026-10-18T00:00:00Z", "extra": 5000,
        }

    def test_eodhd_numeric_strings(self):
        u = parse_usage("eodhd", _json(_eodhd(apiRequests="1234", dailyRateLimit="100000",
                                              extraLimit="5000")), NOW)
        assert (u["used"], u["limit"], u["extra"]) == (1234, 100000, 5000)

    def test_eodhd_stale_date_is_zero_used(self):
        u = parse_usage("eodhd", _json(_eodhd(apiRequestsDate="2026-10-16")), NOW)
        assert u["used"] == 0 and u["limit"] == 100000

    def test_eodhd_missing_date_is_none(self):
        body = _eodhd()
        del body["apiRequestsDate"]
        assert parse_usage("eodhd", _json(body), NOW) is None

    def test_eodhd_bad_limit_is_none(self):
        for bad in ("unlimited", 0, True, -5, None):
            assert parse_usage("eodhd", _json(_eodhd(dailyRateLimit=bad)), NOW) is None, bad

    def test_eodhd_bad_used_today_is_none(self):
        assert parse_usage("eodhd", _json(_eodhd(apiRequests="lots")), NOW) is None

    def test_eodhd_no_extra_key_when_missing(self):
        body = _eodhd()
        del body["extraLimit"]
        assert "extra" not in parse_usage("eodhd", _json(body), NOW)

    def test_non_json_body_is_none(self):
        assert parse_usage("eodhd", httpx.Response(200, text="<html>oops</html>"), NOW) is None
        assert parse_usage("eodhd", httpx.Response(200, content=b"\xff\xfe"), NOW) is None
        assert parse_usage("eodhd", _json([1, 2]), NOW) is None


class TestIntrinio:
    def test_picks_the_most_used_code(self):
        body = [
            {"access_code": "a", "count": 10, "limit": 1000, "seconds_until_reset": 60},
            {"access_code": "b", "count": "90", "limit": "100", "seconds_until_reset": "3600"},
        ]
        assert parse_usage("intrinio", _json(body), NOW) == {
            "used": 90, "limit": 100, "window": "period",
            "resets_at": "2026-10-17T15:48:00Z",
        }

    def test_skips_zero_limit_and_junk_entries(self):
        body = [{"count": 5, "limit": 0}, "junk",
                {"count": 1, "limit": 10}]
        u = parse_usage("intrinio", _json(body), NOW)
        assert (u["used"], u["limit"]) == (1, 10) and "resets_at" not in u

    def test_object_wrapping_a_list(self):
        body = {"usage": [{"count": 3, "limit": 30}]}
        assert parse_usage("intrinio", _json(body), NOW)["used"] == 3

    def test_empty_is_none(self):
        assert parse_usage("intrinio", _json([]), NOW) is None
        assert parse_usage("intrinio", _json({}), NOW) is None


class TestHeaders:
    def test_eia_hourly(self):
        r = _json({}, {"x-ratelimit-limit": "1000", "x-ratelimit-remaining": "988"})
        assert parse_usage("eia", r, NOW) == {"used": 12, "limit": 1000, "window": "hour"}

    def test_alpaca_minute_with_epoch_reset(self):
        reset = int(datetime(2026, 10, 17, 14, 49, tzinfo=UTC).timestamp())
        r = _json({}, {"X-RateLimit-Limit": "200", "X-RateLimit-Remaining": "150",
                       "X-RateLimit-Reset": str(reset)})
        assert parse_usage("alpaca", r, NOW) == {
            "used": 50, "limit": 200, "window": "minute", "resets_at": "2026-10-17T14:49:00Z",
        }

    def test_missing_garbage_or_inverted_headers_are_none(self):
        assert parse_usage("eia", _json({}), NOW) is None
        assert parse_usage("eia", _json({}, {"x-ratelimit-limit": "x",
                                             "x-ratelimit-remaining": "1"}), NOW) is None
        assert parse_usage("eia", _json({}, {"x-ratelimit-limit": "10",
                                             "x-ratelimit-remaining": "11"}), NOW) is None

    def test_unmapped_provider_is_never_parsed(self):
        r = _json({}, {"x-ratelimit-limit": "10", "x-ratelimit-remaining": "9"})
        assert parse_usage("fmp", r, NOW) is None


def test_defaults_now_to_the_current_time():
    today = datetime.now(UTC).date().isoformat()
    assert parse_usage("eodhd", _json(_eodhd(apiRequestsDate=today)))["used"] == 1234
