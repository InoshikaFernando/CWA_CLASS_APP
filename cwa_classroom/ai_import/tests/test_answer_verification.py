"""GPT second-opinion verifier: disagreements flag needs_review, agreements stay
quiet, and the pass is a safe no-op when unconfigured or when the API errors.

Zero-token: the OpenAI client is mocked; no API call is made.
"""
from unittest.mock import MagicMock

import pytest

from ai_import import verification
from ai_import.verification import (
    _answers_agree, _verifiable, verify_answers,
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


def test_disagreement_flags_needs_review():
    q = _mc('What colour?', 'Red', ['Red', 'Blue', 'Green'])
    client = _fake_client([{'index': 0, 'answer': 'Blue', 'confident': True}])

    summary = verify_answers([q], client=client, force=True)

    assert q['needs_review'] is True
    assert 'Blue' in q['review_reason'] and 'Red' in q['review_reason']
    assert summary['flagged'] == 1
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


def test_computed_and_image_questions_are_skipped():
    # A long_division (computed) and an image-bearing short_answer must never be
    # sent to the text verifier.
    computed = {'question_type': 'long_division', 'dividend': 611, 'divisor': 47,
                'answers': []}
    image_q = {'question_text': 'Measure the angle', 'question_type': 'short_answer',
               'image_ref': 'page1_img1.png',
               'answers': [{'text': '45', 'is_correct': True}]}
    already = _mc('Flagged', 'Red', ['Red', 'Blue'], needs_review=True)

    assert not _verifiable(computed)
    assert not _verifiable(image_q)
    assert not _verifiable(already)

    # With nothing verifiable, the pass short-circuits without calling the API.
    client = MagicMock()
    assert verify_answers([computed, image_q, already], client=client, force=True) is None
    client.chat.completions.create.assert_not_called()


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
