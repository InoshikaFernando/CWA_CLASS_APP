"""A question that points at a picture must not arrive without one.

A Year 2 sheet had "Tick the cylinder" beside a cube, a cylinder and a
triangle. It came through as a multiple choice with NO image and options that
described the pictures in words ("the can-shaped solid") — unanswerable as a
picture question and giving the answer away as a text one. Two things caught
it: the shared wording guard now reads "tick the ‹shape›" / "the three shapes
shown" as a figure reference, and the worksheet / homework pipeline runs that
guard after cropping (until now only the AI import did).
"""
from unittest.mock import MagicMock, patch

from ai_import.verification import flag_missing_figures
from maths.answer_verification import FIGURE_REFERENCE_RE
from worksheets import services


def _q(text, **over):
    q = {'question_text': text, 'question_type': 'multiple_choice', 'answers': []}
    q.update(over)
    return q


def test_the_worksheets_wording_is_a_figure_reference():
    for text in [
        'Tick the cylinder. Which of the three shapes shown is the cylinder?',
        'Tick the cylinder.',
        'Tick the smallest square.',
        'Circle the shape with four sides.',
        'Colour all the triangles.',
        'Which of the shapes shown has a curved face?',
    ]:
        assert FIGURE_REFERENCE_RE.search(text), text


def test_wording_answerable_from_print_is_not_swept_in():
    for text in [
        'Circle the number that is more than twenty.',
        'Double 4.',
        'What is sixteen take away two?',
        'Tick the correct answer.',
        'Circle the odd one out: 3, 6, 9, 10.',
    ]:
        assert not FIGURE_REFERENCE_RE.search(text), text


def test_a_figureless_tick_the_shape_question_is_flagged():
    q = _q('Tick the cylinder. Which of the three shapes shown is the cylinder?')
    assert flag_missing_figures([q]) == 1
    assert q['needs_review'] is True
    assert 'no image was attached' in q['review_reason']


def test_the_same_question_with_its_picture_is_not_flagged():
    q = _q('Tick the cylinder.', image_ref='worksheet_img_q6_p2.png')
    assert flag_missing_figures([q]) == 0
    assert 'needs_review' not in q


def test_the_worksheet_pipeline_runs_the_guard_after_cropping():
    questions = [
        _q('Tick the cylinder. Which of the three shapes shown is the cylinder?',
           has_image=False),
        _q('Double 4.', question_type='short_answer'),
    ]
    with patch.dict('sys.modules', {'fitz': MagicMock()}), \
         patch('worksheets.services.extract_worksheet_pages',
               return_value={'pages': [], 'page_count': 1}), \
         patch('worksheets.services.classify_worksheet_questions',
               return_value={'questions': questions, 'usage': {'total_tokens': 0}}), \
         patch('worksheets.services.render_question_images',
               side_effect=lambda doc, pages, result, progress=None: (result, {})):
        output = services.extract_and_classify_worksheet(
            MagicMock(read=lambda: b'%PDF-1.4'), [], [])

    tick, double = output['result']['questions']
    assert tick['needs_review'] is True
    assert 'refers to a figure' in tick['review_reason']
    assert 'needs_review' not in double


def test_prompt_tells_the_model_how_to_write_a_pick_the_picture_question():
    prompt = services._build_system_prompt([], [])
    assert 'PICK THE PICTURED ITEM' in prompt
    assert 'never has_image=false' in prompt
    assert 'NEVER name or describe what the' in prompt
