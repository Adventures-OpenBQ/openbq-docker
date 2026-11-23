import unittest
from openbb_tmx.models.gainers import TmxGainersData, TmxGainersFetcher, TmxGainersQueryParams

class MissingGainerName(unittest.TestCase):
    def row(self, name):
        return {'symbol': 'A', 'longName': name, 'price': 10, 'priceChange': 1, 'percentChange': 10, 'rank': 1}

    def test_null_name_keeps_row_and_nullable_name(self):
        try:
            item = TmxGainersData.model_validate(self.row(None))
        except ValueError as error:
            self.fail('A missing optional display name must not reject a quote: ' + str(error))
        self.assertIsNone(item.name)
        self.assertEqual(item.symbol, 'A')
        self.assertEqual(item.price, 10)

    def test_placeholder_name_is_nullable(self):
        try:
            item = TmxGainersData.model_validate(self.row('-'))
        except ValueError as error:
            self.fail('An upstream missing-name marker must not reject a quote: ' + str(error))
        self.assertIsNone(item.name)

    def test_real_name_and_percentage_preserved(self):
        item=TmxGainersData.model_validate(self.row('Example Inc.'))
        self.assertEqual(item.name, 'Example Inc.')
        self.assertEqual(item.percent_change, .1)

    def test_full_transform_preserves_both_rows(self):
        try:
            items=TmxGainersFetcher.transform_data(TmxGainersQueryParams(), [self.row('Example Inc.'),self.row(None)])
        except ValueError as error:
            self.fail('A nullable optional name must not fail the complete gains list: '+str(error))
        self.assertEqual(len(items),2)
        self.assertEqual(items[0].name,'Example Inc.')
        self.assertIsNone(items[1].name)
