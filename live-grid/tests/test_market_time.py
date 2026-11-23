# SPDX-License-Identifier: Apache-2.0
"""Known bar boundary: explicit instants, legacy naive UTC and market dates."""
from datetime import date, datetime
import pytest


def test_explicit_offsets_and_legacy_utc_are_equivalent():
    from app.market_time import naive_utc, wire_time
    for local, utc in [('2026-01-15T09:30:00-05:00', '2026-01-15T14:30:00Z'),
                       ('2026-07-15T09:30:00-04:00', '2026-07-15T13:30:00Z')]:
        assert naive_utc(local) == naive_utc(utc)
        assert wire_time(local) == utc
        assert wire_time(naive_utc(utc)) == utc
        assert wire_time(utc[:-1].replace('T', ' ')) == utc


def test_daily_dates_and_fractional_instants():
    from app.market_time import wire_time
    assert wire_time('2026-01-15') == '2026-01-15'
    assert wire_time(date(2026, 1, 15)) == '2026-01-15'
    assert wire_time(datetime(2026, 1, 15), date_only=True) == '2026-01-15'
    assert wire_time('2026-01-15T00:00:00+09:00', date_only=True) == '2026-01-15'
    assert wire_time('2026-01-15T09:30:00.123456-05:00') == '2026-01-15T14:30:00.123456Z'


@pytest.mark.parametrize('raw', ['garbage','2026-02-30','2026-01-15T25:00:00Z',
                                '2026-01-15T09:30:00+99:00',
                                '2026-01-15T09:30:00.123456789Z'])
def test_invalid_or_unsupported_precision_is_not_silently_changed(raw):
    from app.market_time import naive_utc, wire_time
    with pytest.raises(ValueError):
        naive_utc(raw)
    with pytest.raises(ValueError):
        wire_time(raw)
