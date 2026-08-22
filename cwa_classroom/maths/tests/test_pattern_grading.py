"""Grading a pattern the student invented — maths.pattern_grading.

The defect these pin: "Create your own tricky subtraction number pattern of six
numbers and write down the rule you used" stores no correct Answer row, because
there is no single correct answer. The typed-answer grader reads "no stored
answer" as "nothing matches" and marks the student wrong — so a Year 4 student
who answered ``20, 18, 16, 14, 12, 10`` (a perfectly good subtraction pattern)
was told ❌ Incorrect, and so was every other student, forever.

Pure-function behaviour is checked directly; the model wiring
(``answer_format='pattern'`` → this grader, with no Answer rows in sight) is
checked against the database at the bottom.
"""
from fractions import Fraction

from django.test import TestCase

from classroom.models import Level
from maths.models import Answer, Question
from maths.pattern_grading import (
    ADD, DIVIDE, MULTIPLY, SUBTRACT, PatternRequest, example_answer,
    extract_numbers, grade_pattern, looks_like_pattern_question,
    parse_pattern_request,
)

# The question from the bug report, verbatim.
THE_QUESTION = ('Create your own tricky subtraction number pattern of six '
                'numbers and write down the rule you used.')


class ReadingTheQuestionTests(TestCase):
    def test_the_reported_question_is_read_in_full(self):
        self.assertEqual(
            parse_pattern_request(THE_QUESTION),
            PatternRequest(operation=SUBTRACT, length=6, step=None,
                           needs_rule=True))

    def test_operation_and_count_are_picked_up_in_other_wordings(self):
        request = parse_pattern_request(
            'Make up your own multiplication pattern of five numbers.')
        self.assertEqual(request.operation, MULTIPLY)
        self.assertEqual(request.length, 5)
        self.assertFalse(request.needs_rule)

        request = parse_pattern_request(
            'Design your own division sequence and state the rule.')
        self.assertEqual(request.operation, DIVIDE)
        self.assertIsNone(request.length)
        self.assertTrue(request.needs_rule)

    def test_a_rule_the_question_fixes_is_read_as_a_requirement(self):
        request = parse_pattern_request(
            'Write your own pattern of your own using the rule -3, '
            'with six numbers.')
        self.assertEqual(request.step, Fraction(3))
        # The question hands over the rule, so it is not also asking for it.
        self.assertFalse(request.needs_rule)

    def test_a_question_that_specifies_nothing_constrains_nothing(self):
        request = parse_pattern_request('Make up your own number pattern.')
        self.assertEqual(request, PatternRequest())

    def test_the_four_live_questions_in_topic_147_are_detected(self):
        """Wording taken from the production catalogue — these are the four
        questions in Patterns/Year 4 that store no answer at all."""
        live = [
            ('Create your own tricky addition number pattern. '
             'Write down your rule.', ADD, None),
            ('Create your own tricky subtraction number pattern. '
             'Write down your rule.', SUBTRACT, None),
            ('Create your own tricky addition number pattern of six numbers '
             'and write down the rule you used.', ADD, 6),
            (THE_QUESTION, SUBTRACT, 6),
        ]
        for text, operation, length in live:
            with self.subTest(text=text):
                self.assertTrue(looks_like_pattern_question(text))
                request = parse_pattern_request(text)
                self.assertEqual(request.operation, operation)
                self.assertEqual(request.length, length)
                self.assertTrue(request.needs_rule)

    def test_only_invent_your_own_questions_are_detected(self):
        self.assertTrue(looks_like_pattern_question(THE_QUESTION))
        self.assertTrue(looks_like_pattern_question(
            'Make up a number pattern and swap it with a partner.'))
        # "pattern" plus a verb is not enough — this one has a real answer and
        # tagging it would accept anything the student typed.
        self.assertFalse(looks_like_pattern_question(
            'Write down the next three numbers in this pattern: 3, 6, 9.'))
        self.assertFalse(looks_like_pattern_question(
            'What is the rule for the pattern 4, 8, 12, 16?'))
        self.assertFalse(looks_like_pattern_question('Calculate 5531 - 4414.'))


class ReadingTheAnswerTests(TestCase):
    def _values(self, text):
        return [value for value, _, _ in extract_numbers(text)]

    def test_numbers_are_read_however_they_are_separated(self):
        self.assertEqual(self._values('20,18, 16, 14, 12, 10'),
                         [20, 18, 16, 14, 12, 10])
        self.assertEqual(self._values('20 18 16 14 12 10'),
                         [20, 18, 16, 14, 12, 10])

    def test_a_minus_is_a_sign_on_a_value_but_an_operator_between_two(self):
        self.assertEqual(self._values('4, 2, 0, -2'), [4, 2, 0, -2])
        self.assertEqual(self._values('20 - 2'), [20, 2])

    def test_decimals_and_grouped_thousands_survive(self):
        self.assertEqual(self._values('2.5, 5, 7.5'),
                         [Fraction('2.5'), 5, Fraction('7.5')])
        self.assertEqual(self._values('1,000, 900'), [1000, 900])


