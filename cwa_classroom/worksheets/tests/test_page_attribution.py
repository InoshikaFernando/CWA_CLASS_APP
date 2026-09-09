"""Questions are pinned to the ABSOLUTE page they came from, not the page's
position in the request that classified it.

The worksheet / homework importer sends four pages per request. On a 34-page
statistics PDF, page 7 went out as the third screenshot of the chunk 5–8 and the
model answered ``page_num: 3``; the renderer trusted it and cropped the figure
box from page 3 — a column-graph question arrived with a student's handwritten
notes as its "figure". These tests cover the schema pin, the deterministic
remap, and the renderer no longer defaulting an unknown page to page 1.

Zero-token: the Anthropic client is mocked; no API call is made.
"""
from unittest.mock import MagicMock

import fitz
import pytest

from worksheets import services
from worksheets.page_attribution import (
    pin_page_enum,
    resolve_chunk_pages,
    resolve_page_number,
)
from worksheets.services import WORKSHEET_CLASSIFICATION_TOOL


# --- resolve_page_number -----------------------------------------------------

@pytest.mark.parametrize('value, expected', [
    (7, (7, 'kept')),            # one of the chunk's pages
    ('7', (7, 'kept')),          # tolerated as a string
    (3, (7, 'relative')),        # third page of the chunk 5–8 → page 7
    (1, (5, 'relative')),
    (4, (8, 'relative')),
    (9, (None, 'unresolved')),   # neither a page nor a position in the chunk
    (247, (None, 'unresolved')), # the paper's own printed page number
    (None, (None, 'unresolved')),
    (0, (None, 'unresolved')),
    (True, (None, 'unresolved')),
])
def test_page_numbers_map_onto_the_chunk(value, expected):
    assert resolve_page_number(value, [5, 6, 7, 8]) == expected


def test_a_single_page_request_fills_a_missing_page():
    assert resolve_page_number(None, [12]) == (12, 'filled')


def test_the_first_chunk_is_unchanged():
    # Pages 1–4: positions and page numbers coincide, nothing to remap.
    for n in (1, 2, 3, 4):
        assert resolve_page_number(n, [1, 2, 3, 4]) == (n, 'kept')


# --- resolve_chunk_pages -----------------------------------------------------

def test_the_statistics_pdf_case_is_remapped():
    # Chunk 5–8; the model numbered the screenshots 1..4 instead of 5..8.
    questions = [{'page_num': 1}, {'page_num': 2}, {'page_num': 2},
                 {'page_num': 3}, {'page_num': 4}]
    counts = resolve_chunk_pages(questions, [5, 6, 7, 8])
    assert [q['page_num'] for q in questions] == [5, 6, 6, 7, 8]
    assert counts['relative'] == 5 and counts['kept'] == 0


def test_correct_pages_are_left_alone():
    questions = [{'page_num': 5}, {'page_num': 6}, {'page_num': 7}, {'page_num': 8}]
    counts = resolve_chunk_pages(questions, [5, 6, 7, 8])
    assert [q['page_num'] for q in questions] == [5, 6, 7, 8]
    assert counts == {'kept': 4, 'relative': 0, 'filled': 0, 'unresolved': 0}


def test_a_position_that_is_also_a_page_is_caught_by_reading_order():
    # Chunk 3–6. "3" is a real page here, but sitting between page-4 and page-6
    # questions it cannot be page 3 — read as a position it is page 5, which fits.
    questions = [{'page_num': 3}, {'page_num': 4}, {'page_num': 3}, {'page_num': 6}]
    resolve_chunk_pages(questions, [3, 4, 5, 6])
    assert [q['page_num'] for q in questions] == [3, 4, 5, 6]


def test_reading_order_does_not_touch_a_page_the_positional_reading_cannot_fix():
    # Out of order, but "3" as a position is page 5 — also outside 6..6 — so the
    # value is left as the model gave it rather than invented.
    questions = [{'page_num': 6}, {'page_num': 3}, {'page_num': 6}]
    resolve_chunk_pages(questions, [3, 4, 5, 6])
    assert [q['page_num'] for q in questions] == [6, 3, 6]


def test_a_missing_page_is_filled_only_when_the_neighbours_agree():
    questions = [{'page_num': 6}, {}, {'page_num': 6}, {}, {'page_num': 7}]
    counts = resolve_chunk_pages(questions, [5, 6, 7, 8])
    assert [q.get('page_num') for q in questions] == [6, 6, 6, None, 7]
    assert counts['filled'] == 1 and counts['unresolved'] == 1


def test_an_impossible_page_becomes_none_not_page_one():
    questions = [{'page_num': 247}]
    resolve_chunk_pages(questions, [5, 6, 7, 8])
    assert questions[0]['page_num'] is None


def test_figure_page_follows_the_question_page_under_the_positional_reading():
    # ai_import shape: source_page + image_page. Question on page 23 whose figure
    # page "3" is the third page of the batch 21–24 → page 23. A figure page that
    # is a different REAL page of the batch is left for the cross-page guard.
    questions = [
        {'source_page': 3, 'image_page': 3},
        {'source_page': 23, 'image_page': 3},
        {'source_page': 23, 'image_page': 22},
        {'source_page': 24, 'image_page': None},
    ]
    resolve_chunk_pages(questions, [21, 22, 23, 24],
                        field='source_page', figure_field='image_page')
    assert [(q['source_page'], q['image_page']) for q in questions] == [
        (23, 23), (23, 23), (23, 22), (24, None)]


def test_non_dict_rows_are_ignored():
    questions = ['garbage', {'page_num': 2}]
    resolve_chunk_pages(questions, [5, 6])
    assert questions[1]['page_num'] == 6


