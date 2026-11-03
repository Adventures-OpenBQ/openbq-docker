# SPDX-License-Identifier: Apache-2.0
"""Known bar boundary: explicit instants, legacy naive UTC and market dates."""
from datetime import date, datetime
import pytest
import polars as pl


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


def test_study_input_normalizes_offsets_before_dropping_zone():
    from app.ta.payload import bars_to_frame
    stamps = ['2026-01-15T09:30:00-05:00', '2026-01-15T14:30:00Z',
              '2026-01-15 14:30:00']
    bars = [dict(date=s, open=1, high=1, low=1, close=1, volume=1) for s in stamps]
    frame = bars_to_frame(bars)
    assert frame['date'].to_list() == [datetime(2026, 1, 15, 14, 30)] * 3
    assert bars[0]['date'] == stamps[0]


def test_study_figures_and_deltas_share_wire_timestamps():
    from app.ta.figure import build_ta_figure, delta
    frame = pl.DataFrame({'date':[datetime(2026, 1, 15, 14, 30)],
                          'open':[1.0], 'high':[1.0], 'low':[1.0], 'close':[1.0]})
    figure = build_ta_figure('TEST', frame, [], interval='1m')
    assert figure['data'][0]['x'] == ['2026-01-15T14:30:00Z']
    assert delta(frame, [], 0, interval='1m')['x'] == figure['data'][0]['x']
    assert build_ta_figure('TEST', frame, [], interval='1d')['data'][0]['x'] == ['2026-01-15']
    assert delta(frame, [], 0, interval='1d')['x'] == ['2026-01-15']


def test_offset_window_end_is_compared_on_the_internal_utc_clock():
    from app.series import window_end
    assert window_end('2026-01-15T09:30:00-05:00') == datetime(2026, 1, 15, 14, 30)


def test_shared_client_host_conformance_fixture():
    import json
    from pathlib import Path
    from app.market_time import wire_time
    fixture = json.loads((Path(__file__).parent/'fixtures/market-time.json').read_text())
    for case in fixture['valid']:
        assert wire_time(case['input']) == case['wire']
    for raw in fixture['invalid']:
        with pytest.raises(ValueError):
            wire_time(raw)



def test_daily_offset_labels_survive_frame_and_delta():
    from app.ta.payload import bars_to_frame
    from app.ta.figure import build_ta_figure, delta
    rows = [dict(date='2026-01-15T00:00:00+09:00', open=1, high=1, low=1, close=1)]
    frame = bars_to_frame(rows, interval='1d')
    assert frame['date'].to_list() == [datetime(2026, 1, 15)]
    assert build_ta_figure('TEST', frame, [], interval='1d')['data'][0]['x'] == ['2026-01-15']
    assert delta(frame, [], 0, interval='1d')['x'] == ['2026-01-15']
