"""The paper's own answer key is parsed and applied to the extracted questions.

An exam paper's key ("44  C  6:45pm to 7pm is 15 minutes…") is better answer
data than the AI's own attempt, so where the two disagree the key wins — and
says so, because a disagreement means one of them misread the page.
"""
from worksheets.answer_key import apply_answer_key, parse_answer_key


# The two layouts real papers use. Stacked is what PyMuPDF returns for the
# scholarship paper this was built from.
STACKED_KEY = """MATHEMATICS
1
B
3 hearts and 4 triangles.
2
B
smaller < bigger
1km = 1 000m
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
Four in the bottom and three in the second layer.
"""

INLINE_KEY = """44 C 6:45pm to 7pm is 15 minutes; 7pm to 7:12pm is 12 minutes.
Total minutes = 15 + 12 = 27 minutes.
45 A 3/4 - 1/2 = 1/4
46 D 1m = 1 000mm
"""


def _mcq(number, correct_index, options=4, **extra):
    question = {
        'source_number': number,
        'question_type': 'multiple_choice',
        'answers': [{'text': f'option {chr(65 + i)}', 'is_correct': i == correct_index}
                    for i in range(options)],
    }
    question.update(extra)
    return question


# --- parsing -----------------------------------------------------------------

def test_parses_a_stacked_key_with_its_working():
    rows = parse_answer_key(STACKED_KEY)

    assert set(rows) == {1, 2, 3, 4, 5, 6}
    assert rows[1] == {'letter': 'B', 'working': '3 hearts and 4 triangles.'}
    assert rows[2]['letter'] == 'B'
    assert rows[2]['working'] == 'smaller < bigger 1km = 1 000m'   # multi-line working


def test_parses_an_inline_key():
    rows = parse_answer_key(INLINE_KEY)

    assert set(rows) == {44, 45, 46}
    assert rows[44]['letter'] == 'C'
    assert rows[44]['working'].startswith('6:45pm to 7pm is 15 minutes')
    assert 'Total minutes = 15 + 12 = 27 minutes.' in rows[44]['working']


def test_a_page_with_no_key_rows_parses_to_nothing():
    assert parse_answer_key('Question 12\nWhat is 2 + 2?\nA. 3\nB. 4\n') == {}
    assert parse_answer_key('') == {}


# --- applying ----------------------------------------------------------------

def _key_page(text, page_num=21):
    return {'page_num': page_num, 'text': text}


def test_the_key_confirms_an_answer_the_ai_already_had_right():
    questions = [_mcq(1, correct_index=1)]          # AI said B, key says B

    summary = apply_answer_key(questions, [_key_page(STACKED_KEY)])

    assert summary['agreed'] == 1
    assert summary['corrected'] == 0
    assert [a['is_correct'] for a in questions[0]['answers']] == [False, True, False, False]
    assert not questions[0].get('needs_review')


def test_the_key_overrides_the_ai_and_flags_the_disagreement():
    questions = [_mcq(3, correct_index=0)]          # AI said A, key says C

    summary = apply_answer_key(questions, [_key_page(STACKED_KEY)])

    assert summary['corrected'] == 1
    assert [a['is_correct'] for a in questions[0]['answers']] == [False, False, True, False]
    assert questions[0]['needs_review'] is True
    assert 'answer key says C' in questions[0]['review_reason']
    assert 'option A' in questions[0]['review_reason']
    assert questions[0]['answer_source'] == 'answer_key'


def test_the_keys_working_fills_an_empty_explanation():
    questions = [_mcq(1, correct_index=1)]

    apply_answer_key(questions, [_key_page(STACKED_KEY)])

    assert questions[0]['explanation'] == '3 hearts and 4 triangles.'


def test_an_explanation_the_ai_wrote_is_kept():
    questions = [_mcq(1, correct_index=1, explanation='The AI said this.')]

    apply_answer_key(questions, [_key_page(STACKED_KEY)])

    assert questions[0]['explanation'] == 'The AI said this.'


def test_a_written_answer_question_takes_the_working_but_keeps_its_answer():
    questions = [{
        'source_number': 1, 'question_type': 'short_answer',
        'answers': [{'text': '7', 'is_correct': True}],
    }]

    summary = apply_answer_key(questions, [_key_page(STACKED_KEY)])

    assert summary['explanation_only'] == 1
    assert summary['applied'] == 0
    assert questions[0]['answers'][0]['is_correct'] is True     # untouched
    assert questions[0]['explanation'] == '3 hearts and 4 triangles.'


