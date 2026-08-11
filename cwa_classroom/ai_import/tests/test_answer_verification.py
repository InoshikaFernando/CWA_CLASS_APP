"""GPT second-opinion verifier (vision-enabled): disagreements on classification,
answer, or transcription flag needs_review; agreements stay quiet; and the pass is
a safe no-op when unconfigured or when the API errors.

Zero-token: the OpenAI client is mocked; no API call is made.
"""
from unittest.mock import MagicMock

import pytest

from ai_import import verification
from ai_import.verification import (
    _answers_agree, _resolve_page, _types_conflict, verify_answers,
)


def _fake_client(results):
    """An OpenAI client whose chat completion returns ``results`` via the tool call."""
    import json

    tool_call = MagicMock()
    tool_call.function.arguments = json.dumps({'results': results})
    message = MagicMock(tool_calls=[tool_call])
    resp = MagicMock(choices=[MagicMock(message=message)])
    resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

    client = MagicMock()
    client.chat.completions.create.return_value = resp
    return client


def _mc(text, correct, options, **extra):
    return {
        'question_text': text,
        'question_type': 'multiple_choice',
        'answers': [
            {'text': o, 'is_correct': (o == correct)} for o in options
        ],
        **extra,
    }


# ---------------------------------------------------------------------------
# Answer disagreement (works with or without a page image)
# ---------------------------------------------------------------------------

def test_disagreement_flags_needs_review():
    q = _mc('What colour?', 'Red', ['Red', 'Blue', 'Green'])
    client = _fake_client([{'index': 0, 'answer': 'Blue', 'confident': True}])

    summary = verify_answers([q], client=client, force=True)

    assert q['needs_review'] is True
    assert 'Blue' in q['review_reason'] and 'Red' in q['review_reason']
    assert summary['flagged'] == 1
    assert summary['answer_flags'] == 1
    assert summary['checked'] == 1


def test_agreement_leaves_question_untouched():
    q = _mc('What colour?', 'Red', ['Red', 'Blue', 'Green'])
    client = _fake_client([{'index': 0, 'answer': 'Red', 'confident': True}])

    summary = verify_answers([q], client=client, force=True)

    assert 'needs_review' not in q
    assert summary['flagged'] == 0


def test_unconfident_verifier_does_not_flag():
    q = _mc('Tricky?', 'Red', ['Red', 'Blue'])
    client = _fake_client([{'index': 0, 'answer': '', 'confident': False}])

    summary = verify_answers([q], client=client, force=True)

    assert 'needs_review' not in q
    assert summary['flagged'] == 0


# ---------------------------------------------------------------------------
# Classification disagreement (new)
# ---------------------------------------------------------------------------

def test_classification_disagreement_flags():
    # Claude called it multiple_choice; the verifier confidently says it is a
    # free-response question (a different type bucket) → flag for the teacher.
    q = _mc('2 + 2 = ?', 'Four', ['Four'])
    client = _fake_client([{
        'index': 0, 'question_type': 'short_answer',
        'answer': 'Four', 'confident': True,
    }])

    summary = verify_answers([q], client=client, force=True)

    assert q['needs_review'] is True
    assert 'short_answer' in q['review_reason']
    assert summary['type_flags'] == 1


def test_same_bucket_type_difference_is_not_flagged():
    # short_answer vs calculation live in the same "free" bucket — interchangeable,
    # so a mismatch there is noise and must NOT flag.
    q = {
        'question_text': '3 x 4 = ?', 'question_type': 'short_answer',
        'answers': [{'text': '12', 'is_correct': True}],
    }
    client = _fake_client([{
        'index': 0, 'question_type': 'calculation',
        'answer': '12', 'confident': True,
    }])

    summary = verify_answers([q], client=client, force=True)

    assert 'needs_review' not in q
    assert summary['type_flags'] == 0


# ---------------------------------------------------------------------------
# Vision: transcription check + image attachment
# ---------------------------------------------------------------------------

def test_vision_transcription_mismatch_flags():
    q = {
        'question_text': 'Solve using long division: 611 ÷ 47',
        'question_type': 'long_division', 'dividend': 611, 'divisor': 47,
        'answers': [], 'source_page': 1,
    }
    client = _fake_client([{
        'index': 0, 'question_type': 'long_division', 'answer': '13',
        'confident': True, 'transcription_ok': False,
        'issue': 'the page shows 671 ÷ 47, not 611',
    }])

    summary = verify_answers([q], page_images={1: 'ZmFrZQ=='},
                             client=client, force=True)

    assert q['needs_review'] is True
    assert '671' in q['review_reason']
    assert summary['transcription_flags'] == 1
    assert summary['vision'] is True


