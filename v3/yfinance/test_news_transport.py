# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Exercise the real SDK news request against a fixed provider response, offline."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import yfinance as yf

class NewsTransport(unittest.TestCase):
    def test_each_news_tab_uses_current_graphql_and_preserves_article_content(self):
        asset = {'__typename': 'Story', 'id': 'article-1', 'title': 'Verified article',
                 'contentAttributes': {'publishTime': '2026-11-19T12:00:00Z',
                     'canonicalUrl': 'https://example.com/verified-article',
                     'provider': {'displayName': 'Fixture publisher'}}}
        response = SimpleNamespace(text='', json=lambda: {'data': {'lightyearList': {'main': {
            'edges': [{'node': {'asset': asset}}], 'pageInfo': {'hasNextPage': False}}}}})
        for tab, stream in [('news', 'news'), ('all', 'all'), ('press releases', 'pressrelease')]:
            with self.subTest(tab=tab):
                ticker = yf.Ticker('AAPL')
                def post(url, **kwargs):
                    self.assertEqual(url, 'https://nexus-finance-prod.media.yahoo.com/')
                    self.assertEqual(kwargs['body']['operationName'], 'FinanceTickerListNews')
                    self.assertTrue(kwargs['body']['variables']['listInput']['slug'].endswith('ticker-' + stream))
                    self.assertEqual(kwargs['headers']['x-yahoo-cg-client-name'], 'finance')
                    return response
                with patch.object(ticker._data, 'post', side_effect=post):
                    news = ticker.get_news(count=1, tab=tab)
                self.assertEqual(len(news), 1)
                self.assertEqual(news[0]['content']['title'], 'Verified article')
                self.assertEqual(news[0]['content']['canonicalUrl']['url'], 'https://example.com/verified-article')

if __name__ == '__main__':
    unittest.main()
