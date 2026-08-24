"""CPP-389 — building and describing a question that has not been imported yet.

``maths.draft_preview`` is what lets a teacher see a PDF-extracted question the
way a student will, and be told how it is going to be marked. These tests pin
the two things that make it worth having: it builds the question the importer
would build, and it names the traps out loud — the comma silently cut across
two gaps, the measurement with no tolerance, the parabola matched as text.
"""
import pytest

from classroom.models import Level
from maths.draft_preview import (
    DraftNotImportable,
    build_preview_question,
    grading_notes,
    preview_question,
)
from maths.models import Answer, Question

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _level():
    return Level.objects.create(level_number=5, display_name='Year 5')


def notes_for(draft, *, promote_blanks=True):
    """Build the draft and describe it, rolled back like the real endpoint."""
    captured = {}
    with preview_question(draft, promote_blanks=promote_blanks) as question:
        captured['question'] = question
        captured['type'] = question.question_type
        captured['notes'] = grading_notes(
            question, draft, promote_blanks=promote_blanks)
        captured['text'] = ' '.join(n['text'] for n in captured['notes'])
        captured['warnings'] = ' '.join(
            n['text'] for n in captured['notes'] if n['level'] == 'warn')
    return captured


# ---------------------------------------------------------------------------
# Nothing survives
# ---------------------------------------------------------------------------
def test_preview_rolls_back_the_question_it_built():
    before = Question.objects.count()
    with preview_question(
        {'question_text': 'What is 2 + 2?', 'question_type': 'short_answer',
         'answers': [{'text': '4', 'is_correct': True}]},
        promote_blanks=False,
    ) as question:
        assert Question.objects.filter(pk=question.pk).exists()
        assert question.answers.count() == 1
    assert Question.objects.count() == before
    assert not Answer.objects.filter(answer_text='4').exists()


def test_an_error_inside_the_preview_still_rolls_back():
    before = Question.objects.count()
    with pytest.raises(RuntimeError):
        with preview_question(
            {'question_text': 'Q', 'question_type': 'short_answer',
             'answers': [{'text': 'a', 'is_correct': True}]},
            promote_blanks=False,
        ):
            raise RuntimeError('render blew up')
    assert Question.objects.count() == before


def test_the_draft_is_built_fresh_rather_than_deduped_onto_an_existing_question():
    """The importers get_or_create; a preview must not.

    Otherwise editing the answers on a question whose text already exists in the
    bank would preview the STORED answers — the teacher would be shown somebody
    else's question and told it was theirs.
    """
    level = Level.objects.get(level_number=5)
    stored = Question.objects.create(
        question_text='What is 2 + 2?', level=level, question_type='short_answer')
    Answer.objects.create(question=stored, answer_text='five', is_correct=True)

    with preview_question(
        {'question_text': 'What is 2 + 2?', 'question_type': 'short_answer',
         'year_level': 5, 'answers': [{'text': '4', 'is_correct': True}]},
        promote_blanks=False,
    ) as question:
        assert question.pk != stored.pk
        assert [a.answer_text for a in question.answers.all()] == ['4']


# ---------------------------------------------------------------------------
# Questions the import would silently drop
# ---------------------------------------------------------------------------
def test_a_choice_question_with_no_options_says_it_would_be_skipped():
    with pytest.raises(DraftNotImportable, match='skipped at import'):
        build_preview_question(
            {'question_text': 'Pick one', 'question_type': 'multiple_choice',
             'answers': []},
            promote_blanks=False,
        )


def test_a_broken_plane_spec_says_it_would_be_skipped():
    with pytest.raises(DraftNotImportable, match='would not be imported'):
        build_preview_question(
            {'question_text': 'Plot (3, -2)', 'question_type': 'plot_points',
             'plane_spec': {'bounds': 'nonsense'}},
            promote_blanks=False,
        )