class GradingTheReportedQuestionTests(TestCase):
    """The exact answer from the bug report, and its neighbours."""

    def test_the_students_answer_is_correct(self):
        grade = grade_pattern(THE_QUESTION, '20,18, 16, 14, 12, 10')
        self.assertTrue(grade.is_correct)
        self.assertIn('goes down by 2', grade.feedback)

    def test_a_missing_rule_is_coached_not_failed(self):
        """The numbers ARE the rule made visible, so a bare pattern still
        earns the mark — with the reminder attached to it."""
        grade = grade_pattern(THE_QUESTION, '20, 18, 16, 14, 12, 10')
        self.assertTrue(grade.is_correct)
        self.assertIn('rule', grade.feedback.lower())

    def test_the_rule_is_accepted_however_the_student_writes_it(self):
        for answer in (
            '20, 18, 16, 14, 12, 10 rule -2',
            '20, 18, 16, 14, 12, 10, rule: take away 2',
            '20, 18, 16, 14, 12, 10 (minus 2 each time)',
            'rule -2: 20, 18, 16, 14, 12, 10',
            'my rule is subtract 2 — 20, 18, 16, 14, 12, 10',
        ):
            with self.subTest(answer=answer):
                grade = grade_pattern(THE_QUESTION, answer)
                self.assertTrue(grade.is_correct, grade.feedback)
                # Rule given, so no reminder to give it.
                self.assertNotIn('next time', grade.feedback)

    def test_a_dash_beside_a_rule_is_punctuation_not_a_minus(self):
        """Found on production. Em and en dashes fold to "-" so a typed minus
        is read whichever character the student reached for — but the dash in
        "5, 8, 11 — rule: add 3" is punctuation. Reading it as "subtract" made
        it contradict the stated rule, so every correct answer to a "create
        your own ADDITION pattern" question was failed. The equivalent
        subtraction answer passed by coincidence, which is what hid it."""
        addition = ('Create your own tricky addition number pattern of six '
                    'numbers and write down the rule you used.')
        for answer in (
            '5, 8, 11, 14, 17, 20 — rule: add 3',    # em dash
            '5, 8, 11, 14, 17, 20 – rule: add 3',    # en dash
            '5, 8, 11, 14, 17, 20 - add 3',          # hyphen
        ):
            with self.subTest(answer=answer):
                grade = grade_pattern(addition, answer)
                self.assertTrue(grade.is_correct, grade.feedback)

    def test_a_minus_on_a_number_is_still_a_rule(self):
        # The fix must not stop "-2" being read as the rule it is.
        for answer in ('20, 18, 16, 14, 12, 10 rule -2',
                       '20, 18, 16, 14, 12, 10 - 2 each time'):
            with self.subTest(answer=answer):
                self.assertTrue(grade_pattern(THE_QUESTION, answer).is_correct)

    def test_a_rule_that_really_contradicts_the_numbers_still_fails(self):
        addition = ('Create your own tricky addition number pattern of six '
                    'numbers and write down the rule you used.')
        grade = grade_pattern(addition, '5, 8, 11, 14, 17, 20 — rule: subtract 3')
        self.assertFalse(grade.is_correct)
        self.assertIn('subtraction', grade.feedback)

    def test_a_rule_that_contradicts_the_numbers_is_wrong(self):
        grade = grade_pattern(THE_QUESTION,
                              '20, 18, 16, 14, 12, 10 my rule was subtract 3')
        self.assertFalse(grade.is_correct)
        self.assertIn('3', grade.feedback)

    def test_an_addition_pattern_does_not_answer_a_subtraction_question(self):
        grade = grade_pattern(THE_QUESTION, '2, 4, 6, 8, 10, 12')
        self.assertFalse(grade.is_correct)
        self.assertIn('subtraction', grade.feedback)

    def test_numbers_that_do_not_share_a_step_are_wrong(self):
        grade = grade_pattern(THE_QUESTION, '20, 18, 15, 14, 12, 10')
        self.assertFalse(grade.is_correct)
        self.assertIn('18 to 15', grade.feedback)

    def test_the_wrong_count_is_named_as_the_wrong_count(self):
        for answer, wrote in (('20, 18, 16, 14, 12', 5),
                              ('20, 18, 16, 14, 12, 10, 8', 7)):
            with self.subTest(answer=answer):
                grade = grade_pattern(THE_QUESTION, answer)
                self.assertFalse(grade.is_correct)
                self.assertIn(str(wrote), grade.feedback)

    def test_an_answer_with_no_pattern_in_it_says_so(self):
        for answer in ('', '   ', 'i dont know', '7'):
            with self.subTest(answer=answer):
                grade = grade_pattern(THE_QUESTION, answer)
                self.assertFalse(grade.is_correct)
                self.assertIn('could not find', grade.feedback)

    def test_repeating_the_same_number_is_not_a_pattern(self):
        grade = grade_pattern(THE_QUESTION, '5, 5, 5, 5, 5, 5')
        self.assertFalse(grade.is_correct)
        self.assertIn('stay on 5', grade.feedback)

    def test_negative_values_inside_the_pattern_are_not_read_as_a_rule(self):
        """``-2`` is one of the numbers here, not a stated rule of 2."""
        grade = grade_pattern(THE_QUESTION, '4, 2, 0, -2, -4, -6')
        self.assertTrue(grade.is_correct, grade.feedback)


