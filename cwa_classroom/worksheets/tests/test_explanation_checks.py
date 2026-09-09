"""An explanation that contradicts itself is a wrong answer announcing itself.

Two real imports from a Year 7 statistics paper: a stem-and-leaf plot with 14
leaves came back as "There are 15 values in order: <fourteen numbers> … the 8th
value (the middle of 15 values) is 25" — the 8th number it listed is 27, and
the median of 14 values is 26 — and a count explained as "stem 3 has 4 leaves,
giving 3 + 8 + 4 = 15" over a stem with 3. A teacher also reported sums like
"10 + 5 + 2 = 18". These checks catch each of those from the text alone and
route the question to review; a clean explanation is never flagged.
"""
from unittest.mock import MagicMock

import pytest

from worksheets import services
from worksheets.explanation_checks import (
    arithmetic_slips,
    count_slips,
    explanation_problems,
    flag_explanation_problems,
    ordinal_slips,
)

MEDIAN_SLIP = (
    'There are 15 values in order: 14, 17, 18, 20, 22, 24, 25, 27, 28, 28, 29, 30, 33, '
    '37 … reading the ordered list, the 8th value (the middle of 15 values) is 25°C.'
)


# --- arithmetic -------------------------------------------------------------

@pytest.mark.parametrize('text, expected', [
    ('10 + 5 + 2 = 18', [('10 + 5 + 2', '18', '17')]),
    ('so 10+5+2 = 18 towns', [('10+5+2', '18', '17')]),
    ('3 + 8 + 4 = 15 towns.', []),                       # correct arithmetic
    ('4 × 3 = 12 and 12 − 5 = 7', []),
    ('4 × 3 = 13', [('4 × 3', '13', '12')]),
    ('2 + 3 × 4 = 14', []),                              # precedence honoured
    ('2 + 3 × 4 = 20', [('2 + 3 × 4', '20', '14')]),
    ('10 ÷ 3 = 3.33', []),                               # rounded, not wrong
    ('10 ÷ 4 = 2.5', []),
    ('1/2 + 1/4 = 3/4', []),                             # fractions both sides
    ('1,200 + 300 = 1,500', []),                         # thousands commas
    ('x + 2 = 5 so x = 3', []),                          # algebra: not judged
    ('2^3 = 8', []),                                     # powers: not judged
    ('10% of 50 = 5', []),                               # percentages: not judged
    ('', []),
    (None, []),
])
def test_arithmetic_slips(text, expected):
    assert arithmetic_slips(text) == expected


# --- counts vs the list written out -----------------------------------------

def test_a_count_that_precedes_a_shorter_list_is_a_slip():
    slips = count_slips(MEDIAN_SLIP)
    assert slips == [(15, 14, '14, 17, 18, 20, 22, 24, …')]


def test_a_count_that_matches_its_list_is_fine():
    assert count_slips('There are 5 values: 3, 4, 7, 9, 12.') == []


def test_a_count_after_the_list_is_checked_too():
    assert count_slips('stem 3: 0, 3, 7 → 4 leaves') == [(4, 3, '0, 3, 7')]
    assert count_slips('stem 3: 0, 3, 7 (3 leaves); stem 2: 0, 2, 4, 5 (4 leaves)') == []
    assert count_slips('the scores 12, 15 and 18, giving 3 scores') == []


def test_short_lists_and_unrelated_numbers_do_not_count():
    # Two numbers are not a list; "8 marks" is not a claim about a list.
    assert count_slips('The totals 12, 15 give 8 marks') == []
    assert count_slips('Angles are 30, 60 and 90, worth 15 minutes of work') == []


# --- ordinals vs the list --------------------------------------------------

def test_an_ordinal_that_disagrees_with_the_list_is_a_slip():
    assert ordinal_slips(MEDIAN_SLIP) == [('8th', '25', '27')]


def test_an_ordinal_that_matches_is_fine():
    text = 'Ordered: 3, 5, 8, 9, 12. The 3rd value is 8, so the median is 8.'
    assert ordinal_slips(text) == []


def test_an_ordinal_with_no_list_before_it_is_not_judged():
    assert ordinal_slips('The 8th value is 25.') == []


# --- the per-question reasons and the pipeline flag --------------------------

def test_explanation_problems_names_every_contradiction():
    reasons = explanation_problems({'explanation': MEDIAN_SLIP})
    assert len(reasons) == 2
    assert 'says there are 15 but lists 14' in reasons[0]
    assert '8th value is 25' in reasons[1] and 'its own list is 27' in reasons[1]