def test_a_long_division_with_no_divisor_says_it_would_be_skipped():
    with pytest.raises(DraftNotImportable, match='skipped at import'):
        build_preview_question(
            {'question_text': '611 ÷ ?', 'question_type': 'long_division',
             'dividend': 611},
            promote_blanks=False,
        )


# ---------------------------------------------------------------------------
# Fill in the blanks — the comma that shipped broken
# ---------------------------------------------------------------------------
def test_a_gapped_sentence_previews_as_the_fill_blank_it_becomes():
    result = notes_for({
        'question_text': 'Out of 100c, 20c is ______ hundredths.',
        'question_type': 'short_answer',
        'answers': [{'text': 'twenty', 'is_correct': True}],
    })
    assert result['type'] == Question.FILL_BLANK
    assert 'Gap 1 accepts: twenty' in result['text']


def test_one_answer_split_across_gaps_at_its_comma_is_warned():
    """The bug this whole feature was asked for.

    A single answer row that happens to contain a comma is cut into one value
    per gap by ``derive_blank_spec``. Nothing about the review form shows that,
    so it reached students; the preview now says it in words.
    """
    result = notes_for({
        'question_text': '20c is ______ hundredths, or ______ of a dollar.',
        'question_type': 'short_answer',
        'answers': [{'text': 'twenty, 0.20', 'is_correct': True}],
    })
    assert result['type'] == Question.FILL_BLANK
    assert 'split across 2 gaps' in result['warnings']
    assert 'Gap 1 accepts: twenty' in result['text']
    assert 'Gap 2 accepts: 0.20' in result['text']


def test_gaps_that_cannot_be_filled_from_the_answers_are_warned():
    result = notes_for({
        'question_text': 'The ______ of a ______ is ______.',
        'question_type': 'short_answer',
        'answers': [{'text': 'area', 'is_correct': True}],
    })
    assert result['type'] != Question.FILL_BLANK
    assert 'one box for the whole sentence' in result['warnings']


def test_a_choice_question_whose_stem_has_gaps_is_not_warned_about_them():
    """Only a typed answer can move into the gaps of a sentence.

    A multiple choice whose stem happens to read "20c is ___ of a dollar" is
    still a question you pick an option for, so warning about gaps that were
    never going to become boxes would be noise.
    """
    result = notes_for({
        'question_text': '20c is ______ of a dollar.',
        'question_type': 'multiple_choice',
        'answers': [{'text': 'twenty hundredths', 'is_correct': True},
                    {'text': 'two hundredths', 'is_correct': False}],
    })
    assert 'gaps' not in result['warnings']
    assert result['warnings'] == ''


def test_a_flow_that_does_not_promote_gaps_says_so():
    result = notes_for(
        {
            'question_text': '20c is ______ of a dollar.',
            'question_type': 'short_answer',
            'answers': [{'text': 'twenty hundredths', 'is_correct': True}],
        },
        promote_blanks=False,
    )
    assert result['type'] == Question.SHORT_ANSWER
    assert 'keeps it as ONE answer box' in result['warnings']


# ---------------------------------------------------------------------------
# Measurement
# ---------------------------------------------------------------------------
def test_a_measurement_with_no_tolerance_is_warned():
    result = notes_for({
        'question_text': 'Measure angle a.', 'question_type': 'measure',
        'numeric_answer': '135', 'answer_unit': '°',
    })
    assert 'no tolerance' in result['warnings']
    assert 'Only exactly 135°' in result['warnings']


def test_a_measurement_with_a_tolerance_states_the_range():
    result = notes_for({
        'question_text': 'Measure angle a.', 'question_type': 'measure',
        'numeric_answer': '135', 'answer_tolerance': '2', 'answer_unit': '°',
    })
    assert result['warnings'] == ''
    assert 'give or take 2°' in result['text']


def test_a_measurement_with_no_value_says_it_would_be_skipped():
    with pytest.raises(DraftNotImportable, match='nothing to mark against'):
        build_preview_question(
            {'question_text': 'Measure angle a.', 'question_type': 'measure'},
            promote_blanks=False,
        )