# --- pin_page_enum -----------------------------------------------------------

def test_the_tool_schema_is_pinned_to_the_chunk_pages_without_mutating_the_constant():
    pinned = pin_page_enum(WORKSHEET_CLASSIFICATION_TOOL, ('page_num',), [5, 6, 7, 8])
    spec = pinned['input_schema']['properties']['questions']['items']['properties']['page_num']
    assert spec['enum'] == [5, 6, 7, 8]
    assert 'position' in spec['description']
    original = (WORKSHEET_CLASSIFICATION_TOOL['input_schema']['properties']
                ['questions']['items']['properties']['page_num'])
    assert 'enum' not in original


def test_a_nullable_figure_page_keeps_null_in_the_enum():
    tool = {'input_schema': {'properties': {'questions': {'items': {'properties': {
        'image_page': {'type': 'integer', 'description': 'figure page'},
    }}}}}}
    pinned = pin_page_enum(tool, ('image_page',), [21, 22], nullable=('image_page',))
    spec = pinned['input_schema']['properties']['questions']['items']['properties']['image_page']
    assert spec['enum'] == [21, 22, None]
    assert spec['type'] == ['integer', 'null']


def test_a_tool_of_another_shape_is_returned_untouched():
    tool = {'name': 'x', 'input_schema': {'type': 'object'}}
    assert pin_page_enum(tool, ('page_num',), [1, 2]) is tool


# --- _classify_page_chunk end to end (mocked client) ------------------------

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
        block.name = 'classify_worksheet_questions'
        block.input = self.payload
        resp = MagicMock(stop_reason='tool_use')
        resp.content = [block]
        resp.usage.input_tokens = 10
        resp.usage.output_tokens = 5
        return resp


def _pages(*nums):
    return [{'page_num': n, 'screenshot': 'x', 'screenshot_w': 1241,
             'screenshot_h': 1755, 'text': ''} for n in nums]


def test_classify_chunk_pins_the_schema_and_remaps_positions_to_pages():
    seen = []
    payload = {'questions': [
        {'question_text': 'income graph', 'page_num': 2, 'has_image': True},
        {'question_text': 'A survey is conducted…', 'page_num': 3, 'has_image': True},
        {'question_text': 'stem and leaf', 'page_num': 4, 'has_image': True},
    ]}
    client = MagicMock()

    def stream(**kw):
        seen.append(kw)
        return _ToolStream(payload)
    client.messages.stream.side_effect = stream

    result = services._classify_page_chunk(client, 'sys', _pages(5, 6, 7, 8), 34)

    # The request itself asks for the real numbers…
    tool = seen[0]['tools'][0]
    spec = tool['input_schema']['properties']['questions']['items']['properties']['page_num']
    assert spec['enum'] == [5, 6, 7, 8]
    intro = seen[0]['messages'][0]['content'][0]['text']
    assert 'page(s) 5, 6, 7, 8' in intro
    # …and a positional answer is still corrected on the way back.
    assert [q['page_num'] for q in result['questions']] == [6, 7, 8]


def test_classify_chunk_keeps_absolute_pages_as_given():
    payload = {'questions': [{'question_text': 'q', 'page_num': 7, 'has_image': False}]}
    client = MagicMock()
    client.messages.stream.side_effect = lambda **kw: _ToolStream(payload)
    result = services._classify_page_chunk(client, 'sys', _pages(5, 6, 7, 8), 34)
    assert result['questions'][0]['page_num'] == 7


# --- render_question_images: no page-1 default ------------------------------

def _three_page_pdf():
    """Pages 1 and 3 each carry a filled rectangle at the same spot; page 2 is blank."""
    doc = fitz.open()
    for n in (1, 2, 3):
        page = doc.new_page(width=400, height=500)
        if n != 2:
            page.draw_rect(fitz.Rect(120, 150, 280, 260), color=(0, 0, 0),
                           fill=(0.6, 0.6, 0.6))
    return doc


def test_a_question_with_no_page_is_flagged_rather_than_cropped_from_page_one():
    doc = _three_page_pdf()
    try:
        pages = services.extract_worksheet_pages(doc)
        ss_w, ss_h = pages['pages'][0]['screenshot_w'], pages['pages'][0]['screenshot_h']
        bbox = [0.25 * ss_w, 0.25 * ss_h, 0.75 * ss_w, 0.60 * ss_h]
        result = {'questions': [
            {'question_text': 'no page', 'has_image': True, 'image_bbox': list(bbox)},
            {'question_text': 'impossible page', 'has_image': True,
             'image_bbox': list(bbox), 'page_num': None},
            {'question_text': 'page 3', 'has_image': True,
             'image_bbox': list(bbox), 'page_num': 3},
        ]}
        result, images = services.render_question_images(doc, pages, result)
    finally:
        doc.close()

    q_none, q_null, q3 = result['questions']
    for q in (q_none, q_null):
        assert q['image_ref'] is None
        assert q['has_image'] is False
        assert q['needs_review'] is True
        assert 'page' in q['review_reason']
    assert q3['image_ref'] == 'worksheet_img_q3_p3.png'
    assert q3['image_page'] == 3
    assert set(images) == {'worksheet_img_q3_p3.png'}


def test_a_figure_with_no_box_is_flagged_for_the_teacher():
    doc = _three_page_pdf()
    try:
        pages = services.extract_worksheet_pages(doc)
        result = {'questions': [
            {'question_text': 'boxless', 'has_image': True, 'page_num': 1},
        ]}
        result, images = services.render_question_images(doc, pages, result)
    finally:
        doc.close()
    q = result['questions'][0]
    assert images == {}
    assert q['has_image'] is False and q['needs_review'] is True
    assert 'box' in q['review_reason']
