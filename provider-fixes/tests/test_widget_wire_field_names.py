# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""Widget columns must address the actual serialized API property names."""
import unittest
from unittest.mock import patch
from openbb_platform_api.utils.openapi import data_schema_to_columns_defs

class WireFieldNames(unittest.TestCase):
    def columns(self, properties):
        schema = {'type': 'object', 'properties': properties}
        with patch('openbb_platform_api.utils.openapi.get_data_schema_for_widget', return_value=schema):
            return data_schema_to_columns_defs({}, 'test', 'ecb')

    def test_ecb_iso_currency_keys_remain_uppercase(self):
        columns = self.columns({'date': {'type': 'string', 'format': 'date'}, 'EUR': {'type': 'number'}, 'USD': {'type': 'number'}})
        self.assertEqual([c['field'] for c in columns], ['date', 'EUR', 'USD'])
        self.assertEqual(columns[0]['pinned'], 'left')
        self.assertEqual(columns[0]['sort'], 'desc')
        self.assertEqual(columns[2]['cellDataType'], 'number')

    def test_mixed_case_serialized_aliases_are_not_invented_snake_case(self):
        columns = self.columns({'netAssetValue': {'type': 'number'}, 'CUSIP': {'type': 'string'}, 'ISO Code': {'type': 'string'}})
        self.assertEqual([c['field'] for c in columns], ['netAssetValue', 'CUSIP', 'ISO Code'])
        self.assertEqual(columns[1]['formatterFn'], 'none')
        self.assertEqual(columns[1]['cellDataType'], 'text')

    def test_snake_case_fields_and_declared_widget_overrides_stay_compatible(self):
        columns = self.columns({'symbol': {'type': 'string'}, 'change_percent': {'type': 'number', 'x-unit_measurement': 'percent'}, 'source': {'type': 'string', 'x-widget_config': {'field': 'declared_source'}}, 'hidden': {'type': 'number', 'x-widget_config': {'exclude': True}}})
        self.assertEqual([c['field'] for c in columns], ['symbol', 'change_percent', 'declared_source'])
        self.assertEqual(columns[0]['pinned'], 'left')
        self.assertEqual(columns[1]['formatterFn'], 'percent')

if __name__ == '__main__':
    unittest.main()
