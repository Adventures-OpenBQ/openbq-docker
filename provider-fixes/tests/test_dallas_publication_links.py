# Copyright 2026 SecretoftheUniverse.com LLC. SPDX-License-Identifier: Apache-2.0
"""Resolve known Dallas working-paper links to their public PDF asset path."""
import unittest


class DallasPublicationLinks(unittest.TestCase):
    def resolve(self, link):
        from openbb_federal_reserve.utils.fedinprint import resolve_file
        page = f'<meta name="citation_pdf_url" content="{link}">'
        return resolve_file('https://fedinprint.org/item/example', lambda _: page)

    def test_known_working_paper_path_uses_the_published_media_asset(self):
        self.assertEqual(self.resolve('https://www.dallasfed.org/research/papers/2026/wp2633.pdf'),
                         'https://www.dallasfed.org/~/media/documents/research/papers/2026/wp2633.pdf')

    def test_rewrite_is_limited_to_dallas_working_paper_paths(self):
        unchanged = [
            'https://www.dallasfed.org/~/media/documents/research/papers/2026/wp2640.pdf',
            'https://example.org/research/papers/2026/wp2633.pdf',
            'https://www.dallasfed.org.example.org/research/papers/2026/wp2633.pdf',
            'https://www.dallasfed.org/research/other/2026/wp2633.pdf',
        ]
        for link in unchanged:
            with self.subTest(link=link):
                self.assertEqual(self.resolve(link), link)