def test_flag_routes_only_contradicted_questions_to_review():
    questions = [
        {'explanation': MEDIAN_SLIP},
        {'explanation': 'Count the leaves: 3 + 8 + 3 = 14 towns.'},
        {'explanation': '10 + 5 + 2 = 18', 'needs_review': True, 'review_reason': 'GPT disagreed.'},
        'not a dict',
    ]
    assert flag_explanation_problems(questions) == 2
    assert questions[0]['needs_review'] is True
    assert 'lists 14' in questions[0]['review_reason']
    assert 'needs_review' not in questions[1]
    # An existing reason is kept, the contradiction appended.
    assert questions[2]['review_reason'].startswith('GPT disagreed.')
    assert 'does not add up: 10 + 5 + 2 = 18 (it makes 17)' in questions[2]['review_reason']


def test_answer_review_warning_surfaces_a_contradiction_on_the_review_screen():
    q = {'question_type': 'short_answer', 'explanation': MEDIAN_SLIP,
         'answers': [{'text': '25', 'is_correct': True}]}
    warning = services.answer_review_warning(q)
    assert warning and 'lists 14' in warning


def test_answer_review_warning_is_silent_on_a_clean_explanation():
    q = {'question_type': 'short_answer',
         'explanation': 'Ordered: 14, 17, 18, 20, 22, 24, 25, 27, 28, 28, 29, 30, 33, 37 '
                        '(14 values). The 7th and 8th values are 25 and 27, so the median '
                        'is (25 + 27) ÷ 2 = 26.',
         'answers': [{'text': '26', 'is_correct': True}]}
    assert services.answer_review_warning(q) is None


# --- the worksheet classifier thinks before it answers ------------------------

class _Stream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.response


def _tool_response(payload):
    block = MagicMock()
    block.type = 'tool_use'
    block.name = 'classify_worksheet_questions'
    block.input = payload
    resp = MagicMock(stop_reason='tool_use')
    resp.content = [block]
    resp.usage.input_tokens = 1
    resp.usage.output_tokens = 1
    return resp


def _text_response(text):
    block = MagicMock()
    block.type = 'text'
    block.text = text
    resp = MagicMock(stop_reason='end_turn')
    resp.content = [block]
    resp.usage.input_tokens = 1
    resp.usage.output_tokens = 1
    return resp


def _pages():
    return [{'page_num': 1, 'screenshot': 'x', 'screenshot_w': 10, 'screenshot_h': 10, 'text': ''}]


def test_classifier_uses_adaptive_thinking_with_auto_tool_choice():
    seen = []
    client = MagicMock()

    def stream(**kw):
        seen.append(kw)
        return _Stream(_tool_response({'questions': [{'question_text': 'q', 'page_num': 1}]}))
    client.messages.stream.side_effect = stream

    result = services._classify_page_chunk(client, 'sys', _pages(), 1)

    assert len(seen) == 1
    assert seen[0]['thinking'] == {'type': 'adaptive'}
    assert seen[0]['tool_choice'] == {'type': 'auto'}
    assert result['questions'][0]['question_text'] == 'q'


def test_a_reply_without_the_tool_call_is_retried_with_the_call_forced():
    seen = []
    client = MagicMock()
    replies = iter([
        _text_response('Here are the questions I found: …'),
        _tool_response({'questions': [{'question_text': 'q', 'page_num': 1}]}),
    ])

    def stream(**kw):
        seen.append(kw)
        return _Stream(next(replies))
    client.messages.stream.side_effect = stream

    result = services._classify_page_chunk(client, 'sys', _pages(), 1)

    assert len(seen) == 2
    assert seen[1]['thinking'] == {'type': 'disabled'}
    assert seen[1]['tool_choice'] == {'type': 'tool', 'name': 'classify_worksheet_questions'}
    assert result['questions'][0]['question_text'] == 'q'


def test_thinking_can_be_switched_off_by_env(monkeypatch):
    monkeypatch.setenv('WORKSHEET_THINKING', '0')
    seen = []
    client = MagicMock()

    def stream(**kw):
        seen.append(kw)
        return _Stream(_tool_response({'questions': []}))
    client.messages.stream.side_effect = stream

    services._classify_page_chunk(client, 'sys', _pages(), 1)

    assert len(seen) == 1
    assert seen[0]['thinking'] == {'type': 'disabled'}
    assert seen[0]['tool_choice']['type'] == 'tool'
