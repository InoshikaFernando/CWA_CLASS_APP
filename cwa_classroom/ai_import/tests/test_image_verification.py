"""Vision second-opinion image validator: a confident mismatch flags needs_review,
a match stays quiet, and the pass is a safe no-op when unconfigured, when there is
nothing to check, or when the API errors.

Zero-token: the OpenAI client is mocked; no API call is made.
"""
from unittest.mock import MagicMock

from ai_import import verification
from ai_import.verification import (
    _count_verifiable, _image_media_type, _image_ref_page, _image_verifiable,
    flag_cross_page_images, flag_missing_figures,
    flag_photo_images_on_diagrams, verify_counts, verify_images,
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


def _seq_client(result_lists):
    """A client whose successive completion calls return successive result lists.

    Lets a test drive the consensus sampler with a different per-call verdict —
    e.g. [[{18}], [{18}], [{24}]] for three samples that split 2-to-1."""
    import json

    def _resp(results):
        tool_call = MagicMock()
        tool_call.function.arguments = json.dumps({'results': results})
        message = MagicMock(tool_calls=[tool_call])
        resp = MagicMock(choices=[MagicMock(message=message)])
        resp.usage = MagicMock(prompt_tokens=20, completion_tokens=8)
        return resp

    client = MagicMock()
    client.chat.completions.create.side_effect = [_resp(r) for r in result_lists]
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


def test_confident_mismatch_detaches_the_wrong_image():
    # The reported bug: a multiplication card left showing on a "how many diamonds
    # on this playing card?" question. A confident mismatch must REMOVE the image,
    # not merely badge it (default behaviour).
    q = _q(text='How many diamonds are on this playing card?')
    client = _fake_client([
        {'index': 0, 'matches': False, 'confident': True,
         'reason': 'a multiplication problem, not a playing card'},
    ])

    summary = verify_images([q], IMAGES, client=client, force=True)

    assert 'image_ref' not in q          # wrong image removed
    assert 'image_page' not in q
    assert q['needs_review'] is True
    assert 'removed' in q['review_reason']
    assert summary['detached'] == 1
    assert summary['flagged'] == 1


def test_autodetach_off_flags_but_keeps_image(monkeypatch):
    monkeypatch.setenv('AI_IMPORT_VERIFY_IMAGES_AUTODETACH', '0')
    q = _q()
    client = _fake_client([
        {'index': 0, 'matches': False, 'confident': True, 'reason': 'wrong figure'},
    ])

    summary = verify_images([q], IMAGES, client=client, force=True)

    assert q['image_ref'] == 'page7_img1.jpeg'   # left in place
    assert q['needs_review'] is True
    assert summary['flagged'] == 1
    assert summary['detached'] == 0


def test_incomplete_crop_is_flagged_for_recrop_not_detached():
    # Right figure, but a label is cut off → flag to re-crop, keep the image.
    q = _q(text='Find x in this triangle.')
    client = _fake_client([{
        'index': 0, 'matches': True, 'confident': True,
        'complete': False, 'clean': True, 'reason': 'the 23.9 km label is cut off',
    }])

    summary = verify_images([q], IMAGES, client=client, force=True)

    assert q['image_ref'] == 'page7_img1.jpeg'          # NOT detached — figure is right
    assert q['needs_review'] is True
    assert 're-crop' in q['review_reason']
    assert 'cuts off' in q['review_reason']
    assert '23.9 km' in q['review_reason']
    assert summary['recrop'] == 1
    assert summary['detached'] == 0
    assert summary['flagged'] == 1


def test_crop_with_extra_content_is_flagged():
    q = _q()
    client = _fake_client([{
        'index': 0, 'matches': True, 'confident': True,
        'complete': True, 'clean': False, 'reason': "the next question's text is included",
    }])

    summary = verify_images([q], IMAGES, client=client, force=True)

    assert q['needs_review'] is True
    assert 'extra content' in q['review_reason']
    assert summary['recrop'] == 1


def test_complete_and_clean_crop_stays_quiet():
    q = _q()
    client = _fake_client([{
        'index': 0, 'matches': True, 'confident': True,
        'complete': True, 'clean': True,
    }])

    summary = verify_images([q], IMAGES, client=client, force=True)

    assert 'needs_review' not in q
    assert summary['flagged'] == 0
    assert summary['recrop'] == 0


def test_crop_quality_check_can_be_disabled(monkeypatch):
    monkeypatch.setenv('AI_IMPORT_VERIFY_CROP_QUALITY', '0')
    q = _q()
    client = _fake_client([{
        'index': 0, 'matches': True, 'confident': True,
        'complete': False, 'clean': False, 'reason': 'clipped',
    }])

    summary = verify_images([q], IMAGES, client=client, force=True)

    assert 'needs_review' not in q          # sub-check off → not flagged
    assert summary['recrop'] == 0


def test_unconfident_crop_quality_is_ignored():
    q = _q()
    client = _fake_client([{
        'index': 0, 'matches': True, 'confident': False,
        'complete': False, 'clean': False, 'reason': 'maybe clipped',
    }])

    summary = verify_images([q], IMAGES, client=client, force=True)

    assert 'needs_review' not in q
    assert summary['recrop'] == 0


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


# ---------------------------------------------------------------------------
# Missing-figure guard (no API call)

def _text_q(text, **extra):
    """A question with NO attached image (image_ref/image_page absent)."""
    return {'question_text': text, 'question_type': 'short_answer', **extra}


def test_missing_figure_is_flagged():
    # The reported case: a perimeter question about a shape it can't show.
    q = _text_q('This shape has been made using identical squares. One square '
                'has a perimeter of 20cm. What is the perimeter of the whole shape?')

    flagged = flag_missing_figures([q])

    assert flagged == 1
    assert q['needs_review'] is True
    assert q['review_reason'].startswith('Image check:')
    assert 'no image' in q['review_reason']


def test_various_figure_references_are_flagged():
    for text in [
        'What is the area of the diagram below?',
        'Read the value shown on the number line.',
        'Use the graph to answer the question.',
        'Plot the points on the grid.',
        'What time is shown on the clock face?',
    ]:
        q = _text_q(text)
        assert flag_missing_figures([q]) == 1, text


def test_text_only_question_is_not_flagged():
    # A rectangle fully described in words points at no picture.
    q = _text_q('A rectangle has a perimeter of 20cm and a length of 6cm. '
                'What is its width?')
    assert flag_missing_figures([q]) == 0
    assert 'needs_review' not in q


def test_question_with_attached_figure_is_not_flagged():
    # "this shape" wording but a crop was attached → nothing missing.
    q = _text_q('What is the perimeter of this shape?', image_ref='page3_figure2.png')
    assert flag_missing_figures([q]) == 0
    assert 'needs_review' not in q


def test_scaffolding_visual_types_are_exempt():
    # "grid" here is the column-arithmetic layout, transcribed into fields.
    q = _text_q('Work out the answer using the grid.', question_type='column_operation')
    assert flag_missing_figures([q]) == 0
    assert 'needs_review' not in q


def test_group_shared_and_already_flagged_are_skipped():
    shared = _text_q('What is the area of this shape?', shares_image_with_previous=True)
    already = _text_q('Name the diagram shown.', needs_review=True,
                      review_reason='pre-existing')

    flagged = flag_missing_figures([shared, already])

    assert flagged == 0
    assert 'needs_review' not in shared            # image carried from previous
    assert already['review_reason'] == 'pre-existing'  # untouched


# ---------------------------------------------------------------------------
# Photo-on-diagram guard (no API call)

def test_photo_on_perimeter_question_is_flagged():
    # The reported case: a supermarket illustration attached to a perimeter question.
    q = _q('Find the perimeter of this shape made of squares (each 1cm by 1cm).',
           ref='page6_img2.jpeg')

    flagged = flag_photo_images_on_diagrams([q], {'page6_img2.jpeg'})

    assert flagged == 1
    assert q['needs_review'] is True
    assert 'photo' in q['review_reason']
    assert q['review_reason'].startswith('Image check:')


def test_non_photo_image_on_diagram_is_not_flagged():
    # Same question, but its image was NOT flagged photo_like → left alone.
    q = _q('Find the perimeter of this shape.', ref='page6_img2.jpeg')
    assert flag_photo_images_on_diagrams([q], set()) == 0
    assert 'needs_review' not in q


def test_photo_on_non_diagram_question_is_not_flagged():
    # A genuine picture-interpretation question keeps its photo.
    q = _q('What item is shown in the photograph?', ref='page6_img2.jpeg')
    assert flag_photo_images_on_diagrams([q], {'page6_img2.jpeg'}) == 0
    assert 'needs_review' not in q


def test_photo_guard_skips_already_flagged():
    q = _q('Find the area of this triangle.', ref='page6_img2.jpeg',
           needs_review=True, review_reason='pre-existing')
    assert flag_photo_images_on_diagrams([q], {'page6_img2.jpeg'}) == 0
    assert q['review_reason'] == 'pre-existing'


# ---------------------------------------------------------------------------
# Vision count re-check ("count the squares")

def _count_q(text='Find the area of this shape by counting the squares.',
             answer='24cm²', ref='page6_figure1.png', **extra):
    return {'question_text': text, 'question_type': 'short_answer',
            'image_ref': ref,
            'answers': [{'text': answer, 'is_correct': True}], **extra}


COUNT_IMAGES = {'page6_figure1.png': 'GRIDGRID'}


def test_count_verifiable_detects_counting_questions():
    assert _count_verifiable(_count_q())                                   # "counting the squares"
    assert _count_verifiable(_count_q('Perimeter of this shape made of squares?'))
    assert not _count_verifiable(_count_q('What is 6 x 4?', ref=None))     # no figure
    assert not _count_verifiable(_count_q('Find the angle shown.'))        # not a square count


def test_confident_disagreement_auto_corrects_by_default():
    q = _count_q(answer='24cm²')                       # imported says 24
    client = _fake_client([{'index': 0, 'answer': '18', 'confident': True}])

    summary = verify_counts([q], COUNT_IMAGES, client=client, force=True)

    # Answer key rewritten to the verifier's count, unit preserved; audited; not
    # routed to a human.
    assert q['answers'][0]['text'] == '18cm²'
    assert q['answer_auto_corrected'] == {
        'from': '24cm²', 'to': '18cm²', 'source': 'count-recheck'}
    assert 'needs_review' not in q
    assert summary['corrected'] == 1 and summary['flagged'] == 0
    assert summary['corrections'][0]['from'] == '24cm²'
    assert summary['corrections'][0]['to'] == '18cm²'


def test_confident_disagreement_flags_when_autocorrect_disabled(monkeypatch):
    monkeypatch.setenv('AI_IMPORT_VERIFY_COUNTS_AUTOCORRECT', '0')
    q = _count_q(answer='24cm²')
    client = _fake_client([{'index': 0, 'answer': '18', 'confident': True}])

    summary = verify_counts([q], COUNT_IMAGES, client=client, force=True)

    # Flag-only fallback: answer untouched, routed to a human.
    assert q['answers'][0]['text'] == '24cm²'
    assert 'answer_auto_corrected' not in q
    assert q['needs_review'] is True
    assert '18' in q['review_reason'] and '24' in q['review_reason']
    assert summary['flagged'] == 1 and summary['corrected'] == 0


def test_auto_correct_rewrites_all_correct_forms():
    # Both "24cm²" and "24" are ticked correct; both get the new count.
    q = _count_q(answer='24cm²')
    q['answers'].append({'text': '24', 'is_correct': True})
    q['numeric_answer'] = 24
    client = _fake_client([{'index': 0, 'answer': '18', 'confident': True}])

    verify_counts([q], COUNT_IMAGES, client=client, force=True)

    assert q['answers'][0]['text'] == '18cm²'
    assert q['answers'][1]['text'] == '18'
    assert q['numeric_answer'] == 18


def test_count_agreement_stays_quiet():
    q = _count_q(answer='24cm²')
    client = _fake_client([{'index': 0, 'answer': '24', 'confident': True}])

    summary = verify_counts([q], COUNT_IMAGES, client=client, force=True)

    assert 'needs_review' not in q
    assert summary['flagged'] == 0


def test_count_unconfident_does_not_flag():
    q = _count_q(answer='24cm²')
    client = _fake_client([{'index': 0, 'answer': '', 'confident': False}])

    summary = verify_counts([q], COUNT_IMAGES, client=client, force=True)

    assert 'needs_review' not in q
    assert summary['flagged'] == 0


def test_count_disabled_without_key(monkeypatch):
    monkeypatch.setattr(verification.settings, 'OPENAI_API_KEY', '', raising=False)
    q = _count_q()
    assert verify_counts([q], COUNT_IMAGES, client=MagicMock()) is None
    assert 'needs_review' not in q


def test_count_non_counting_questions_are_skipped():
    # A plain short-answer question with a figure but no square-count wording.
    q = _q('What is the angle?', ref='page6_img1.jpeg')
    client = MagicMock()
    assert verify_counts([q], {'page6_img1.jpeg': 'X'}, client=client,
                         force=True) is None
    client.chat.completions.create.assert_not_called()


# --- Consensus (multiple samples) ---

def test_consensus_majority_auto_corrects(monkeypatch):
    monkeypatch.setenv('AI_IMPORT_VERIFY_COUNT_SAMPLES', '3')
    q = _count_q(answer='24cm²')
    # Three independent recounts split 2-to-1 on 18 → majority wins, corrects to 18.
    client = _seq_client([
        [{'index': 0, 'answer': '18', 'confident': True}],
        [{'index': 0, 'answer': '18', 'confident': True}],
        [{'index': 0, 'answer': '24', 'confident': True}],
    ])

    summary = verify_counts([q], COUNT_IMAGES, client=client, force=True)

    assert q['answers'][0]['text'] == '18cm²'
    assert summary['corrected'] == 1
    assert summary['corrections'][0]['agreement'] == '2/3'


def test_consensus_split_routes_to_review(monkeypatch):
    monkeypatch.setenv('AI_IMPORT_VERIFY_COUNT_SAMPLES', '3')
    q = _count_q(answer='24cm²')
    # All three disagree with each other → no majority → uncertain → flag, no rewrite.
    client = _seq_client([
        [{'index': 0, 'answer': '18', 'confident': True}],
        [{'index': 0, 'answer': '20', 'confident': True}],
        [{'index': 0, 'answer': '30', 'confident': True}],
    ])

    summary = verify_counts([q], COUNT_IMAGES, client=client, force=True)

    assert q['answers'][0]['text'] == '24cm²'          # untouched
    assert 'answer_auto_corrected' not in q
    assert q['needs_review'] is True
    assert 'could not agree' in q['review_reason']
    assert summary['corrected'] == 0 and summary['flagged'] == 1


def test_consensus_majority_agrees_with_import_stays_quiet(monkeypatch):
    monkeypatch.setenv('AI_IMPORT_VERIFY_COUNT_SAMPLES', '3')
    q = _count_q(answer='24cm²')
    client = _seq_client([
        [{'index': 0, 'answer': '24', 'confident': True}],
        [{'index': 0, 'answer': '24', 'confident': True}],
        [{'index': 0, 'answer': '18', 'confident': True}],
    ])

    summary = verify_counts([q], COUNT_IMAGES, client=client, force=True)

    assert q['answers'][0]['text'] == '24cm²'
    assert 'needs_review' not in q
    assert summary['corrected'] == 0 and summary['flagged'] == 0


# ---------------------------------------------------------------------------
# Deterministic page-locality guard (no API call)

def test_image_ref_page_parses_both_conventions():
    assert _image_ref_page('page5_img2.jpeg') == 5          # embedded raster
    assert _image_ref_page('page12_figure3.png') == 12      # cropped figure
    assert _image_ref_page('missing.png') is None           # no page encoded
    assert _image_ref_page(None) is None


def test_cross_page_image_is_flagged():
    # The real bug: a page-1 title-page engraving attached to a page-5 question.
    q = _q(ref='page1_img1.jpeg', source_page=5)

    flagged = flag_cross_page_images([q])

    assert flagged == 1
    assert q['needs_review'] is True
    assert 'page 1' in q['review_reason'] and 'page 5' in q['review_reason']
    assert q['review_reason'].startswith('Image check:')


def test_cross_page_image_is_detached_by_default():
    # A far cross-page image is REMOVED, not just badged, so the wrong picture
    # never shows in preview.
    q = _q(ref='page1_img1.jpeg', source_page=5)

    flag_cross_page_images([q])

    assert 'image_ref' not in q
    assert q['needs_review'] is True
    assert 'removed' in q['review_reason']


def test_cross_page_autodrop_off_keeps_image(monkeypatch):
    monkeypatch.setenv('AI_IMPORT_DROP_CROSS_PAGE_IMAGES', '0')
    q = _q(ref='page1_img1.jpeg', source_page=5)

    assert flag_cross_page_images([q]) == 1
    assert q['image_ref'] == 'page1_img1.jpeg'   # left in place
    assert q['needs_review'] is True


def test_far_apart_pages_are_flagged():
    # The exact worry: image on page 1, question on page 10.
    q = _q(ref='page1_img1.jpeg', source_page=10)
    assert flag_cross_page_images([q]) == 1
    assert q['needs_review'] is True
    assert 'page 1' in q['review_reason'] and 'page 10' in q['review_reason']


def test_source_page_as_string_is_handled():
    # The model may return source_page as a string; it must still compare numerically.
    q = _q(ref='page1_img1.jpeg', source_page='10')
    assert flag_cross_page_images([q]) == 1
    assert q['needs_review'] is True


def test_same_page_image_is_not_flagged():
    q = _q(ref='page5_img1.jpeg', source_page=5)
    assert flag_cross_page_images([q]) == 0
    assert 'needs_review' not in q


def test_adjacent_page_allowed_by_default():
    # A figure at a page break shared onto the next page is legitimate (gap 1).
    q = _q(ref='page4_figure2.png', source_page=5)
    assert flag_cross_page_images([q]) == 0
    assert 'needs_review' not in q


def test_gap_of_two_is_flagged():
    q = _q(ref='page3_img1.jpeg', source_page=5)
    assert flag_cross_page_images([q]) == 1
    assert q['needs_review'] is True


def test_max_gap_is_env_tunable(monkeypatch):
    monkeypatch.setenv('AI_IMPORT_MAX_IMAGE_PAGE_GAP', '0')
    # With no slack even an adjacent page counts as a mismatch.
    q = _q(ref='page4_img1.jpeg', source_page=5)
    assert flag_cross_page_images([q]) == 1


def test_guard_skips_already_flagged_and_pageless(monkeypatch):
    already = _q(ref='page1_img1.jpeg', source_page=5, needs_review=True,
                 review_reason='pre-existing')
    no_source = _q(ref='page1_img1.jpeg')                 # source_page absent
    drawn_ref = _q(ref='sketch.png', source_page=5)       # no page encoded in ref

    flagged = flag_cross_page_images([already, no_source, drawn_ref])

    assert flagged == 0
    assert already['review_reason'] == 'pre-existing'     # untouched
    assert 'needs_review' not in no_source
    assert 'needs_review' not in drawn_ref
