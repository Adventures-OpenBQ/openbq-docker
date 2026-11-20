"""Offline installed-model behavior regressions adapted from PRs 7808, 7835, 7859."""
from datetime import date, timedelta
import unittest
from openbb_core.provider.standard_models.options_chains import OptionsChainsData


def make_chain(expirations):
    rows = []
    for expiration, strikes in expirations:
        for strike in strikes:
            for kind in ('call', 'put'):
                intrinsic = max(100-strike, 0) if kind == 'call' else max(strike-100, 0)
                bid = intrinsic + (4 if strike == 100 else 1)
                rows.append(dict(contract_symbol=f'FAKE{expiration:%y%m%d}{kind[0]}{strike}', underlying_symbol='FAKE', underlying_price=100., eod_date=date(2030,1,1), expiration=expiration, dte=(expiration-date(2030,1,1)).days, strike=strike, option_type=kind, bid=float(bid), ask=float(bid)+.1))
    return OptionsChainsData(**{key:[row[key] for row in rows] for key in rows[0]})


class SelectedExpiration(unittest.TestCase):
    def setUp(self):
        self.chain = make_chain([(date(2030,1,15),(90.,100.,110.)),(date(2030,2,15),(95.,105.))])

    def test_selected_expiration_ignores_other_strikes(self):
        for expiration in ('2030-01-15', 14):
            with self.subTest(expiration=expiration):
                self.assertEqual(self.chain._get_nearest_otm_strikes(date=expiration,moneyness=5.2), {'call':110.,'put':90.})

    def test_selected_expiration_does_not_borrow_atm(self):
        for expiration in ('2030-02-15', 45):
            with self.subTest(expiration=expiration):
                self.assertEqual(self.chain._get_nearest_otm_strikes(date=expiration,moneyness=1.), {'call':105.,'put':95.})

    def test_unfiltered_chain_unchanged(self):
        self.assertEqual(self.chain._get_nearest_otm_strikes(moneyness=5.2), {'call':105.,'put':95.})

    def test_long_and_short_strangle_costs(self):
        for moneyness,cost in ((5.2,2.2),(-5.2,-2.)):
            with self.subTest(moneyness=moneyness):
                result=self.chain.strangle(days=14,moneyness=moneyness).iloc[:,0]
                self.assertEqual(result['Expiration'],'2030-01-15')
                self.assertEqual(result['Strike 1'],110.)
                self.assertEqual(result['Strike 2'],90.)
                self.assertAlmostEqual(result['Cost'],cost)


class VerticalPutSpreads(unittest.TestCase):
    def test_every_requested_pair_and_expiration_is_returned(self):
        chain=make_chain([(date(2030,1,15),(90.,95.,100.,105.,110.)),(date(2030,2,15),(90.,95.,100.,105.,110.))])
        result=chain.strategies(days=[14,45],vertical_puts=[(95.,105.),(90.,110.)])
        puts=result[result['Strategy'].str.contains('Put Spread')]
        self.assertEqual(len(puts),4)
        self.assertEqual(set(zip(puts['Expiration'],puts['Strike 1'],puts['Strike 2'])),{(exp,a,b) for exp in ('2030-01-15','2030-02-15') for a,b in ((95.,105.),(90.,110.))})
        for _,row in puts.iterrows():
            direct=chain.vertical_put_spread(row['Expiration'],row['Strike 1'],row['Strike 2']).iloc[:,0]
            self.assertAlmostEqual(row['Cost'],direct['Cost'])


class ExistingOneSidedExpiryFix(unittest.TestCase):
    def test_straddle_skips_one_sided_nearest_expiry(self):
        near,far=date.today()+timedelta(days=14),date.today()+timedelta(days=16)
        rows=[(near,125.,'call')]+[(far,strike,kind) for strike in (95.,100.,105.) for kind in ('call','put')]
        chain=OptionsChainsData(underlying_symbol=['FAKE']*len(rows), underlying_price=[100.]*len(rows), contract_symbol=[f'FAKE{i}' for i in range(len(rows))], expiration=[r[0] for r in rows], dte=[(r[0]-date.today()).days for r in rows], strike=[r[1] for r in rows], option_type=[r[2] for r in rows], bid=[1.]*len(rows), ask=[1.2]*len(rows),last_trade_price=[1.1]*len(rows))
        result=chain.straddle(days=14)
        self.assertEqual(result.loc['Expiration'].iloc[0],far.isoformat())


if __name__=='__main__':
    unittest.main(verbosity=2)