def test_a_letter_beyond_the_options_is_not_forced_on():
    """Key says D but the AI only found two options — don't invent one."""
    questions = [_mcq(46, correct_index=0, options=2)]

    summary = apply_answer_key(questions, [_key_page(INLINE_KEY)])

    assert summary['applied'] == 0
    assert summary['explanation_only'] == 1
    assert [a['is_correct'] for a in questions[0]['answers']] == [True, False]


def test_rows_and_questions_that_do_not_match_are_reported():
    questions = [_mcq(1, correct_index=1), _mcq(None, correct_index=0)]

    summary = apply_answer_key(questions, [_key_page(STACKED_KEY)])

    assert summary['rows_found'] == 6
    assert summary['unmatched_rows'] == [2, 3, 4, 5, 6]   # key rows with no question
    assert summary['questions_without_number'] == 1
    assert summary['pages'] == [21]


def test_several_key_pages_are_merged():
    questions = [_mcq(1, correct_index=1), _mcq(44, correct_index=2)]

    summary = apply_answer_key(questions, [
        _key_page(STACKED_KEY, 21), _key_page(INLINE_KEY, 22),
    ])

    assert summary['pages'] == [21, 22]
    assert summary['agreed'] == 2
    assert summary['unmatched_rows'] == [2, 3, 4, 5, 6, 45, 46]


def test_no_key_rows_means_nothing_applied():
    questions = [_mcq(1, correct_index=0)]

    summary = apply_answer_key(questions, [_key_page('Just some prose.')])

    assert summary['rows_found'] == 0
    assert [a['is_correct'] for a in questions[0]['answers']] == [True, False, False, False]


# --- wired into the pipeline -------------------------------------------------

def test_classification_applies_the_key_from_the_pages_it_skipped():
    """The key pages are set aside from classification, then used on the result."""
    from unittest.mock import patch

    from worksheets import services

    pages = [
        {'page_num': 1, 'text': 'Question 1\nWhat is 2 + 2?\nA. 3\nB. 4\n', 'screenshot': 'x'},
        {'page_num': 2, 'text': STACKED_KEY, 'screenshot': 'x'},
    ]

    def fake_chunk(client, system, chunk, total, shape_naming=False):
        assert [p['page_num'] for p in chunk] == [1]      # the key never goes out
        return {'questions': [_mcq(1, correct_index=0)],  # AI says A, key says B
                'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}

    with patch.object(services, '_get_anthropic_client'), \
         patch.object(services, '_classify_page_chunk', side_effect=fake_chunk):
        result = services.classify_worksheet_questions(
            {'pages': pages, 'page_count': 2}, [], [])

    assert result['answer_key']['corrected'] == 1
    assert result['answer_key']['pages'] == [2]
    question = result['questions'][0]
    assert [a['is_correct'] for a in question['answers']] == [False, True, False, False]
    assert question['needs_review'] is True


def test_a_paper_with_no_answer_key_reports_none():
    from unittest.mock import patch

    from worksheets import services

    pages = [{'page_num': 1, 'text': 'Question 1\nWhat is 2 + 2?\n', 'screenshot': 'x'}]

    with patch.object(services, '_get_anthropic_client'), \
         patch.object(services, '_classify_page_chunk',
                      return_value={'questions': [_mcq(1, correct_index=0)],
                                    'usage': {'total_tokens': 2}}):
        result = services.classify_worksheet_questions(
            {'pages': pages, 'page_count': 1}, [], [])

    assert 'answer_key' not in result


# --- the question's number on the paper --------------------------------------

def test_a_label_the_model_copied_supplies_the_missing_source_number():
    """source_number is what the key matches on; recover it before it's stripped."""
    from worksheets.services import _label_question_number

    assert _label_question_number('Question 46 If a man was 1.94m tall…') == 46
    assert _label_question_number('46. What is 2 + 2?') == 46
    assert _label_question_number('Q7) Simplify') == 7
    assert _label_question_number('What is 2 + 2?') is None
    assert _label_question_number('') is None
