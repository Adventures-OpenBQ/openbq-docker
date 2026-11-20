import unittest
from unittest.mock import patch
from openbb_news import registry

class RSSDefault(unittest.TestCase):
    def test_benzinga_default_is_main_feed(self):
        self.assertEqual(registry.default_feed_for('benzinga'),'benzinga_main')
        self.assertEqual(registry.get_feed_url(registry.default_feed_for('benzinga')),'https://www.benzinga.com/feed')
    def test_explicit_market_source_stays_available(self):
        self.assertEqual(registry.get_feed_url('benzinga_markets'),'https://www.benzinga.com/markets/feed')
        self.assertIn('benzinga_markets',{r['value'] for r in registry.list_feed_choices('benzinga')})
    def test_custom_feed_url_still_wins(self):
        feeds=registry.list_feeds()
        feeds['benzinga_main']='https://example.test/custom.xml'
        with patch.object(registry,'list_feeds',return_value=feeds):
            self.assertEqual(registry.get_feed_url(registry.default_feed_for('benzinga')),'https://example.test/custom.xml')
    def test_other_defaults_unchanged(self):
        self.assertEqual(registry.default_feed_for('bbc'),'bbc_world')
        self.assertEqual(registry.default_feed_for(None),None)

if __name__=='__main__': unittest.main(verbosity=2)

class FetchFeedCharacterization(unittest.IsolatedAsyncioTestCase):
    async def test_403_is_currently_returned_as_empty_feed(self):
        import aiohttp
        from openbb_news.parser import fetch_feed
        class Response:
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            def raise_for_status(self): raise aiohttp.ClientResponseError(None,(),status=403,message='Forbidden')
        class Session:
            async def get(self,*args,**kwargs): return Response()
        result=await fetch_feed(Session(),'https://www.benzinga.com/markets/feed')
        self.assertEqual(result.entries,[])
    async def test_valid_xml_yields_actual_article_fields(self):
        from openbb_news.parser import fetch_feed
        class Response:
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            def raise_for_status(self): pass
            async def read(self): return b'<rss version="2.0"><channel><title>Benzinga</title><item><title>Actual fixture article</title><link>https://example.test/article</link><description>News summary</description></item></channel></rss>'
        class Session:
            async def get(self,*args,**kwargs): return Response()
        result=await fetch_feed(Session(),'https://www.benzinga.com/feed')
        self.assertEqual(result.entries[0].title,'Actual fixture article')
        self.assertEqual(result.entries[0].link,'https://example.test/article')
