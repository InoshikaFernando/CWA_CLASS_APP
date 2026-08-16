"""Non-question pages (bubble answer sheets, answer keys) are never classified.

An exam paper ships with a "shade the square" answer sheet at the front and a
worked answer key at the back. Both used to be sent to Claude — paid for, and
imported as nonsense questions the teacher had to untick one by one. Detection
is deterministic and runs on the page's text before any AI call.
"""
from unittest.mock import patch

import pytest

from worksheets import services
from worksheets.services import (
    PAGE_ROLE_ANSWER_KEY,
    PAGE_ROLE_ANSWER_SHEET,
    PAGE_ROLE_QUESTIONS,
    _split_question_pages,
    detect_page_role,
)


# Text shaped like the real papers this was built from.
BUBBLE_SHEET = """Page 3 of 24
MATHEMATICS
Name........................................ Exam Number.........
Ensure that most of the square with your answer has been coloured.
*DO NOT WRITE OR MARK ANYTHING ELSE ON THIS SHEET*
""" + '\n'.join(f'{n}. A \nB \nC \nD ' for n in range(1, 21))

ANSWER_KEY = """MATHEMATICS
1
B
3 hearts and 4 triangles.
2
B
smaller < bigger
3
C
Acute angles are less than 90 degrees.
4
D
1m = 1 000mm
5
A
Working backwards 38 - 37 = 1
6
C
6:45pm to 7pm is 15 minutes.
"""

QUESTION_PAGE = """Page 23 of 24
Question 46
If a man was 1.94 metres tall, how many millimetres would he be?
A.  194mm
B.  1 094mm
C.  10 094mm
D.  1 940mm
Question 47
This is the last question. If you have any time left, check your answers.
"""


def test_bubble_answer_sheet_is_detected():
    assert detect_page_role(BUBBLE_SHEET) == PAGE_ROLE_ANSWER_SHEET


def test_worked_answer_key_is_detected():
    assert detect_page_role(ANSWER_KEY) == PAGE_ROLE_ANSWER_KEY


def test_a_question_page_with_lettered_options_is_not_an_answer_key():
    """A question's own A./B./C./D. options must not read as a key."""
    assert detect_page_role(QUESTION_PAGE) == PAGE_ROLE_QUESTIONS


def test_a_couple_of_numbered_lines_is_not_enough():
    """Two stray "3 B" lines are a coincidence, not a key."""
    assert detect_page_role('1\nB\nsome working\n2\nC\nmore working\n') == PAGE_ROLE_QUESTIONS


def test_empty_page_is_treated_as_questions():
    assert detect_page_role('') == PAGE_ROLE_QUESTIONS


def _pages(*texts):
    return [{'page_num': i, 'text': t, 'screenshot': 'x'}
            for i, t in enumerate(texts, start=1)]


def test_split_keeps_questions_and_reports_what_it_dropped():
    pages = _pages(BUBBLE_SHEET, QUESTION_PAGE, QUESTION_PAGE, ANSWER_KEY)
    keep, skipped = _split_question_pages(pages)

    assert [p['page_num'] for p in keep] == [2, 3]
    # Skipped pages come back whole, not as bare numbers — an answer key still
    # has its text read for the answers it holds.
    assert [(page['page_num'], role) for page, role in skipped] == [
        (1, PAGE_ROLE_ANSWER_SHEET),
        (4, PAGE_ROLE_ANSWER_KEY),
    ]
    assert skipped[1][0]['text'] == ANSWER_KEY


def test_split_never_drops_every_page():
    """If the detector flags everything it is the detector that is wrong."""
    keep, skipped = _split_question_pages(_pages(BUBBLE_SHEET, ANSWER_KEY))

    assert len(keep) == 2
    assert skipped == []


def test_skipping_can_be_switched_off_without_a_deploy():
    with patch.object(services, 'SKIP_NON_QUESTION_PAGES', False):
        keep, skipped = _split_question_pages(_pages(BUBBLE_SHEET, QUESTION_PAGE))

    assert len(keep) == 2
    assert skipped == []


@pytest.mark.parametrize('chunk_size', [4, 2])
def test_skipped_pages_are_reported_on_the_result(chunk_size):
    """The result carries what was skipped — the preview shows it, no silent drop."""
    pages = _pages(BUBBLE_SHEET, QUESTION_PAGE, QUESTION_PAGE, QUESTION_PAGE, ANSWER_KEY)
    classified = []

    def fake_chunk(client, system, chunk, total, shape_naming=False):
        classified.extend(p['page_num'] for p in chunk)
        return {'questions': [], 'usage': {'input_tokens': 1, 'output_tokens': 1,
                                           'total_tokens': 2}}

    with patch.object(services, 'WORKSHEET_CHUNK_SIZE', chunk_size), \
         patch.object(services, '_get_anthropic_client'), \
         patch.object(services, '_classify_page_chunk', side_effect=fake_chunk):
        result = services.classify_worksheet_questions(
            {'pages': pages, 'page_count': 5}, [], [])

    assert classified == [2, 3, 4]            # the answer sheet/key never went out
    assert result['skipped_pages'] == [
        {'page': 1, 'reason': PAGE_ROLE_ANSWER_SHEET},
        {'page': 5, 'reason': PAGE_ROLE_ANSWER_KEY},
    ]


# --- the teacher is told what was skipped ------------------------------------

def test_describe_skipped_pages_labels_each_reason():
    from worksheets.services import describe_skipped_pages
    described = describe_skipped_pages({'skipped_pages': [
        {'page': 1, 'reason': PAGE_ROLE_ANSWER_SHEET},
        {'page': 21, 'reason': PAGE_ROLE_ANSWER_KEY},
    ]})
    assert described == [
        {'page': 1, 'label': 'multiple-choice answer sheet'},
        {'page': 21, 'label': 'answer key'},
    ]


def test_describe_skipped_pages_handles_a_result_without_the_key():
    from worksheets.services import describe_skipped_pages
    assert describe_skipped_pages({}) == []
    assert describe_skipped_pages(None) == []
