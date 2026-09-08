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

from django.test import SimpleTestCase, TestCase

from classroom.models import Level
from maths.models import Answer, Question
from maths.pattern_grading import (
    ADD, DIVIDE, MULTIPLY, NUMBERS, RULE, SUBTRACT, PatternRequest,
    completes_printed_pattern, completion_parts, example_answer,
    extract_numbers, grade_pattern, looks_like_pattern_question,
    parse_pattern_request, read_printed_pattern,
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


# The other pattern shape, from the second bug report: the question prints the
# pattern with gaps in it and asks for two things — the missing numbers and the
# rule — but its stored answer is only the rule.
THE_COMPLETION_QUESTION = (
    'Work out the number pattern rule and complete the pattern: '
    '30, ___, 60, 75, ___, ___. What is the rule?'
)
THE_STORED_ROWS = ['+15', 'add 15', '+ 15']


class ReadingAPrintedPatternTests(SimpleTestCase):
    """Solving the sequence the question prints, gaps and all."""

    def test_the_reported_question_is_solved_in_full(self):
        pattern = read_printed_pattern(THE_COMPLETION_QUESTION)
        self.assertEqual(pattern.values,
                         [Fraction(n) for n in (30, 45, 60, 75, 90, 105)])
        self.assertEqual(pattern.missing,
                         [Fraction(n) for n in (45, 90, 105)])
        self.assertEqual(pattern.operation, ADD)
        self.assertEqual(pattern.size, Fraction(15))

    def test_the_step_spans_the_gap_it_jumps(self):
        # 30 to 60 is two steps of 15, not one of 30. Reading it as 30 would
        # have marked the whole answer wrong.
        pattern = read_printed_pattern('Complete: 30, ___, 60.')
        self.assertEqual(pattern.missing, [Fraction(45)])

    def test_a_falling_pattern_reads_as_subtraction(self):
        pattern = read_printed_pattern(
            'Complete the pattern and give the rule: 40, 36, 32, ___, ___.')
        self.assertEqual(pattern.missing, [Fraction(28), Fraction(24)])
        self.assertEqual((pattern.operation, pattern.size),
                         (SUBTRACT, Fraction(4)))

    def test_a_doubling_pattern_reads_as_multiplication(self):
        pattern = read_printed_pattern(
            'What are the next two numbers? 2, 4, 8, 16, ___, ___.')
        self.assertEqual(pattern.missing, [Fraction(32), Fraction(64)])
        self.assertEqual((pattern.operation, pattern.size),
                         (MULTIPLY, Fraction(2)))

    def test_a_question_marks_the_gap_too(self):
        pattern = read_printed_pattern('Fill the gaps: 5, ?, 15, ?')
        self.assertEqual(pattern.missing, [Fraction(10), Fraction(20)])

    def test_the_longest_sequence_is_the_one_the_question_is_about(self):
        pattern = read_printed_pattern(
            'Here is a pattern that starts 2, 4, 6. Complete this one: '
            '30, ___, 60, 75, ___, ___.')
        self.assertEqual(pattern.missing,
                         [Fraction(n) for n in (45, 90, 105)])

    # ── the questions this must keep its hands off ──────────────────────

    def test_a_sequence_with_no_gap_is_not_a_completion_question(self):
        self.assertIsNone(read_printed_pattern(
            'Write these numbers in order: 3, 5, 7'))

    def test_numbers_that_share_no_rule_are_left_alone(self):
        self.assertIsNone(read_printed_pattern(
            'Which is the odd one out: 2, 5, 6, ___?'))

    def test_a_gap_that_is_not_in_a_sequence_is_left_alone(self):
        self.assertIsNone(read_printed_pattern(
            'Fill in the missing number: 8 + 8 = ____ x 8'))

    def test_one_known_number_decides_nothing(self):
        self.assertIsNone(read_printed_pattern('Complete: 30, ___, ___.'))

    def test_a_multiplier_is_read_from_two_adjacent_numbers(self):
        pattern = read_printed_pattern('Complete: 2, 4, ___, 16.')
        self.assertEqual(pattern.missing, [Fraction(8)])

    def test_a_multiplier_is_not_read_across_a_gap(self):
        # 2, _, 8, 16 needs a multiplier taken over two places to be x2, and
        # x-2 fits the visible numbers just as well. Refused rather than
        # guessed at.
        self.assertIsNone(read_printed_pattern('Complete: 2, ___, 8, 16.'))

    def test_arithmetic_wins_a_reading_that_could_go_either_way(self):
        # 3, _, 27 is +12 and x3 alike, and arithmetic is taken first here as
        # it is everywhere else in this module. A reading the question did not
        # mean costs nothing: an answer that does not fit it is simply not
        # rescued, which leaves the ordinary answer matching as it was.
        question = 'Complete: 3, ___, 27.'
        self.assertEqual(read_printed_pattern(question).missing, [Fraction(15)])
        self.assertFalse(completes_printed_pattern(question, ['9'], '9 — x3'))


class WhatAnAnswerSuppliesTests(SimpleTestCase):
    """Reading an answer against the pattern the question printed."""

    def setUp(self):
        self.pattern = read_printed_pattern(THE_COMPLETION_QUESTION)

    def _parts(self, text):
        return completion_parts(text, self.pattern)

    def test_the_reported_answer_supplies_both_halves(self):
        # Typed into the quiz exactly like this, quotes and all.
        self.assertEqual(self._parts('add 15 " 45, 90, 105 "'), {NUMBERS, RULE})

    def test_the_rule_alone_is_the_rule_alone(self):
        self.assertEqual(self._parts('+15'), {RULE})
        self.assertEqual(self._parts('add 15'), {RULE})

    def test_the_numbers_alone_are_the_numbers_alone(self):
        self.assertEqual(self._parts('45, 90, 105'), {NUMBERS})

    def test_writing_out_the_whole_sequence_counts_as_the_numbers(self):
        self.assertEqual(self._parts('30, 45, 60, 75, 90, 105'), {NUMBERS})

    def test_the_two_halves_read_in_either_order(self):
        self.assertEqual(self._parts('45, 90, 105 — rule: add 15'),
                         {NUMBERS, RULE})
        self.assertEqual(self._parts('+15; 45, 90, 105'), {NUMBERS, RULE})

    def test_prose_around_the_answer_does_not_hide_it(self):
        self.assertEqual(
            self._parts('the rule is add 15 and the missing numbers are '
                        '45, 90 and 105'),
            {NUMBERS, RULE})

    # ── wrong is wrong, never "partly supplied" ─────────────────────────

    def test_a_wrong_rule_is_rejected_outright(self):
        self.assertIsNone(self._parts('add 5 " 45, 90, 105 "'))

    def test_a_rule_pointing_the_wrong_way_is_rejected(self):
        self.assertIsNone(self._parts('subtract 15'))

    def test_one_wrong_number_fails_the_whole_list(self):
        self.assertIsNone(self._parts('add 15 " 45, 90, 100 "'))

    def test_a_stray_number_is_not_ignored(self):
        self.assertIsNone(self._parts('45, 90, 105 and 200'))

    def test_a_bare_number_states_no_rule(self):
        # "15" could be +15 or -15; the question asked which.
        self.assertIsNone(self._parts('15'))

    def test_nothing_at_all_supplies_nothing(self):
        self.assertIsNone(self._parts(''))
        self.assertIsNone(self._parts('I do not know'))


class CompletingAPrintedPatternTests(SimpleTestCase):
    """The rescue itself: what it accepts, and what it still marks wrong."""

    def _grade(self, answer, question=THE_COMPLETION_QUESTION,
               rows=THE_STORED_ROWS):
        return completes_printed_pattern(question, rows, answer)

    def test_the_reported_answer_is_accepted(self):
        # The whole point: "add 15 " 45, 90, 105 "" was marked ❌ Incorrect
        # under a correct answer of "+15 or add 15 or + 15".
        self.assertTrue(self._grade('add 15 " 45, 90, 105 "'))

    def test_the_stored_answer_itself_still_passes(self):
        for row in THE_STORED_ROWS:
            self.assertTrue(self._grade(row), row)

    def test_the_rule_beside_the_whole_sequence_passes(self):
        self.assertTrue(self._grade('+15; 30, 45, 60, 75, 90, 105'))

    def test_an_answer_that_says_less_than_the_stored_one_still_fails(self):
        # The stored answer is the rule, and the question asks for it in so
        # many words. Numbers alone have not answered "what is the rule?".
        self.assertFalse(self._grade('45, 90, 105'))

    def test_a_wrong_rule_beside_right_numbers_still_fails(self):
        self.assertFalse(self._grade('45, 90, 105 — rule: add 5'))

    def test_right_rule_beside_wrong_numbers_still_fails(self):
        self.assertFalse(self._grade('add 15 " 45, 90, 100 "'))

    def test_it_works_the_other_way_round_too(self):
        # A question whose stored answer is the NUMBERS: a student who adds
        # the rule beside them has still answered it.
        question = 'Complete the pattern: 14, 18, 22, __, __, __.'
        rows = ['26, 30, 34']
        self.assertTrue(completes_printed_pattern(
            question, rows, '26, 30, 34 — add 4 each time'))
        self.assertTrue(completes_printed_pattern(
            question, rows, '+4; 26, 30, 34'))
        # …and the rule alone is not the three numbers it asked for.
        self.assertFalse(completes_printed_pattern(question, rows, 'add 4'))

    def test_a_falling_pattern_is_graded_the_same_way(self):
        question = 'Complete the pattern and give the rule: 40, 36, 32, ___, ___.'
        rows = ['-4', 'subtract 4']
        self.assertTrue(completes_printed_pattern(
            question, rows, '28, 24 take away 4'))
        self.assertTrue(completes_printed_pattern(question, rows, '28, 24 -4'))
        self.assertFalse(completes_printed_pattern(
            question, rows, '28, 24 add 4'))

    def test_a_doubling_pattern_is_graded_the_same_way(self):
        question = ('What are the next two numbers? 2, 4, 8, 16, ___, ___. '
                    'What is the rule?')
        rows = ['x2', 'multiply by 2']
        self.assertTrue(completes_printed_pattern(
            question, rows, '32, 64 multiply by 2'))
        self.assertFalse(completes_printed_pattern(
            question, rows, '32, 64 add 16'))

    # ── it declines everything that is not this shape ───────────────────

    def test_a_question_with_no_printed_pattern_is_declined(self):
        self.assertFalse(completes_printed_pattern(
            'What is 4 + 5?', ['9'], '9 apples'))

    def test_a_stored_answer_it_cannot_read_leaves_the_question_alone(self):
        # Nothing to compare "says at least as much" against, so no rescue.
        self.assertFalse(self._grade('add 15 " 45, 90, 105 "',
                                     rows=['fifteen more each time']))

    def test_an_empty_answer_is_never_rescued(self):
        self.assertFalse(self._grade(''))
        self.assertFalse(self._grade('   '))


class PatternCompletionRoutingTests(TestCase):
    """The model wiring: a stored-answer question, graded by the question."""

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=992, defaults={'display_name': 'completion fixture'})
        cls.question = Question.objects.create(
            level=cls.level, question_text=THE_COMPLETION_QUESTION,
            question_type=Question.SHORT_ANSWER,
            answer_format=Question.ANSWER_FORMAT_TEXT, difficulty=1, points=1,
        )
        for row in THE_STORED_ROWS:
            Answer.objects.create(question=cls.question, answer_text=row,
                                  is_correct=True)
        Answer.objects.create(question=cls.question, answer_text='+30',
                              is_correct=False)

    def test_the_reported_answer_now_grades_correct(self):
        self.assertTrue(self.question.grade_text_answer('add 15 " 45, 90, 105 "'))

    def test_the_stored_spellings_grade_correct_as_they_always_did(self):
        for row in THE_STORED_ROWS:
            self.assertTrue(self.question.grade_text_answer(row), row)

    def test_a_wrong_answer_is_still_wrong(self):
        self.assertFalse(self.question.grade_text_answer('add 5'))
        self.assertFalse(self.question.grade_text_answer('+30'))
        self.assertFalse(self.question.grade_text_answer('45, 90, 100 add 15'))

    def test_an_ordinary_typed_question_is_untouched(self):
        question = Question.objects.create(
            level=self.level, question_text='What is 4 + 5?',
            question_type=Question.SHORT_ANSWER,
            answer_format=Question.ANSWER_FORMAT_TEXT, difficulty=1, points=1,
        )
        Answer.objects.create(question=question, answer_text='9', is_correct=True)
        self.assertTrue(question.grade_text_answer('9'))
        self.assertFalse(question.grade_text_answer('9, 10'))
