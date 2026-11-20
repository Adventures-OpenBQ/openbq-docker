"""Only directory fixtures from upstream conftest; options fixtures unused."""
import pytest
@pytest.fixture
def index_directory():
    """Minimal Cboe index directory frame."""
    from pandas import DataFrame

    return DataFrame(
        [
            {
                "index_symbol": "BUK100P",
                "name": "Cboe UK 100",
                "description": "UK large cap",
                "source": "eu_proprietary_index",
                "currency": "GBP",
            },
            {
                "index_symbol": "AAVE10RP",
                "name": "Cboe Apple 10 Index",
                "description": "US index",
                "source": "us_index",
                "currency": "USD",
            },
            {
                "index_symbol": "X2C",
                "name": "CXA 200 Price Return Index",
                "description": "Cboe Australia 200",
                "source": "au_proprietary_index",
                "currency": "AUD",
            },
        ]
    )


@pytest.fixture
def company_directory():
    """Minimal Cboe company directory frame, indexed by symbol."""
    from pandas import DataFrame

    return DataFrame(
        [
            {
                "symbol": "AAPL",
                "name": "APPLE INC",
                "dpm_name": "DPM",
                "post_station": "1",
            },
            {
                "symbol": "SPY",
                "name": "SPDR S&P 500 ETF",
                "dpm_name": "DPM",
                "post_station": "2",
            },
        ]
    ).set_index("symbol")