def test_page_image_is_attached_when_available():
    q = _mc('What colour?', 'Red', ['Red', 'Blue'], source_page=2)
    client = _fake_client([{
        'index': 0, 'question_type': 'multiple_choice', 'answer': 'Red',
        'confident': True, 'transcription_ok': True,
    }])

    verify_answers([q], page_images={2: 'aW1hZ2U='}, client=client, force=True)

    # The request carried the page screenshot as an image_url content block.
    _, kwargs = client.chat.completions.create.call_args
    user_msg = kwargs['messages'][-1]
    image_parts = [p for p in user_msg['content'] if p.get('type') == 'image_url']
    assert len(image_parts) == 1
    assert 'aW1hZ2U=' in image_parts[0]['image_url']['url']


def test_transcription_ignored_without_image():
    # No page image → the model cannot judge transcription, so a transcription_ok
    # False it returns is ignored rather than flagged.
    q = _mc('What colour?', 'Red', ['Red', 'Blue'])
    client = _fake_client([{
        'index': 0, 'question_type': 'multiple_choice', 'answer': 'Red',
        'confident': True, 'transcription_ok': False, 'issue': 'cannot see',
    }])

    summary = verify_answers([q], client=client, force=True)  # no page_images

    assert 'needs_review' not in q
    assert summary['transcription_flags'] == 0
    assert summary['vision'] is False


# ---------------------------------------------------------------------------
# Read-off numeric answers (read_graph / measure): answer lives in
# numeric_answer, compared with the question's tolerance band
# ---------------------------------------------------------------------------

def test_read_graph_numeric_answer_disagreement_flags():
    # Real case: a protractor read-off Claude extracted as 75° (±4); the verifier,
    # reading the page image, gets 110° — outside tolerance → flag for review.
    q = {
        'question_text': 'Using the protractor, read off the value of the marked angle:',
        'question_type': 'read_graph', 'numeric_answer': 75,
        'answer_tolerance': 4, 'answer_unit': '°', 'answers': [], 'source_page': 1,
    }
    client = _fake_client([{
        'index': 0, 'question_type': 'read_graph', 'answer': '110°',
        'confident': True, 'transcription_ok': True,
    }])

    summary = verify_answers([q], page_images={1: 'ZmFrZQ=='},
                             client=client, force=True)

    assert q['needs_review'] is True
    assert '110' in q['review_reason'] and '75' in q['review_reason']
    assert summary['answer_flags'] == 1


def test_read_graph_within_tolerance_stays_quiet():
    q = {
        'question_text': 'Read the dial:', 'question_type': 'measure',
        'numeric_answer': 110, 'answer_tolerance': 4, 'answer_unit': '°',
        'answers': [], 'source_page': 1,
    }
    client = _fake_client([{
        'index': 0, 'question_type': 'measure', 'answer': '108',
        'confident': True, 'transcription_ok': True,
    }])

    summary = verify_answers([q], page_images={1: 'ZmFrZQ=='},
                             client=client, force=True)

    assert 'needs_review' not in q          # 108 within ±4 of 110
    assert summary['answer_flags'] == 0


# ---------------------------------------------------------------------------
# Coverage now includes computed / image-dependent types
# ---------------------------------------------------------------------------

def test_computed_and_image_questions_are_now_checked():
    # Previously these were skipped by the text-only verifier; with vision they are
    # candidates and get sent to the model.
    computed = {'question_text': 'Solve: 611 ÷ 47', 'question_type': 'long_division',
                'dividend': 611, 'divisor': 47, 'answers': [], 'source_page': 1}
    image_q = {'question_text': 'Measure the angle', 'question_type': 'measure',
               'image_ref': 'page1_img1.png', 'answers': []}
    already = _mc('Flagged', 'Red', ['Red', 'Blue'], needs_review=True)

    client = _fake_client([
        {'index': 0, 'question_type': 'long_division', 'answer': '13',
         'confident': True, 'transcription_ok': True},
        {'index': 1, 'question_type': 'measure', 'answer': '45',
         'confident': True, 'transcription_ok': True},
    ])

    summary = verify_answers([computed, image_q, already],
                             page_images={1: 'ZmFrZQ=='}, client=client, force=True)

    # The API WAS called (the two unflagged questions were verified)...
    client.chat.completions.create.assert_called()
    # ...the already-flagged question is never re-touched (no review_reason added)...
    assert already['needs_review'] is True
    assert 'review_reason' not in already
    # ...and with the model agreeing, nothing new is flagged.
    assert summary['flagged'] == 0
    assert summary['checked'] == 2


# ---------------------------------------------------------------------------
# Safety: disabled / API failure never break the import
# ---------------------------------------------------------------------------

def test_disabled_when_no_key(monkeypatch):
    monkeypatch.setattr(verification.settings, 'OPENAI_API_KEY', '', raising=False)
    q = _mc('What colour?', 'Red', ['Red', 'Blue'])

    # force=False → honours the gate; returns None and does nothing.
    assert verify_answers([q], client=MagicMock()) is None
    assert 'needs_review' not in q


