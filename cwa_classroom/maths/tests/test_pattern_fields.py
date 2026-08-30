"""The boxes a "create your own pattern" question is answered into.

One box per number the question asks for, one for the rule. The question used
to be a single empty text box, which left a child to guess the shape of what
was wanted — how many numbers, whether to write the rule in there too, and how
to keep the two apart. Half of what the grader has to untangle (is that
trailing 3 a seventh number, or the rule "subtract 3"?) existed only because
the box did not ask.

What the boxes compose is exactly the line a student would have typed, so
``grade_pattern`` reads one format whether the answer came from the widget, an
older attempt stored before it existed, or a surface that still shows a plain
box. These tests pin that: the shape of the boxes, and the line they build.
"""
import pytest

from maths.pattern_grading import (
    DEFAULT_FIELD_COUNT,
    PatternFields,
    compose_answer,
    grade_pattern,
    pattern_fields,
)

SIX_AND_A_RULE = ('Create your own tricky subtraction number pattern of six '
                  'numbers and write down the rule you used.')


class TestPatternFields:
    """How many boxes, and whether the question asks for the rule."""

    def test_a_question_that_names_a_count_gets_exactly_that_many(self):
        assert pattern_fields(SIX_AND_A_RULE) == PatternFields(
            count=6, needs_rule=True, fixed=True)

    def test_a_count_in_digits_is_read_too(self):
        fields = pattern_fields('Make up your own pattern of 4 numbers.')
        assert fields.count == 4
        assert fields.fixed is True

    def test_a_question_that_names_no_count_gets_spare_boxes(self):
        fields = pattern_fields('Make up your own addition number pattern.')
        assert fields.count == DEFAULT_FIELD_COUNT
        # Not fixed: the trailing boxes are spares, and leaving them empty is
        # a shorter pattern, not an unfinished answer.
        assert fields.fixed is False

    def test_a_count_no_real_question_would_ask_for_is_not_trusted(self):
        # parse_pattern_request already refuses to read 40 as a length; the
        # boxes must not then render 40 empty inputs at a child.
        fields = pattern_fields('Write your own pattern of 40 numbers.')
        assert fields.count == DEFAULT_FIELD_COUNT
        assert fields.fixed is False

    def test_the_rule_is_only_LABELLED_as_asked_for_when_it_is(self):
        assert pattern_fields(SIX_AND_A_RULE).needs_rule is True
        assert pattern_fields(
            'Make up your own addition pattern of five numbers.'
        ).needs_rule is False

    def test_indexes_number_the_boxes_in_order(self):
        # The order of the numbers IS the answer, so the boxes carry it.
        assert pattern_fields(SIX_AND_A_RULE).indexes == [0, 1, 2, 3, 4, 5]


class TestComposeAnswer:
    """The single line the boxes build."""

    def test_numbers_and_rule_read_as_a_student_would_write_them(self):
        assert compose_answer(['20', '18', '16', '14', '12', '10'],
                              'subtract 2') == (
            '20, 18, 16, 14, 12, 10 — rule: subtract 2')

    def test_numbers_alone_compose_to_the_numbers(self):
        assert compose_answer(['3', '6', '9'], '') == '3, 6, 9'

    def test_empty_boxes_are_dropped_not_left_as_gaps(self):
        # Spare boxes on a question that fixes no count: "3, 6, 9, , " is not
        # something to hand a grader.
        assert compose_answer(['3', '6', '9', '', '  '], '') == '3, 6, 9'

    def test_a_rule_the_student_labelled_themselves_is_not_doubled(self):
        for typed in ('rule: add 3', 'Rule add 3', 'The rule is: add 3',
                      'the rule is add 3'):
            assert compose_answer(['3', '6', '9'], typed) == (
                '3, 6, 9 — rule: add 3'), typed

    def test_a_rule_with_no_numbers_still_composes(self):
        # Nothing worth grading, but it must not compose to " — rule: add 3"
        # with a dangling separator.
        assert compose_answer(['', ''], 'add 3') == 'rule: add 3'

    def test_nothing_typed_composes_to_nothing(self):
        assert compose_answer(['', '', ''], '') == ''

    def test_whitespace_around_a_value_is_trimmed(self):
        assert compose_answer([' 20 ', '18'], ' subtract 2 ') == (
            '20, 18 — rule: subtract 2')


