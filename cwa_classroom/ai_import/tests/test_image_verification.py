"""Vision second-opinion image validator: a confident mismatch flags needs_review,
a match stays quiet, and the pass is a safe no-op when unconfigured, when there is
nothing to check, or when the API errors.

Zero-token: the OpenAI client is mocked; no API call is made.
"""
from unittest.mock import MagicMock

from ai_import import verification
from ai_import.verification import (
    _image_media_type, _image_verifiable, verify_images,
)


def _fake_client(results):
    """An OpenAI client whose chat completion returns ``results`` via the tool call."""
    import json

    tool_call = MagicMock()
    tool_call.function.arguments = json.dumps({'results': results})
    message = MagicMock(tool_calls=[tool_call])
    resp = MagicMock(choices=[MagicMock(message=message)])
    resp.usage = MagicMock(prompt_tokens=20, completion_tokens=8)

    client = MagicMock()
    client.chat.completions.create.return_value = resp
    return client


def _q(text='Find the angle', ref='page7_img1.jpeg', **extra):
    return {'question_text': text, 'question_type': 'short_answer',
            'image_ref': ref, **extra}


IMAGES = {'page7_img1.jpeg': 'AAAA', 'page7_figure2.png': 'BBBB'}


def test_confident_mismatch_flags_needs_review():
    q = _q()
    client = _fake_client([
        {'index': 0, 'matches': False, 'confident': True,
         'reason': 'decorative hand-drawing, not the angle figure'},
    ])

    summary = verify_images([q], IMAGES, client=client, force=True)

    assert q['needs_review'] is True
    assert 'Image check' in q['review_reason']
    assert 'decorative' in q['review_reason']
    assert summary['flagged'] == 1
    assert summary['checked'] == 1


def test_match_leaves_question_untouched():
    q = _q()
    client = _fake_client([{'index': 0, 'matches': True, 'confident': True}])

    summary = verify_images([q], IMAGES, client=client, force=True)

    assert 'needs_review' not in q
    assert summary['flagged'] == 0


def test_unconfident_mismatch_does_not_flag():
    q = _q()
    client = _fake_client([{'index': 0, 'matches': False, 'confident': False}])

    summary = verify_images([q], IMAGES, client=client, force=True)

    assert 'needs_review' not in q
    assert summary['flagged'] == 0


def test_questions_without_image_are_skipped():
    # No image_ref, an already-flagged question, and a ref with no bytes are all
    # skipped; with nothing to check the pass short-circuits without an API call.
    no_image = {'question_text': 'text only', 'question_type': 'short_answer'}
    already = _q(needs_review=True)
    dangling = _q(ref='missing.png')  # ref not present in IMAGES

    assert not _image_verifiable(no_image)
    assert not _image_verifiable(already)
    assert _image_verifiable(dangling)  # verifiable, but has no bytes → skipped

    client = MagicMock()
    assert verify_images([no_image, already, dangling], IMAGES,
                         client=client, force=True) is None
    client.chat.completions.create.assert_not_called()


def test_disabled_when_no_key(monkeypatch):
    monkeypatch.setattr(verification.settings, 'OPENAI_API_KEY', '', raising=False)
    q = _q()

    # force=False → honours the gate; returns None and does nothing.
    assert verify_images([q], IMAGES, client=MagicMock()) is None
    assert 'needs_review' not in q


def test_disabled_by_toggle(monkeypatch):
    monkeypatch.setattr(verification.settings, 'OPENAI_API_KEY', 'sk-x', raising=False)
    monkeypatch.setenv('AI_IMPORT_VERIFY_IMAGES_ENABLED', '0')
    q = _q()

    assert verify_images([q], IMAGES, client=MagicMock()) is None
    assert 'needs_review' not in q


def test_api_failure_leaves_import_intact():
    q = _q()
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError('boom')

    summary = verify_images([q], IMAGES, client=client, force=True)

    # Import proceeds: question unchanged, failure surfaced in the summary.
    assert 'needs_review' not in q
    assert summary['flagged'] == 0
    assert summary['error'] == 'boom'


def test_only_the_mismatched_question_in_a_batch_is_flagged():
    q_ok = _q('Read the graph', ref='page7_figure2.png')
    q_bad = _q('Find the angle', ref='page7_img1.jpeg')
    client = _fake_client([
        {'index': 0, 'matches': True, 'confident': True},
        {'index': 1, 'matches': False, 'confident': True, 'reason': 'wrong figure'},
    ])

    summary = verify_images([q_ok, q_bad], IMAGES, client=client, force=True)

    assert 'needs_review' not in q_ok
    assert q_bad['needs_review'] is True
    assert summary['flagged'] == 1


def test_media_type_from_ref_extension():
    assert _image_media_type('page1_img1.png') == 'image/png'
    assert _image_media_type('page1_img1.jpeg') == 'image/jpeg'
    assert _image_media_type('page1_img1.jpg') == 'image/jpeg'
    assert _image_media_type('weird') == 'image/png'  # default
