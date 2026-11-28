"""Offline regressions adapted from upstream PRs 7758/7836/7823/7807/7834/7583.

Only download/parsing boundaries are mocked; numerical functions execute installed code.
Run with stdlib unittest (no production dependency changes required).
"""
import io
import unittest
import warnings
import zipfile
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import pandas as pd
from openbb_famafrench.utils import helpers as ff
from openbb_technical.helpers import yang_zhang, calculate_fib_levels
from openbb_technical.indicators.statistics import _stats_block


class InternationalArchives(unittest.TestCase):
    def archive(self, member, **kwargs):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr(member, 'fixture portfolio data')
        with patch.object(ff, 'download_international_portfolios', return_value=SimpleNamespace(content=stream.getvalue())):
            self.assertEqual(ff.get_international_portfolio_data(**kwargs), 'fixture portfolio data')

    def test_australia_archive_member(self):
        for dividends in (True, False):
            with self.subTest(dividends=dividends):
                self.archive('Austrlia.Dat', country='australia', dividends=dividends)

    def test_scandinavia_archive_member(self):
        for dividends in (True, False):
            with self.subTest(dividends=dividends):
                self.archive('Ind_Scandanavia.Dat', index='scandinavia', dividends=dividends)

    def test_not_required_tables_align_with_metadata(self):
        for suffix in ('', ' - Ex-Dividends'):
            with self.subTest(suffix=suffix):
                descriptions = ['Value-Weight Local Returns All 4 Data Items Not Reqd', 'Value-Weight Local Returns All 4 Data Items Required']
                frames = [pd.DataFrame({'mkt': [v]}) for v in (1.0, 2.0)]
                meta = [{'frequency': 'annual', 'description': d + suffix} for d in descriptions]
                with patch.object(ff, 'get_international_portfolio_data', return_value=''), patch.object(ff, 'read_dat_file', return_value=[]), patch.object(ff, 'process_international_portfolio_data', return_value=(frames, meta)):
                    dfs, metadata = ff.get_international_portfolio(country='japan', measure='local', frequency='annual', dividends=not suffix, all_data_items_required=False)
                self.assertEqual([df['mkt'].iloc[0] for df in dfs], [1.0])
                self.assertEqual(metadata, [meta[0]])

    def test_required_tables_unchanged(self):
        frames = [pd.DataFrame({'mkt': [v]}) for v in (1.0, 2.0)]
        meta = [{'frequency': 'annual', 'description': d} for d in ('Local Not Reqd', 'Local Required')]
        with patch.object(ff, 'get_international_portfolio_data', return_value=''), patch.object(ff, 'read_dat_file', return_value=[]), patch.object(ff, 'process_international_portfolio_data', return_value=(frames, meta)):
            dfs, metadata = ff.get_international_portfolio(country='japan', measure='local', frequency='annual', all_data_items_required=True)
        self.assertEqual(dfs[0]['mkt'].iloc[0], 2.0)
        self.assertEqual(metadata, [meta[1]])


class NumericalRegressions(unittest.TestCase):
    def test_yang_zhang_overnight_counted_once(self):
        gaps = np.array([0, .01, -.02, .015, -.005, .02, -.01, .005])
        price = 100 * np.exp(np.cumsum(gaps))
        df = pd.DataFrame({k: price for k in ['open','high','low','close']}, index=pd.date_range('2021-01-01', periods=len(price)))
        expected = np.sqrt(np.log(df.open / df.close.shift(1)).pow(2).rolling(5).sum() / 4 * 252).dropna()
        pd.testing.assert_series_equal(yang_zhang(df, window=5), expected, check_names=False)

    def test_yang_zhang_hand_computed(self):
        g, c = np.array([0,.01,-.02,.03]), np.array([0,.02,-.01,0])
        h, lo = np.array([0,.03,.01,.02]), np.array([0,-.01,-.02,-.01])
        close = np.log(100) + np.cumsum(g+c)
        op = close-c
        df = pd.DataFrame({'open':np.exp(op),'high':np.exp(op+h),'low':np.exp(op+lo),'close':np.exp(close)})
        result = yang_zhang(df, window=3)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result.iloc[0], 0.5937791278704656, places=10)

    def test_sortino_identical_negative_returns(self):
        result = _stats_block(pd.Series([-.10,-.10,.20,.20]),252,0)
        self.assertIsNotNone(result['sortino'])
        self.assertAlmostEqual(result['sortino'], .05/np.sqrt(.005)*np.sqrt(252))

    def test_sortino_single_negative_return(self):
        result = _stats_block(pd.Series([-.08,.04,.04,.04]),252,0)
        self.assertIsNotNone(result['sortino'])
        self.assertAlmostEqual(result['sortino'], .25*np.sqrt(252))

    def test_sortino_uses_excess_target_and_full_sample(self):
        returns = pd.Series([-.02,.03,.08,.12,np.nan])
        excess = np.array([-.03,.02,.07,.11])
        expected = excess.mean()/np.sqrt(np.mean(np.minimum(excess,0)**2))*np.sqrt(12)
        result = _stats_block(returns,12,.01)
        self.assertIsNotNone(result['sortino'])
        self.assertAlmostEqual(result['sortino'], expected)

    def test_sortino_no_downside_unchanged(self):
        self.assertIsNone(_stats_block(pd.Series([.01,.02,.03]),252,0)['sortino'])

    def test_fibonacci_snaps_missing_start_against_start(self):
        index = pd.bdate_range('2024-01-01', periods=60)
        data = pd.DataFrame({'close': np.linspace(100,160,60)}, index=index)
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter('always')
            _, min_date, max_date, min_pr, max_pr, _ = calculate_fib_levels(data,'close',start_date=pd.Timestamp('2024-01-06'),end_date=index[-1])
        self.assertTrue(any('Start date not in data' in str(w.message) for w in captured))
        self.assertEqual(min_date,pd.Timestamp('2024-01-05'))
        self.assertEqual(max_date,index[-1])
        self.assertGreater(max_pr,min_pr)


if __name__ == '__main__':
    unittest.main(verbosity=2)
