"""A chunk that overflows max_tokens is split and retried, not fatal.

A packed page (an answer key, a 50-item grid) can generate more structured
output than one call can return. That used to abort the whole upload with
"Try a smaller WORKSHEET_CHUNK_SIZE" — an environment variable, shown to a
teacher. Now the chunk is halved and retried; only a single page that still
overflows fails, and it says which page.
"""
from unittest.mock import MagicMock, patch

import pytest

from worksheets import services
from worksheets.services import ChunkTooDenseError, _classify_chunk_adaptive


def _pages(*nums):
    return [{'page_num': n, 'text': '', 'screenshot': 'x'} for n in nums]


def _result(pages, questions=1):
    return {
        'questions': [{'question_text': f'q on p{p["page_num"]}'} for _ in range(questions)
                      for p in [pages[0]]],
        'year_level': 5,
        'usage': {'input_tokens': 10, 'output_tokens': 20, 'total_tokens': 30},
    }


def test_a_chunk_that_fits_is_classified_in_one_call():
    pages = _pages(1, 2, 3, 4)
    with patch.object(services, '_classify_page_chunk',
                      return_value=_result(pages)) as chunk:
        _classify_chunk_adaptive(MagicMock(), 'sys', pages, 4)

    assert chunk.call_count == 1


def test_a_dense_chunk_is_halved_and_retried():
    pages = _pages(1, 2, 3, 4)
    seen = []

    def fake(client, system, chunk, total, shape_naming=False):
        seen.append([p['page_num'] for p in chunk])
        if len(chunk) > 2:
            raise ChunkTooDenseError('too dense')
        return _result(chunk)

    with patch.object(services, '_classify_page_chunk', side_effect=fake):
        result = _classify_chunk_adaptive(MagicMock(), 'sys', pages, 4)

    assert seen == [[1, 2, 3, 4], [1, 2], [3, 4]]
    # Both halves' questions and token usage survive the merge.
    assert len(result['questions']) == 2
    assert result['usage']['total_tokens'] == 60


def test_splitting_recurses_down_to_single_pages():
    pages = _pages(1, 2, 3, 4)
    seen = []

    def fake(client, system, chunk, total, shape_naming=False):
        seen.append([p['page_num'] for p in chunk])
        if len(chunk) > 1:
            raise ChunkTooDenseError('too dense')
        return _result(chunk)

    with patch.object(services, '_classify_page_chunk', side_effect=fake):
        result = _classify_chunk_adaptive(MagicMock(), 'sys', pages, 4)

    assert [c for c in seen if len(c) == 1] == [[1], [2], [3], [4]]
    assert len(result['questions']) == 4


def test_a_single_page_that_still_overflows_names_the_page():
    with patch.object(services, '_classify_page_chunk',
                      side_effect=ChunkTooDenseError('too dense')):
        with pytest.raises(ValueError) as exc:
            _classify_chunk_adaptive(MagicMock(), 'sys', _pages(7), 12)

    message = str(exc.value)
    assert 'Page 7' in message
    assert 'WORKSHEET_CHUNK_SIZE' not in message      # no env vars at teachers
    assert not isinstance(exc.value, ChunkTooDenseError)


def test_splitting_reports_progress():
    reported = []

    def fake(client, system, chunk, total, shape_naming=False):
        if len(chunk) > 1:
            raise ChunkTooDenseError('too dense')
        return _result(chunk)

    with patch.object(services, '_classify_page_chunk', side_effect=fake):
        _classify_chunk_adaptive(MagicMock(), 'sys', _pages(3, 4), 4,
                                 report=reported.append)

    assert any('smaller pieces' in m for m in reported)


def test_other_failures_are_not_retried():
    """A refusal or a rate-limit error must fail fast, not fan out into retries."""
    with patch.object(services, '_classify_page_chunk',
                      side_effect=ValueError('The AI declined')) as chunk:
        with pytest.raises(ValueError):
            _classify_chunk_adaptive(MagicMock(), 'sys', _pages(1, 2, 3, 4), 4)

    assert chunk.call_count == 1