class GradingOtherPatternQuestionsTests(TestCase):
    def test_a_multiplication_pattern(self):
        question = 'Make up your own multiplication pattern of five numbers.'
        self.assertTrue(grade_pattern(question, '2, 4, 8, 16, 32').is_correct)
        self.assertTrue(grade_pattern(question, '1, 3, 9, 27, 81').is_correct)
        # Adding 3 each time is not multiplying.
        grade = grade_pattern(question, '3, 6, 9, 12, 15')
        self.assertFalse(grade.is_correct)
        self.assertIn('multiplication', grade.feedback)

    def test_a_division_pattern(self):
        question = 'Create your own division pattern of four numbers.'
        self.assertTrue(grade_pattern(question, '64, 32, 16, 8').is_correct)
        self.assertFalse(grade_pattern(question, '2, 4, 8, 16').is_correct)

    def test_a_rule_the_question_fixed_must_be_the_rule_used(self):
        question = ('Write your own pattern of your own using the rule -3, '
                    'with six numbers.')
        self.assertTrue(grade_pattern(question, '20, 17, 14, 11, 8, 5').is_correct)
        grade = grade_pattern(question, '20, 18, 16, 14, 12, 10')
        self.assertFalse(grade.is_correct)
        self.assertIn('3', grade.feedback)

    def test_two_numbers_do_not_show_a_rule(self):
        question = 'Make up your own number pattern.'
        self.assertFalse(grade_pattern(question, '20, 18').is_correct)
        self.assertTrue(grade_pattern(question, '20, 18, 16').is_correct)

    def test_an_unconstrained_question_accepts_any_real_pattern(self):
        question = 'Make up your own number pattern.'
        self.assertTrue(grade_pattern(question, '5, 10, 15, 20').is_correct)
        self.assertTrue(grade_pattern(question, '81, 27, 9, 3').is_correct)
        self.assertFalse(grade_pattern(question, '3, 9, 2, 4').is_correct)


class ExampleAnswerTests(TestCase):
    """The worked example is shown to students AND submitted by
    ``manage.py verify_quiz_grading`` as the right answer, so it has to be one."""

    def test_the_example_is_always_accepted_by_the_grader(self):
        for question in (
            THE_QUESTION,
            'Make up your own multiplication pattern of five numbers.',
            'Create your own division pattern of four numbers.',
            'Design your own addition sequence of 3 numbers.',
            'Make up your own number pattern.',
            'Write your own pattern of your own using the rule -3, with six numbers.',
        ):
            with self.subTest(question=question):
                example = example_answer(parse_pattern_request(question))
                grade = grade_pattern(question, example)
                self.assertTrue(grade.is_correct,
                                f'{example!r}: {grade.feedback}')

    def test_the_example_states_the_rule_when_the_question_asks_for_one(self):
        self.assertIn('rule', example_answer(parse_pattern_request(THE_QUESTION)))

    def test_the_example_has_the_requested_number_of_terms(self):
        example = example_answer(PatternRequest(operation=ADD, length=4))
        self.assertEqual(len(extract_numbers(example)), 4)


class PatternAnswerFormatRoutingTests(TestCase):
    """The model wiring: a question with NO stored answer still grades."""

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=993, defaults={'display_name': 'pattern fixture'})

    def _question(self, answer_format=Question.ANSWER_FORMAT_PATTERN,
                  text=THE_QUESTION):
        return Question.objects.create(
            level=self.level, question_text=text,
            question_type=Question.SHORT_ANSWER, answer_format=answer_format,
            difficulty=1, points=1,
        )

    def test_a_pattern_question_grades_with_no_answer_rows_at_all(self):
        question = self._question()
        self.assertFalse(question.answers.exists())
        self.assertTrue(question.grade_text_answer('20, 18, 16, 14, 12, 10'))
        self.assertFalse(question.grade_text_answer('2, 4, 6, 8, 10, 12'))

    def test_an_empty_answer_is_still_wrong(self):
        question = self._question()
        self.assertFalse(question.grade_text_answer(''))

    def test_a_text_question_with_no_answer_rows_still_marks_wrong(self):
        """The old behaviour stays put for everything not tagged: a question
        missing its answer is a content defect, not an open question."""
        question = self._question(answer_format=Question.ANSWER_FORMAT_TEXT)
        self.assertFalse(question.grade_text_answer('20, 18, 16, 14, 12, 10'))

    def test_the_shown_answer_is_a_worked_example_not_a_blank(self):
        question = self._question()
        display = question.correct_answer_display()
        self.assertIn('for example', display.lower())
        # …and it is an example that would itself be marked correct.
        self.assertTrue(grade_pattern(THE_QUESTION, display).is_correct, display)

    def test_a_stored_answer_still_wins_the_display(self):
        question = self._question()
        Answer.objects.create(question=question, answer_text='30, 27, 24',
                              is_correct=True)
        self.assertEqual(question.correct_answer_display(), '30, 27, 24')