# ---------------------------------------------------------------------------
# Typed answers
# ---------------------------------------------------------------------------
def test_a_single_accepted_wording_is_warned():
    result = notes_for({
        'question_text': 'How long is a school term?',
        'question_type': 'short_answer',
        'answers': [{'text': '10 weeks', 'is_correct': True}],
    })
    assert 'Only one wording is accepted' in result['warnings']


def test_several_accepted_wordings_are_listed_and_not_warned_about():
    result = notes_for({
        'question_text': 'How long is a school term?',
        'question_type': 'short_answer',
        'answers': [
            {'text': '10 weeks', 'is_correct': True},
            {'text': 'ten weeks', 'is_correct': True},
        ],
    })
    assert '"10 weeks" or "ten weeks"' in result['text']
    assert 'Only one wording' not in result['warnings']


def test_an_algebraic_answer_matched_as_text_is_warned():
    """The parabola case: equivalent forms are marked wrong.

    Neither importer sets ``answer_format``, so an imported algebra question is
    matched literally. A student writing the same curve in a different form is
    marked wrong, and until now nothing said so before import.
    """
    result = notes_for({
        'question_text': 'Write the equation of this parabola.',
        'question_type': 'short_answer',
        'answers': [
            {'text': 'y = (x - 2)^2 + 1', 'is_correct': True},
            {'text': 'y = x^2 - 4x + 5', 'is_correct': True},
        ],
    })
    assert 'matches text literally' in result['warnings']


def test_a_question_with_no_correct_answer_is_warned():
    result = notes_for({
        'question_text': 'What is 2 + 2?', 'question_type': 'short_answer',
        'answers': [{'text': '4', 'is_correct': False}],
    })
    assert 'every answer the student types is marked wrong' in result['warnings']


# ---------------------------------------------------------------------------
# Pick-an-option
# ---------------------------------------------------------------------------
def test_a_choice_question_with_nothing_ticked_is_warned():
    result = notes_for({
        'question_text': 'Pick one', 'question_type': 'multiple_choice',
        'answers': [{'text': 'a', 'is_correct': False},
                    {'text': 'b', 'is_correct': False}],
    })
    assert 'No option is ticked correct' in result['warnings']


def test_a_choice_question_with_two_ticked_is_warned():
    result = notes_for({
        'question_text': 'Pick one', 'question_type': 'multiple_choice',
        'answers': [{'text': 'a', 'is_correct': True},
                    {'text': 'b', 'is_correct': True}],
    })
    assert '2 options are ticked correct' in result['warnings']


# ---------------------------------------------------------------------------
# Not auto-marked at all
# ---------------------------------------------------------------------------
def test_a_teacher_graded_question_says_it_is_not_auto_marked():
    result = notes_for({
        'question_text': 'Explain your working.',
        'question_type': 'extended_answer', 'validation_type': 'human_graded',
    })
    assert 'A teacher marks this by hand' in result['text']


def test_an_ai_graded_question_with_no_rubric_is_warned():
    result = notes_for({
        'question_text': 'Explain your working.',
        'question_type': 'extended_answer', 'validation_type': 'ai_graded',
    })
    assert 'AI marks this' in result['text']
    assert 'no grading rubric' in result['warnings']


# ---------------------------------------------------------------------------
# Structured types
# ---------------------------------------------------------------------------
def test_a_table_says_it_is_marked_all_or_nothing():
    result = notes_for({
        'question_text': 'Complete the table.',
        'question_type': 'table_of_values',
        'table_spec': {
            'headers': ['Money value', 'Decimal form'],
            'rows': [[{'given': '56c'}, {'answer': '0.56'}]],
            'tolerance': 0,
        },
    })
    assert 'every cell must be right' in result['text']


def test_a_computed_answer_is_shown_rather_than_the_answer_list():
    result = notes_for({
        'question_text': '611 ÷ 47', 'question_type': 'long_division',
        'dividend': 611, 'divisor': 47,
    })
    assert '611 ÷ 47' in result['text']
