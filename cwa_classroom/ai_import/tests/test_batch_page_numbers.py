"""A batch's source_page / image_page are pinned to the batch's REAL page
numbers, and a positional answer is remapped before anything is cropped.

The AI import sends up to twenty pages per request. A page sent seventh in the
batch covering pages 21–40 is page 27; a model that answers ``7`` would have
its figure cropped from page 7 — the same position-for-page mix-up that put a
page of handwritten notes on a page-7 statistics question in the worksheet
importer. Zero-token: the Anthropic client is mocked.
"""
from unittest.mock import MagicMock

from ai_import.services import CLASSIFICATION_TOOL, _classify_page_batch


class _ToolStream:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        block = MagicMock()
        block.type = 'tool_use'
        block.name = 'classify_questions'
        block.input = self.payload
        resp = MagicMock(stop_reason='tool_use')
        resp.content = [block]
        resp.usage.input_tokens = 10
        resp.usage.output_tokens = 5
        return resp


def _pages(*nums):
    return [{'page_num': n, 'screenshot': 'x', 'text': '', 'images': []} for n in nums]


def _question_props(tool):
    return tool['input_schema']['properties']['questions']['items']['properties']


def test_batch_pins_both_page_fields_to_the_batch_pages():
    seen = []
    client = MagicMock()

    def stream(**kw):
        seen.append(kw)
        return _ToolStream({'questions': []})
    client.messages.stream.side_effect = stream

    _classify_page_batch(client, 'sys', _pages(21, 22, 23, 24), total_page_count=34)

    props = _question_props(seen[0]['tools'][0])
    assert props['source_page']['enum'] == [21, 22, 23, 24]
    assert props['image_page']['enum'] == [21, 22, 23, 24, None]   # still nullable
    assert props['image_page']['type'] == ['integer', 'null']
    intro = seen[0]['messages'][0]['content'][0]['text']
    assert '21, 22, 23, 24' in intro
    # The module constant is never mutated by the per-batch copy.
    assert 'enum' not in _question_props(CLASSIFICATION_TOOL)['source_page']


def test_positional_page_numbers_are_remapped_to_absolute_ones():
    payload = {'questions': [
        # Third screenshot of the batch: page 23, not page 3.
        {'question_text': 'a', 'source_page': 3, 'image_page': 3,
         'image_box': {'x1': 60, 'y1': 4, 'x2': 93, 'y2': 25}},
        # Correct source page, positional figure page → held to the question's page.
        {'question_text': 'b', 'source_page': 23, 'image_page': 3,
         'image_box': {'x1': 10, 'y1': 40, 'x2': 50, 'y2': 60}},
        # A different REAL page in the batch is left for the cross-page guard.
        {'question_text': 'c', 'source_page': 23, 'image_page': 22},
        # Text-only: nothing to change.
        {'question_text': 'd', 'source_page': 24, 'image_page': None},
    ]}
    client = MagicMock()
    client.messages.stream.side_effect = lambda **kw: _ToolStream(payload)

    result = _classify_page_batch(client, 'sys', _pages(21, 22, 23, 24), total_page_count=34)

    assert [(q['source_page'], q['image_page']) for q in result['questions']] == [
        (23, 23), (23, 23), (23, 22), (24, None)]


def test_the_first_batch_is_unchanged():
    payload = {'questions': [{'question_text': 'q', 'source_page': 3, 'image_page': 3}]}
    client = MagicMock()
    client.messages.stream.side_effect = lambda **kw: _ToolStream(payload)
    result = _classify_page_batch(client, 'sys', _pages(1, 2, 3, 4), total_page_count=4)
    assert (result['questions'][0]['source_page'], result['questions'][0]['image_page']) == (3, 3)
