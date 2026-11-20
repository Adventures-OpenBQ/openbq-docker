# Copyright 2026 SecretoftheUniverse.com LLC. Licensed under the Apache License, Version 2.0.
# SPDX-License-Identifier: Apache-2.0
"""The advanced-chart default must classify as the intended UDF asset."""
import ast
from pathlib import Path
import unittest
import openbb_tmx
from openbb_tmx.routers.udf import _instrument_type

class DefaultUdfSymbols(unittest.TestCase):
    def check_default(self, module, expected_type):
        path = Path(openbb_tmx.__file__).parent / 'routers' / (module + '.py')
        values = [value.value for node in ast.walk(ast.parse(path.read_text()))
                  if isinstance(node, ast.Dict) for key, value in zip(node.keys, node.values)
                  if isinstance(key, ast.Constant) and key.value == 'defaultSymbol'
                  and isinstance(value, ast.Constant)]
        self.assertEqual(len(values), 1)
        self.assertEqual(_instrument_type(values[0], None), expected_type)

    def test_futures_default_selects_futures_not_stock(self):
        self.check_default('futures', 'futures')

    def test_currency_default_selects_forex_not_stock(self):
        self.check_default('currency', 'forex')

if __name__ == '__main__':
    unittest.main()