def test_api_failure_leaves_import_intact():
    q = _mc('What colour?', 'Red', ['Red', 'Blue'])
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError('boom')

    summary = verify_answers([q], client=client, force=True)

    # Import proceeds: question unchanged, failure surfaced in the summary.
    assert 'needs_review' not in q
    assert summary['flagged'] == 0
    assert summary['error'] == 'boom'


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('gpt, correct, agree', [
    ('60', ['60 months', '60'], True),       # exact form present
    ('60 months', ['60'], True),             # unit variant → same leading number
    ('$4.50', ['4.50'], True),               # currency variant
    ('3/4', ['3/4'], True),
    ('Blue', ['Red'], False),                # genuine disagreement
    ('', ['Red'], True),                     # no GPT answer → no signal, stay quiet
])
def test_answers_agree_numeric_and_unit_tolerance(gpt, correct, agree):
    assert _answers_agree(gpt, correct) is agree


@pytest.mark.parametrize('claude, gpt, conflict', [
    ('multiple_choice', 'short_answer', True),    # choice vs free → conflict
    ('short_answer', 'calculation', False),       # same free bucket
    ('multiple_choice', 'true_false', False),     # same choice bucket
    ('long_division', 'measure', True),           # free vs measure → conflict
    ('short_answer', None, False),                # missing → no signal
    ('short_answer', 'not_a_type', False),        # unknown vocab → no signal
])
def test_types_conflict(claude, gpt, conflict):
    assert _types_conflict(claude, gpt) is conflict


@pytest.mark.parametrize('q, page', [
    ({'source_page': 3}, 3),
    ({'image_page': 2}, 2),
    ({'image_ref': 'page5_img1.png'}, 5),
    ({'source_page': 4, 'image_page': 9}, 4),     # source_page wins
    ({}, None),
    ({'source_page': True}, None),                # bool is not a page number
])
def test_resolve_page(q, page):
    assert _resolve_page(q) == page


# ---------------------------------------------------------------------------
# Visual comparison guard (deterministic, no API): "which figure is larger / are
# they equal" questions with a figure are routed to review unconditionally,
# because both models read the same coarse figure the same wrong way and so
# agree on a wrong answer that the disagreement check never catches.
# ---------------------------------------------------------------------------

from ai_import.verification import _is_visual_comparison, flag_visual_comparisons


def test_comparison_with_figure_flagged_even_when_equal_is_marked():
    # The reported case #1: answer marked "A is larger" but truly equal, and #2:
    # marked "They are the same size" but not — either way the class is flagged.
    q = _mc(
        'Decide which of the angles A and B is larger, if any, in this case.',
        'They are the same size',
        ['They are the same size', 'A is larger', 'B is larger'],
        image_ref='page1_img1.png',
    )

    flagged = flag_visual_comparisons([q])

    assert flagged == 1
    assert q['needs_review'] is True
    assert 'confirm the correct answer' in q['review_reason']


def test_comparison_with_figure_flagged_when_larger_is_marked():
    q = _mc(
        'Decide which of the angles A and B is larger, if any, in this case.',
        'A is larger',
        ['A is larger', 'B is larger', 'Equal'],
        image_ref='page1_img1.png',
    )

    assert flag_visual_comparisons([q]) == 1
    assert q['needs_review'] is True


def test_equal_option_alone_triggers_flag_without_comparison_wording():
    # Terse stem, but the "same size" option marks it as a figure comparison.
    q = _mc(
        'Angles A and B?',
        'They are the same size',
        ['They are the same size', 'They are different'],
        image_page=2,
    )

    assert flag_visual_comparisons([q]) == 1
    assert q['needs_review'] is True


def test_text_only_comparison_is_not_flagged():
    # No figure → the models handle it reliably, so leave it alone.
    q = _mc('Which is larger, 2/3 or 3/5?', '2/3', ['2/3', '3/5'])

    assert flag_visual_comparisons([q]) == 0
    assert 'needs_review' not in q


def test_figure_without_comparison_language_is_not_flagged():
    # A plain read-off question with a figure but no comparison wording.
    q = {
        'question_text': 'Measure the angle shown.',
        'question_type': 'measure',
        'numeric_answer': '45',
        'image_ref': 'page1_img2.png',
    }

    assert flag_visual_comparisons([q]) == 0
    assert 'needs_review' not in q


def test_already_flagged_question_is_left_untouched():
    q = _mc(
        'Which angle is larger?', 'A is larger',
        ['A is larger', 'B is larger'],
        image_ref='page1_img1.png', needs_review=True,
        review_reason='pre-existing reason',
    )

    assert flag_visual_comparisons([q]) == 0
    assert q['review_reason'] == 'pre-existing reason'


@pytest.mark.parametrize('q, expected', [
    ({'question_text': 'which is bigger?', 'image_ref': 'p.png'}, True),
    ({'question_text': 'compare the two shapes', 'image_page': 1}, True),
    ({'question_text': 'which is bigger?'}, False),                  # no figure
    ({'question_text': 'name this shape', 'image_ref': 'p.png'}, False),  # no comparison
])
def test_is_visual_comparison(q, expected):
    assert _is_visual_comparison(q) is expected