class TestTheComposedLineGrades:
    """The point of the format: what the boxes build, the grader reads."""

    def test_the_right_pattern_with_its_rule_is_correct(self):
        answer = compose_answer(['20', '18', '16', '14', '12', '10'],
                                'subtract 2')
        assert grade_pattern(SIX_AND_A_RULE, answer).is_correct

    def test_the_rule_is_never_read_as_another_number_of_the_pattern(self):
        """The reason the rule box leads with the word "rule".

        "20, 18, 16, 14, 12, 10" and a rule of 2 is six numbers and a rule —
        read as seven numbers it is a broken pattern of the wrong length.
        """
        answer = compose_answer(['20', '18', '16', '14', '12', '10'], '2')
        grade = grade_pattern(SIX_AND_A_RULE, answer)
        assert grade.is_correct, grade.feedback

    def test_a_rule_that_contradicts_the_numbers_is_caught(self):
        answer = compose_answer(['20', '18', '16', '14', '12', '10'],
                                'subtract 5')
        grade = grade_pattern(SIX_AND_A_RULE, answer)
        assert not grade.is_correct
        assert '5' in grade.feedback

    def test_a_pattern_running_the_wrong_way_is_still_wrong(self):
        # The defect that started this: an ADDITION pattern answering a
        # SUBTRACTION question, marked correct by an AI grader.
        answer = compose_answer(['5', '8', '11', '14', '17', '20'], 'add 3')
        grade = grade_pattern(SIX_AND_A_RULE, answer)
        assert not grade.is_correct
        assert 'subtraction' in grade.feedback.lower()

    def test_too_few_numbers_is_told_in_numbers_of_boxes(self):
        answer = compose_answer(['20', '18', '16', '', '', ''], 'subtract 2')
        grade = grade_pattern(SIX_AND_A_RULE, answer)
        assert not grade.is_correct
        assert 'asks for 6 numbers' in grade.feedback

    def test_an_empty_rule_box_does_not_fail_a_right_pattern(self):
        """The rule is visible in the numbers; the nudge is a note, not a mark."""
        answer = compose_answer(['20', '18', '16', '14', '12', '10'], '')
        grade = grade_pattern(SIX_AND_A_RULE, answer)
        assert grade.is_correct
        assert 'rule' in grade.feedback.lower()


@pytest.mark.django_db
class TestPatternFieldDataOnTheQuestion:
    """``Question.pattern_field_data`` — render data on the model."""

    def _question(self, text=SIX_AND_A_RULE, **kwargs):
        from classroom.models import Level, Subject, Topic
        from maths.models import Question
        subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})
        level, _ = Level.objects.get_or_create(
            level_number=4, defaults={'display_name': 'Year 4'})
        topic, _ = Topic.objects.get_or_create(
            subject=subject, name='Patterns fields', slug='patterns-fields',
            defaults={'is_active': True})
        kwargs.setdefault('answer_format', Question.ANSWER_FORMAT_PATTERN)
        return Question.objects.create(
            question_text=text, question_type=Question.SHORT_ANSWER,
            topic=topic, level=level, **kwargs)

    def test_a_pattern_question_carries_its_boxes(self):
        data = self._question().pattern_field_data
        assert data == {'count': 6, 'indexes': [0, 1, 2, 3, 4, 5],
                        'needs_rule': True, 'fixed': True}

    def test_every_other_question_gets_the_plain_box(self):
        from maths.models import Question
        other = self._question(text='What is 5531 - 4414?',
                               answer_format=Question.ANSWER_FORMAT_TEXT)
        assert other.pattern_field_data is None
