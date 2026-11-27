# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""A slow complete career index must not hide an otherwise valid member bio."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from openbb_government_us.congress import congress_router as route
from openbb_government_us.congress.utils import bulk
from openbb_government_us.congress.utils.member_cards import member_bio_payload

RECORD = {'id': {'bioguide': 'A000055'}, 'name': {'official_full': 'Robert B. Aderholt'}, 'terms': [{'type': 'rep', 'state': 'AL', 'start': '2025-01-03', 'end': '2027-01-03'}]}
class MemberVotingDeadline(unittest.IsolatedAsyncioTestCase):
    async def payload(self, voting):
        with patch.object(route, '_MEMBER_VOTING_TIMEOUT', 0.01, create=True), patch.object(bulk, 'load_member_record', AsyncMock(return_value=RECORD)), patch.object(bulk, 'member_committees', AsyncMock(return_value=[{'committee': 'Appropriations'}])), patch.object(bulk, 'load_social_media', AsyncMock(return_value={})), patch.object(bulk, 'member_passage_record', voting), patch.object(bulk, 'member_photo_url', AsyncMock(return_value=None)):
            return await asyncio.wait_for(route.member_info_data('A000055'), 0.3)

    async def test_slow_career_index_returns_real_bio_and_unknown_counts(self):
        cancelled = asyncio.Event()
        async def slow(_):
            try: await asyncio.Event().wait()
            finally: cancelled.set()
        payload = await self.payload(AsyncMock(side_effect=slow))
        self.assertEqual(payload['name'], 'Robert B. Aderholt')
        self.assertEqual(payload['committees'][0]['committee'], 'Appropriations')
        self.assertEqual(len(payload['terms']), 1)
        self.assertEqual(payload['voting']['status'], 'unavailable')
        for key in ['yea', 'nay', 'total', 'yea_pct']: self.assertIsNone(payload['voting'][key])
        self.assertTrue(cancelled.is_set(), 'Do not leave the timed-out aggregation running')

    async def test_available_complete_career_counts_are_preserved(self):
        expected = {'yea': 123, 'nay': 8, 'total': 131, 'yea_pct': 93.9}
        payload = await self.payload(AsyncMock(return_value=expected))
        for key, value in expected.items(): self.assertEqual(payload['voting'][key], value)
        self.assertNotEqual(payload['voting'].get('status'), 'unavailable')

    def test_payload_preserves_unavailable_status_instead_of_inventing_zero(self):
        voting = dict.fromkeys(['yea', 'nay', 'total', 'yea_pct'])
        voting.update(status='unavailable', message='Complete career index is not ready.')
        result = member_bio_payload(RECORD, [], {}, voting)['voting']
        self.assertEqual(result['status'], 'unavailable')
        self.assertIsNone(result['total'])
        self.assertEqual(result['message'], voting['message'])

class CompleteCareerOnly(unittest.IsolatedAsyncioTestCase):
    async def tally(self, loaded):
        from unittest.mock import MagicMock
        from openbb_government_us.congress.utils import store
        get = MagicMock(return_value=(123, 8))
        with patch.object(bulk, 'ensure_member_passage', AsyncMock()), patch.object(bulk, 'load_member_record', AsyncMock(return_value=RECORD)), patch.object(bulk, 'member_service', return_value=[(118, 'H'), (119, 'H')]), patch.object(store, 'loaded_keys', return_value=loaded), patch.object(store, 'get_passage', get):
            result = await bulk.member_passage_record('A000055')
        return result, get

    async def test_partial_store_must_not_be_labeled_as_complete_career(self):
        result, get = await self.tally(['118-H'])
        self.assertEqual(result.get('status'), 'unavailable')
        self.assertIsNone(result['total'])
        get.assert_not_called()

    async def test_fully_indexed_store_retains_actual_tally(self):
        result, get = await self.tally(['118-H', '119-H'])
        self.assertEqual(result, {'yea': 123, 'nay': 8, 'total': 131, 'yea_pct': 93.9})
        get.assert_called_once_with('A000055')
