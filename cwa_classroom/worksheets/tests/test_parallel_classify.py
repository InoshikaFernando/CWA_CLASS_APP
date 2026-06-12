"""CPP: parallel page-chunk classification — chunking + merge logic."""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from worksheets import services


def _pages(n):
    return {
        'page_count': n,
        'pages': [
            {
                'page_num': i + 1,
                'screenshot': 'b64data',
                'screenshot_w': 800,
                'screenshot_h': 1100,
                'text': f'page {i + 1} text',
            }
            for i in range(n)
        ],
    }


def _chunk_result(pages, n_questions=1):
    return {
        'year_level': 9,
        'subject': 'Mathematics',
        'strand': 'Algebra',
        'topic': 'Quadratics',
        'questions': [{'page': pages[0]['page_num'], 'q': i} for i in range(n_questions)],
        'usage': {'input_tokens': 5, 'output_tokens': 5, 'total_tokens': 10},
    }


class ParallelClassifyTests(SimpleTestCase):

    @patch('worksheets.services._get_anthropic_client', return_value=MagicMock())
    @patch('worksheets.services._classify_page_chunk')
    def test_single_chunk_skips_threadpool(self, mock_chunk, _client):
        # 3 pages, chunk size 4 → one chunk → single call, no merge.
        mock_chunk.return_value = _chunk_result(_pages(3)['pages'], n_questions=2)
        res = services.classify_worksheet_questions(_pages(3), [], [])
        self.assertEqual(mock_chunk.call_count, 1)
        self.assertEqual(len(res['questions']), 2)

    @patch('worksheets.services._get_anthropic_client', return_value=MagicMock())
    @patch('worksheets.services._classify_page_chunk')
    def test_multi_chunk_runs_parallel_and_merges(self, mock_chunk, _client):
        # 9 pages, chunk size 4 → chunks of [4, 4, 1] = 3 chunks.
        mock_chunk.side_effect = lambda client, system, pages, total: _chunk_result(pages, n_questions=2)
        res = services.classify_worksheet_questions(_pages(9), [], [])

        self.assertEqual(mock_chunk.call_count, 3)
        self.assertEqual(len(res['questions']), 6)          # 2 per chunk × 3
        self.assertEqual(res['usage']['total_tokens'], 30)  # 10 per chunk × 3
        self.assertEqual(res['year_level'], 9)
        self.assertEqual(res['topic'], 'Quadratics')

    @patch('worksheets.services._get_anthropic_client', return_value=MagicMock())
    @patch('worksheets.services._classify_page_chunk')
    def test_chunk_failure_propagates(self, mock_chunk, _client):
        def boom(client, system, pages, total):
            if pages[0]['page_num'] == 5:        # fail the second chunk
                raise ValueError('chunk timed out')
            return _chunk_result(pages)
        mock_chunk.side_effect = boom
        with self.assertRaises(ValueError):
            services.classify_worksheet_questions(_pages(9), [], [])

    @patch('worksheets.services._get_anthropic_client', return_value=MagicMock())
    @patch('worksheets.services._classify_page_chunk')
    def test_merge_picks_majority_classification(self, mock_chunk, _client):
        # Two chunks say Year 9, one says Year 8 → majority wins.
        results = iter([
            {'year_level': 9, 'subject': 'Mathematics', 'questions': [{}], 'usage': {}},
            {'year_level': 9, 'subject': 'Mathematics', 'questions': [{}], 'usage': {}},
            {'year_level': 8, 'subject': 'Mathematics', 'questions': [{}], 'usage': {}},
        ])
        mock_chunk.side_effect = lambda *a, **k: next(results)
        res = services.classify_worksheet_questions(_pages(9), [], [])
        self.assertEqual(res['year_level'], 9)
        self.assertEqual(len(res['questions']), 3)
