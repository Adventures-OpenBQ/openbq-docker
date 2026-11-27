"""Generic expiry selection and strategy-specific quoted-leg availability."""
from datetime import date, timedelta
import unittest
from openbb_core.provider.standard_models.options_chains import OptionsChainsData
from openbb_core.app.model.abstract.error import OpenBBError


def chain(near_rows):
    near,far=date.today()+timedelta(days=14),date.today()+timedelta(days=21)
    rows=[(near,*r) for r in near_rows]+[(far,strike,kind,1.,1.2) for strike in (95.,100.,105.) for kind in ('call','put')]
    return OptionsChainsData(contract_symbol=[f'FAKE{i}' for i in range(len(rows))],underlying_symbol=['FAKE']*len(rows),underlying_price=[100.]*len(rows),expiration=[r[0] for r in rows],dte=[(r[0]-date.today()).days for r in rows],strike=[r[1] for r in rows],option_type=[r[2] for r in rows],bid=[r[3] for r in rows],ask=[r[4] for r in rows]),near.isoformat(),far.isoformat()


class StrategyExpiryScope(unittest.TestCase):
    def test_generic_filter_keeps_nearest_one_sided_expiry(self):
        c,near,_=chain([(110.,'call',1.,1.2),(115.,'call',1.,1.2)])
        numeric=c.filter_data(date=14,option_type='call')
        literal=c.filter_data(date=near,option_type='call')
        self.assertEqual(len(numeric),2)
        self.assertEqual(numeric['expiration'].astype(str).unique().tolist(),[near])
        self.assertEqual(numeric['contract_symbol'].tolist(),literal['contract_symbol'].tolist())

    def test_vertical_calls_do_not_need_puts_or_spot_spanning(self):
        c,near,_=chain([(110.,'call',1.,1.2),(115.,'call',1.,1.2)])
        result=c.vertical_call_spread(days=14,sold=110.,bought=115.).iloc[:,0]
        self.assertEqual(result['Expiration'],near)

    def test_straddle_requires_actual_put_and_call_rows(self):
        c,_,far=chain([(95.,'call',1.,1.2),(105.,'call',1.,1.2)])
        result=c.straddle(days=14).iloc[:,0]
        self.assertEqual(result['Expiration'],far)
        self.assertAlmostEqual(result['Cost'],2.4)

    def test_straddle_requires_otm_side_for_each_option_kind(self):
        c,_,far=chain([(95.,'call',1.,1.2),(105.,'put',1.,1.2)])
        self.assertEqual(c.straddle(days=14).loc['Expiration'].iloc[0],far)

    def test_long_straddle_requires_ask_quotes(self):
        c,_,far=chain([(95.,'put',1.,None),(105.,'call',1.,1.2)])
        self.assertEqual(c.straddle(days=14).loc['Expiration'].iloc[0],far)

    def test_short_straddle_requires_bid_quotes(self):
        c,_,far=chain([(95.,'put',None,1.2),(105.,'call',1.,1.2)])
        self.assertEqual(c.straddle(days=14,strike=-100.).loc['Expiration'].iloc[0],far)

    def test_explicit_strike_does_not_require_spot_spanning(self):
        c,near,_=chain([(110.,'put',1.,1.2),(110.,'call',1.,1.2)])
        self.assertEqual(c.straddle(days=14,strike=110.).loc['Expiration'].iloc[0],near)

    def test_strangle_skips_missing_option_side(self):
        c,_,far=chain([(95.,'call',1.,1.2),(105.,'call',1.,1.2)])
        for money in (5.,-5.):
            with self.subTest(moneyness=money):
                result=c.strangle(days=14,moneyness=money).iloc[:,0]
                self.assertEqual(result['Expiration'],far)
                self.assertAlmostEqual(result['Cost'],-2. if money<0 else 2.4)

    def test_synthetic_positions_require_their_actual_quote_sides(self):
        c,_,far=chain([(95.,'call',1.,1.2),(105.,'call',1.,1.2)])
        for method in ('synthetic_long','synthetic_short'):
            with self.subTest(method=method):
                self.assertEqual(getattr(c,method)(days=14).loc['Expiration'].iloc[0],far)

    def test_synthetic_quote_requirements_match_trade_direction(self):
        # Long requires call ask + put bid, short requires call bid + put ask.
        for method,near_rows in (
            ('synthetic_long',[(95.,'put',None,1.2),(105.,'call',1.,1.2)]),
            ('synthetic_short',[(95.,'put',1.,None),(105.,'call',1.,1.2)]),
        ):
            with self.subTest(method=method):
                c,_,far=chain(near_rows)
                self.assertEqual(getattr(c,method)(days=14).loc['Expiration'].iloc[0],far)

    def test_no_viable_expiry_reports_strategy_error(self):
        c,_,_=chain([(95.,'call',1.,1.2),(105.,'call',1.,1.2)])
        # Keep only listed calls at both expirations.
        rows=c.dataframe[c.dataframe.option_type=='call']
        invalid=OptionsChainsData(**{key:rows[key].tolist() for key in ('contract_symbol','underlying_symbol','underlying_price','expiration','dte','strike','option_type','bid','ask')})
        with self.assertRaisesRegex(OpenBBError,'No expiration has quoted call and put legs'):
            invalid.straddle(days=14)

    def test_batch_straddle_uses_same_viability_rule(self):
        c,_,far=chain([(95.,'call',1.,1.2),(105.,'call',1.,1.2)])
        result=c.strategies(days=[14],straddle_strike=0)
        self.assertEqual(result['Expiration'].tolist(),[far])


if __name__=='__main__':unittest.main(verbosity=2)
