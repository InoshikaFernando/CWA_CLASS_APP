"""The importer derives angle-relationship answers from perceived geometry.

``_apply_computed_angle_answer`` runs in ``classify_questions`` post-processing:
for "label the marked pair of angles" questions the model supplies only the
figure geometry (``angle_relationship_spec``) and the app computes which option
is correct — so a mis-named guess can't be saved. These tests exercise that hook
directly (zero-token, no API) plus the prompt/schema contract.
"""
from ai_import.services import (
    CLASSIFICATION_TOOL,
    _apply_computed_angle_answer,
    _build_classification_prompt,
)

TOP = {'p1': [10, 20], 'p2': [90, 20]}
BOTTOM = {'p1': [10, 60], 'p2': [90, 60]}
TRANS = {'p1': [45, 10], 'p2': [70, 90]}

# The four standard options a worksheet offers.
OPTIONS = ['corresponding', 'alternate interior', 'alternate exterior', 'consecutive interior']


def _question(y_pos, x_pos, spec=True, correct_guess='corresponding'):
    """A multiple_choice angle question as the model would emit it."""
    q = {
        'question_text': 'Label the marked pair of angles.',
        'question_type': 'multiple_choice',
        'answers': [{'text': o, 'is_correct': (o == correct_guess)} for o in OPTIONS],
    }
    if spec:
        q['angle_relationship_spec'] = {
            'lines': [TOP, BOTTOM],
            'transversal': TRANS,
            'angles': [
                {'label': 'y', 'pos': list(y_pos)},
                {'label': 'x', 'pos': list(x_pos)},
            ],
        }
    return q


def _correct_texts(q):
    return {a['text'] for a in q['answers'] if a['is_correct']}


def test_overrides_wrong_guess_with_computed_answer():
    # Model guessed "corresponding"; geometry says alternate exterior (the Q5 case).
    q = _question(y_pos=(55, 14), x_pos=(52, 68), correct_guess='corresponding')
    _apply_computed_angle_answer(q)
    assert _correct_texts(q) == {'alternate exterior'}
    assert not q.get('needs_review')


def test_rewrites_explanation_to_match():
    q = _question(y_pos=(55, 28), x_pos=(52, 52))  # alternate interior
    _apply_computed_angle_answer(q)
    assert _correct_texts(q) == {'alternate interior'}
    assert 'opposite sides' in q['explanation']


def test_multi_transversal_flag_from_model_is_preserved():
    # Model left the spec off and flagged it; hook must not clobber that.
    q = _question(y_pos=(0, 0), x_pos=(0, 0), spec=False)
    q['needs_review'] = True
    q['review_reason'] = 'two transversals'
    _apply_computed_angle_answer(q)
    assert q['needs_review'] is True
    assert q['review_reason'] == 'two transversals'


def test_ambiguous_geometry_sets_needs_review():
    q = _question(y_pos=(55, 20), x_pos=(52, 52))  # y sits on the top line
    _apply_computed_angle_answer(q)
    assert q['needs_review'] is True


def test_missing_option_is_added_and_flagged():
    q = _question(y_pos=(55, 14), x_pos=(52, 68))  # alternate exterior
    q['answers'] = [{'text': 'corresponding', 'is_correct': True}]  # option not present
    _apply_computed_angle_answer(q)
    assert 'alternate exterior' in _correct_texts(q)
    assert q['needs_review'] is True


def test_no_spec_is_noop():
    q = _question(y_pos=(0, 0), x_pos=(0, 0), spec=False, correct_guess='corresponding')
    _apply_computed_angle_answer(q)
    assert _correct_texts(q) == {'corresponding'}
    assert 'needs_review' not in q


def test_malformed_spec_flags_rather_than_raises():
    q = _question(y_pos=(0, 0), x_pos=(0, 0))
    q['angle_relationship_spec'] = {'lines': [TOP], 'transversal': TRANS, 'angles': []}
    _apply_computed_angle_answer(q)
    assert q['needs_review'] is True


def test_schema_advertises_angle_spec_and_review_fields():
    props = CLASSIFICATION_TOOL['input_schema']['properties']['questions']['items']['properties']
    assert 'angle_relationship_spec' in props
    assert 'needs_review' in props
    assert 'review_reason' in props


def test_prompt_tells_model_not_to_name_the_pair():
    p = _build_classification_prompt([], [])
    assert 'DO NOT NAME THE PAIR YOURSELF' in p
    assert 'angle_relationship_spec' in p
