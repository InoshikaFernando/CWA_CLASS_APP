"""The wrong-answer leaderboard, the Reviewed verdict, and the re-mark on save.

Three things are being defended here, and they are the three ways this feature
could quietly lie:

1. The rate must rank on real evidence — not on a question one child answered
   once, and not on a retired question nobody meets any more.
2. Reviewing must SETTLE the answers recorded before it, not hide the question:
   a question students go on getting wrong has to come back on its own.
3. Fixing an answer key must give back the marks the old key took. A repair
   that only works from now on leaves every child who already sat it with the
   nought, which is the half of the bug a parent actually notices.
"""
import uuid
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from classroom.models import Level, Subject, Topic
from maths.answer_key_regrade import regrade_question
from maths.models import (
    Answer, Question, QuestionReview, StudentAnswer, StudentFinalAnswer,
)
from maths.question_difficulty import wrong_rate_rows
from maths.question_review import record_review

User = get_user_model()


class WrongRateTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            username='rateadmin', email='rate@test.com', password='pass1234')
        cls.subject = Subject.objects.create(name='Mathematics',
                                             slug='mathematics')
        cls.level = Level.objects.create(level_number=7, display_name='Year 7')
        cls.topic = Topic.objects.create(name='Fractions', slug='fractions',
                                         subject=cls.subject)
        cls.students = [
            User.objects.create_user(username=f'ratekid{i}',
                                     email=f'rk{i}@test.com', password='pass1234')
            for i in range(12)
        ]

    def question(self, text='What is 1/2 + 1/4?',
                 options=(('3/4', True), ('1/4', False)),
                 question_type=Question.MULTIPLE_CHOICE, **kwargs):
        question = Question.objects.create(
            level=self.level, topic=self.topic, question_text=text,
            question_type=question_type, difficulty=1, **kwargs)
        for order, (answer_text, correct) in enumerate(options):
            Answer.objects.create(question=question, answer_text=answer_text,
                                  is_correct=correct, order=order)
        return question

    def answer(self, question, student, *, correct, option=None, when=None):
        row = StudentAnswer.objects.create(
            student=student, question=question, selected_answer=option,
            is_correct=correct, attempt_id=uuid.uuid4())
        if when is not None:
            # answered_at is auto_now_add, so back-dating needs a direct write.
            StudentAnswer.objects.filter(pk=row.pk).update(answered_at=when)
            row.refresh_from_db()
        return row

    def sit(self, question, *, wrong, right=0, when=None, option=None):
        """``wrong`` students get it wrong and ``right`` get it right."""
        pool = iter(self.students)
        for _ in range(wrong):
            self.answer(question, next(pool), correct=False, option=option,
                        when=when)
        for _ in range(right):
            self.answer(question, next(pool), correct=True, when=when)


class WrongRateRankingTests(WrongRateTestBase):

    def test_ranks_by_wrong_share_not_by_wrong_count(self):
        # 6 wrong of 12 — more wrong answers, but half the rate.
        busy = self.question(text='Busy question')
        self.sit(busy, wrong=6, right=6)
        # 5 wrong of 5 — fewer wrong answers, and it is marking everybody wrong.
        broken = self.question(text='Broken question')
        self.sit(broken, wrong=5)

        rows = wrong_rate_rows()

        self.assertEqual([row['question'].id for row in rows],
                         [broken.id, busy.id])
        self.assertEqual(rows[0]['percent'], 100.0)
        self.assertEqual(rows[1]['percent'], 50.0)
        self.assertEqual(rows[1]['wrong'], 6)
        self.assertEqual(rows[1]['attempts'], 12)

    def test_a_question_barely_answered_is_not_ranked(self):
        # 100% wrong, but from four children. Ranking it would point the
        # reviewer at the question with the least evidence behind it.
        thin = self.question(text='Answered four times')
        self.sit(thin, wrong=4)

        self.assertEqual(wrong_rate_rows(), [])

    def test_a_question_nobody_gets_wrong_is_not_ranked(self):
        clean = self.question(text='Everybody gets this')
        self.sit(clean, wrong=0, right=6)

        self.assertEqual(wrong_rate_rows(), [])

    def test_retired_questions_are_left_out(self):
        retired = self.question(text='Retired question')
        self.sit(retired, wrong=6)
        retired.retire(reason='replaced')

        self.assertEqual(wrong_rate_rows(), [])

    def test_the_list_is_capped_at_the_top_n(self):
        for index in range(12):
            question = self.question(text=f'Bad question {index}')
            self.sit(question, wrong=5)

        self.assertEqual(len(wrong_rate_rows()), 10)
        self.assertEqual(len(wrong_rate_rows(limit=3)), 3)


class ReviewSettlesThePastTests(WrongRateTestBase):

    def test_reviewing_drops_it_from_the_list(self):
        question = self.question(text='Reviewed question')
        self.sit(question, wrong=6)
        self.assertEqual(len(wrong_rate_rows()), 1)

        record_review(question, user=self.superuser,
                      verdict=QuestionReview.VERDICT_CORRECT)

        self.assertEqual(wrong_rate_rows(), [])

    def test_answers_given_after_the_review_bring_it_back(self):
        """The whole point of settling the past rather than hiding the row.

        A reviewer's verdict answers the evidence in front of them. Fifty more
        children getting it wrong afterwards is new evidence, and a list that
        could never show it again would be the dashboard vouching for a
        question it has stopped watching.
        """
        question = self.question(text='Still wrong afterwards')
        self.sit(question, wrong=6,
                 when=timezone.now() - timedelta(days=3))
        record_review(question, user=self.superuser,
                      verdict=QuestionReview.VERDICT_CORRECT)
        self.assertEqual(wrong_rate_rows(), [])

        self.sit(question, wrong=5)

        rows = wrong_rate_rows()
        self.assertEqual(len(rows), 1)
        # Counted from the review, not from the beginning: 5 of 5, not 11 of 11.
        self.assertEqual(rows[0]['attempts'], 5)
        self.assertIsNotNone(rows[0]['since'])

    def test_a_needs_fixing_verdict_settles_the_past_too(self):
        # Somebody has looked and the question is on their list; re-listing it
        # adds nothing they do not already know.
        question = self.question(text='Known broken')
        self.sit(question, wrong=6)

        record_review(question, user=self.superuser,
                      verdict=QuestionReview.VERDICT_BROKEN)

        self.assertEqual(wrong_rate_rows(), [])


class ReviewedButtonTests(WrongRateTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='rateadmin', password='pass1234')

    def test_the_button_records_a_verdict_and_redraws_the_panel(self):
        question = self.question(text='Reviewed by button')
        self.sit(question, wrong=6)

        response = self.client.post(
            reverse('question_reviewed_admin_dashboard'),
            {'question_id': question.id}, HTTP_HX_REQUEST='true')

        self.assertEqual(response.status_code, 200)
        review = QuestionReview.objects.get(question=question)
        self.assertEqual(review.verdict, QuestionReview.VERDICT_CORRECT)
        self.assertEqual(review.reviewed_by, self.superuser)
        # The content version is snapshotted, so a later edit makes the verdict
        # stale rather than letting it vouch for text nobody read.
        self.assertEqual(review.question_updated_at, question.updated_at)
        # The row it was clicked on is gone from what came back.
        self.assertNotContains(response, f'wrong-rate-row-{question.id}')

    def test_an_unknown_question_says_so_rather_than_doing_nothing(self):
        response = self.client.post(
            reverse('question_reviewed_admin_dashboard'),
            {'question_id': 99999}, HTTP_HX_REQUEST='true')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'nothing was reviewed')
        self.assertFalse(QuestionReview.objects.exists())

    def test_a_non_superuser_cannot_review(self):
        question = self.question()
        self.sit(question, wrong=6)
        client = Client()
        client.force_login(self.students[0])

        response = client.post(reverse('question_reviewed_admin_dashboard'),
                               {'question_id': question.id})

        self.assertNotEqual(response.status_code, 200)
        self.assertFalse(QuestionReview.objects.exists())

    def test_the_dashboard_renders_the_panel(self):
        question = self.question(text='Shown on the dashboard')
        self.sit(question, wrong=6)

        response = self.client.get(
            reverse('question_health_admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Most often answered wrong')
        self.assertContains(response, f'wrong-rate-row-{question.id}')


class RegradeOnSaveTests(WrongRateTestBase):
    """A fixed answer key must give back the marks the old one took."""

    def test_students_who_picked_the_now_correct_option_get_their_mark(self):
        question = self.question(
            text='666 in expanded form',
            options=(('600 + 60 + 6', False), ('6 + 6 + 6', True)))
        right_option = question.answers.get(answer_text='600 + 60 + 6')
        rows = [self.answer(question, student, correct=False,
                            option=right_option)
                for student in self.students[:3]]

        # The key is corrected, the way the editor would.
        question.answers.filter(answer_text='6 + 6 + 6').update(is_correct=False)
        question.answers.filter(answer_text='600 + 60 + 6').update(is_correct=True)

        regraded = regrade_question(question)

        self.assertEqual(regraded.quiz, 3)
        self.assertEqual(len(regraded.students), 3)
        for row in rows:
            row.refresh_from_db()
            self.assertTrue(row.is_correct)
            self.assertEqual(row.points_earned, question.points)
        self.assertIn('3 answers', regraded.summary())

    def test_a_mark_already_awarded_is_never_taken_away(self):
        """Wrong-to-right only — see the module docstring on answer_key_regrade.

        Taking a mark back from a child weeks later, because an adult changed
        their mind about the answer, is not something a Save button may do.
        """
        question = self.question(
            options=(('3/4', True), ('1/4', False)))
        was_right = question.answers.get(answer_text='3/4')
        row = self.answer(question, self.students[0], correct=True,
                          option=was_right)

        # Someone decides 1/4 is the answer instead.
        question.answers.filter(answer_text='3/4').update(is_correct=False)
        question.answers.filter(answer_text='1/4').update(is_correct=True)

        regrade_question(question)

        row.refresh_from_db()
        self.assertTrue(row.is_correct)

    def test_the_attempt_total_is_recounted_not_just_the_answer(self):
        question = self.question(
            text='666 in expanded form',
            options=(('600 + 60 + 6', False), ('6 + 6 + 6', True)))
        right_option = question.answers.get(answer_text='600 + 60 + 6')
        student = self.students[0]
        self.answer(question, student, correct=False, option=right_option)
        attempt = StudentFinalAnswer.objects.create(
            student=student, topic=self.topic, level=self.level,
            score=1, total_questions=2, time_taken_seconds=60,
            questions_data=[
                {'id': question.id, 'question': question.question_text,
                 'student_answer': '600 + 60 + 6', 'is_correct': False},
                {'id': 0, 'question': 'other', 'student_answer': 'x',
                 'is_correct': True},
            ])

        question.answers.filter(answer_text='6 + 6 + 6').update(is_correct=False)
        question.answers.filter(answer_text='600 + 60 + 6').update(is_correct=True)
        regraded = regrade_question(question)

        attempt.refresh_from_db()
        self.assertEqual(regraded.attempts, 1)
        self.assertEqual(attempt.score, 2)
        self.assertTrue(attempt.questions_data[0]['is_correct'])
        # Leaving the summary at its old score would fix the detail and keep
        # the number the child and their teacher actually read wrong.
        self.assertGreater(attempt.points, 0)

    def test_an_ai_graded_question_is_left_alone(self):
        question = self.question(text='Explain your reasoning',
                                 options=(('anything', True),))
        question.validation_type = Question.VALIDATION_AI
        question.save(update_fields=['validation_type'])
        row = self.answer(question, self.students[0], correct=False,
                          option=question.answers.first())

        regraded = regrade_question(question)

        self.assertFalse(regraded)
        row.refresh_from_db()
        self.assertFalse(row.is_correct)

def _regrade_input(response):
    """The re-mark tick box's own <input> tag, plus 'CHECKED' when it is ticked.

    Searching the whole page for "checked" would pass whatever the state is —
    every correct option in this form carries it.
    """
    import re

    html = response.content.decode()
    match = re.search(r'<input[^>]*name="regrade_answers"[^>]*>', html)
    assert match, 'the re-mark tick box is not on this form'
    tag = match.group(0)
    return tag + ('CHECKED' if re.search(r'\bchecked\b', tag) else '')


class EditorSaveTests(WrongRateTestBase):
    """What the editor's Save does, and the two gates that decide whether.

    Re-marking a child's record is not a side effect of pressing Save. It
    happens when a person asked for it AND the save actually changed how the
    question marks — and these tests are what keep both halves true.
    """

    def setUp(self):
        self.client = Client()
        self.client.login(username='rateadmin', password='pass1234')

    def _mismarked(self):
        """A question whose key has the wrong option ticked, already sat."""
        question = self.question(
            text='666 in expanded form', school=None,
            options=(('600 + 60 + 6', False), ('6 + 6 + 6', True)))
        right = question.answers.get(answer_text='600 + 60 + 6')
        wrong = question.answers.get(answer_text='6 + 6 + 6')
        row = self.answer(question, self.students[0], correct=False,
                          option=right)
        return question, right, wrong, row

    def _save(self, question, right, wrong, *, fix_key=True, regrade=True,
              text=None):
        payload = {
            'question_text': text or question.question_text,
            'question_type': Question.MULTIPLE_CHOICE,
            'answer_id': [right.id, wrong.id],
            f'answer_text_{right.id}': right.answer_text,
            f'answer_text_{wrong.id}': wrong.answer_text,
        }
        # Ticking the right option is what makes this a key correction; without
        # it the save changes nothing about how the question marks.
        payload[f'is_correct_{right.id}' if fix_key
                else f'is_correct_{wrong.id}'] = 'on'
        if regrade:
            payload['regrade_answers'] = 'on'
        return self.client.post(
            reverse('admin_global_question_edit', args=[question.id]), payload)

    def test_fixing_the_key_with_the_tick_re_marks_and_says_so(self):
        question, right, wrong, row = self._mismarked()

        response = self._save(question, right, wrong)

        self.assertEqual(response.status_code, 200)
        row.refresh_from_db()
        self.assertTrue(row.is_correct)
        self.assertContains(response, 'now marked correct')
        # And the notice is marked as worth reading, so the page holds the
        # modal open instead of closing it in the same frame.
        self.assertContains(response, 'data-hold')

    def test_without_the_tick_the_key_is_fixed_but_no_mark_moves(self):
        """The opt-in gate. Saving from the question bank leaves records alone.

        The same editor serves ordinary maintenance, where re-judging what
        children were marked years ago is not what anybody asked for.
        """
        question, right, wrong, row = self._mismarked()

        response = self._save(question, right, wrong, regrade=False)

        self.assertEqual(response.status_code, 200)
        right.refresh_from_db()
        self.assertTrue(right.is_correct)        # the question IS fixed
        row.refresh_from_db()
        self.assertFalse(row.is_correct)         # the record is untouched
        self.assertNotContains(response, 'now marked correct')

    def test_an_edit_that_does_not_change_grading_re_marks_nothing(self):
        """The fingerprint gate.

        A typo fixed in the stem used to re-run today's grader over every
        answer ever given to the question — so where the grader had improved
        since, marks moved on a save nobody meant as a correction.
        """
        question = self.question(
            text='What is 1/2 + 1/4?', school=None,
            options=(('3/4', True), ('1/4', False)))
        right = question.answers.get(answer_text='3/4')
        wrong = question.answers.get(answer_text='1/4')
        row = self.answer(question, self.students[0], correct=False,
                          option=wrong)

        # Tick asked for, stem corrected, key untouched.
        response = self._save(question, right, wrong,
                              text='What is 1/2 + 1/4 ?')

        self.assertEqual(response.status_code, 200)
        question.refresh_from_db()
        self.assertEqual(question.question_text, 'What is 1/2 + 1/4 ?')
        row.refresh_from_db()
        self.assertFalse(row.is_correct)
        self.assertNotContains(response, 'now marked correct')

    def test_the_tick_arrives_ticked_from_the_leaderboard_only(self):
        """One endpoint serves both pages; ?regrade=1 is what tells them apart."""
        question, _right, _wrong, _row = self._mismarked()
        url = reverse('admin_global_question_edit', args=[question.id])

        from_bank = self.client.get(url)
        from_leaderboard = self.client.get(f'{url}?regrade=1')

        # Read the tick box's own tag: "checked" appears on every ticked option
        # in this form, so searching the whole page would pass either way.
        self.assertFalse(_regrade_input(from_bank).endswith('CHECKED'))
        self.assertTrue(_regrade_input(from_leaderboard).endswith('CHECKED'))
        # The reader is told the size of what they are authorising.
        self.assertContains(from_leaderboard, 'on record marked wrong')

    def test_no_tick_is_offered_for_an_ai_graded_question(self):
        """A tick that cannot do anything would be a promise the page can't keep."""
        question = self.question(text='Explain your reasoning', school=None,
                                 options=(('anything', True),))
        question.validation_type = Question.VALIDATION_AI
        question.save(update_fields=['validation_type'])

        response = self.client.get(
            reverse('admin_global_question_edit', args=[question.id]))

        self.assertNotContains(response, 'regrade_answers')


class GradingFingerprintTests(WrongRateTestBase):

    def test_the_stem_counts_only_where_the_grader_reads_it(self):
        """Pattern questions are graded FROM the stem; everything else is not."""
        from maths.answer_key_regrade import grading_fingerprint

        plain = self.question(text='What is 1/2 + 1/4?',
                              question_type=Question.SHORT_ANSWER,
                              options=(('3/4', True),))
        before = grading_fingerprint(plain)
        plain.question_text = 'What is 1/2 + 1/4 ?'
        plain.save(update_fields=['question_text'])
        self.assertEqual(grading_fingerprint(plain), before)

        pattern = self.question(
            text='Make a pattern that goes up by 5',
            question_type=Question.SHORT_ANSWER,
            options=(('any', True),),
            answer_format=Question.ANSWER_FORMAT_PATTERN)
        before = grading_fingerprint(pattern)
        pattern.question_text = 'Make a pattern that goes up by 7'
        pattern.save(update_fields=['question_text'])
        self.assertNotEqual(grading_fingerprint(pattern), before)

    def test_moving_the_correct_tick_changes_the_fingerprint(self):
        from maths.answer_key_regrade import grading_fingerprint

        question = self.question(options=(('3/4', True), ('1/4', False)))
        before = grading_fingerprint(question)
        question.answers.filter(answer_text='3/4').update(is_correct=False)
        question.answers.filter(answer_text='1/4').update(is_correct=True)

        self.assertNotEqual(grading_fingerprint(question), before)

    def test_a_spec_graded_question_is_not_re_marked_from_its_text(self):
        """The guard that stops marks being handed out by the wrong grader.

        A number-line answer is a payload marked against the question's own
        figure. Read as plain text it happens to match the stored Answer row,
        so a re-mark without this guard would not be correcting anybody — it
        would be awarding a mark nobody earned.
        """
        from maths.answer_key_regrade import grades_from_text

        question = self.question(text='Mark 5 on the number line',
                                 options=(('5', True),),
                                 question_type=Question.NUMBER_LINE)
        row = StudentAnswer.objects.create(
            student=self.students[0], question=question, text_answer='5',
            is_correct=False, attempt_id=uuid.uuid4())

        self.assertFalse(grades_from_text(question))
        self.assertTrue(question.grade_text_answer('5'))   # the trap

        self.assertFalse(regrade_question(question))
        row.refresh_from_db()
        self.assertFalse(row.is_correct)


class WrongRateBandTests(WrongRateTestBase):
    """The counts above the list — how big the problem behind the ten rows is.

    The leaderboard shows ten rows because ten is what a person can act on. But
    ten is also all they can see: a bank with forty always-wrong questions and
    one with eleven look identical on it. The bands are what tells those apart,
    so what they must never do is count a different population from the list
    they head — a retired question, a question nobody has really sat, or one
    whose answers a review has already settled.
    """

    def setUp(self):
        self.client = Client()
        self.client.login(username='rateadmin', password='pass1234')

    def bands(self):
        from maths.question_difficulty import ranked_questions, wrong_rate_bands

        return wrong_rate_bands(ranked_questions()[0])

    def band(self, label):
        for row in self.bands()['bands']:
            if row['label'] == label:
                return row['count']
        raise AssertionError(f'no band labelled {label!r}')

    def test_the_bands_count_past_the_ten_rows_on_show(self):
        for index in range(12):
            self.sit(self.question(text=f'Always wrong {index}'), wrong=6)

        self.assertEqual(len(wrong_rate_rows()), 10)   # the list is still ten
        self.assertEqual(self.band('Always wrong'), 12)
        self.assertEqual(self.bands()['total'], 12)

    def test_each_rate_lands_in_one_band_and_only_one(self):
        self.sit(self.question(text='All six wrong'), wrong=6)          # 100%
        self.sit(self.question(text='Five of six'), wrong=5, right=1)   # 83.3%
        self.sit(self.question(text='Three of six'), wrong=3, right=3)  # 50%
        self.sit(self.question(text='Two of six'), wrong=2, right=4)    # 33.3%
        self.sit(self.question(text='One of eight'), wrong=1, right=7)  # 12.5%

        self.assertEqual(self.band('Always wrong'), 1)
        self.assertEqual(self.band('75–99% wrong'), 1)
        self.assertEqual(self.band('50–74% wrong'), 1)
        self.assertEqual(self.band('25–49% wrong'), 1)
        self.assertEqual(self.band('Under 25% wrong'), 1)
        self.assertEqual(self.bands()['total'], 5)

    def test_a_retired_question_is_left_out_exactly_as_it_is_from_the_list(self):
        self.sit(self.question(text='Still asked'), wrong=6)
        self.sit(self.question(text='Retired', retired_at=timezone.now()),
                 wrong=6)

        self.assertEqual(self.band('Always wrong'), 1)
        self.assertEqual(self.bands()['total'], 1)

    def test_a_question_too_few_children_have_sat_is_not_counted(self):
        self.sit(self.question(text='Four children only'), wrong=4)

        self.assertEqual(self.bands()['total'], 0)

    def test_a_reviewed_question_leaves_the_bands_with_the_list(self):
        """The summary counts what the list ranks, whatever settles it.

        A review settles the answers recorded before it, so a reviewed question
        stops ranking. If it went on being counted here the summary would
        report a problem the list below could never show.
        """
        question = self.question(text='Reviewed away')
        self.sit(question, wrong=6)
        self.assertEqual(self.bands()['total'], 1)

        record_review(question, user=self.superuser,
                      verdict=QuestionReview.VERDICT_CORRECT)

        self.assertEqual(self.bands()['total'], 0)

    def test_the_dashboard_shows_the_counts(self):
        self.sit(self.question(text='On the dashboard'), wrong=6)

        response = self.client.get(reverse('question_health_admin_dashboard'))

        self.assertContains(response, 'wrong-rate-bands')
        self.assertContains(response, 'Always wrong')
        self.assertContains(response, 'questions ranked in all')


class AnswersGivenTests(WrongRateTestBase):
    """What the children actually wrote, next to what the question accepts.

    The rate alone cannot separate a hard question from a question marking a
    correct answer wrong, and reviewing ten 100%-wrong rows that each turn out
    to be worded perfectly is exactly what that gap costs. The evidence that
    separates them is the answers themselves: all seven children typing the
    same thing is the key or the accepted format, not the children.
    """

    def setUp(self):
        self.client = Client()
        self.client.login(username='rateadmin', password='pass1234')

    def row_for(self, question):
        for row in wrong_rate_rows():
            if row['question'].id == question.id:
                return row
        raise AssertionError(f'Q{question.id} is not on the list')

    def typed(self, question, student, text, *, correct=False, when=None):
        row = StudentAnswer.objects.create(
            student=student, question=question, text_answer=text,
            is_correct=correct, attempt_id=uuid.uuid4())
        if when is not None:
            StudentAnswer.objects.filter(pk=row.pk).update(answered_at=when)
        return row

    def test_the_row_shows_what_they_typed_and_how_many_typed_it(self):
        question = self.question(
            text='How much flour was left in each packet?',
            options=(('148 g', True),),
            question_type=Question.SHORT_ANSWER)
        for student in self.students[:6]:
            self.typed(question, student, '148')

        row = self.row_for(question)

        self.assertEqual(row['given'], [{'text': '148', 'count': 6}])
        # And what it would have accepted, which is the other half of the
        # diagnosis: the question is right, the accepted format is not.
        self.assertEqual(row['expected'], ['148 g'])

    def test_answers_are_folded_by_case_and_spacing(self):
        """Twelve children who agree must not read as twelve who disagree."""
        question = self.question(text='Name the shape',
                                 options=(('Hexagon', True),),
                                 question_type=Question.SHORT_ANSWER)
        for index, student in enumerate(self.students[:6]):
            self.typed(question, student,
                       ['hexagon', 'Hexagon', ' hexagon ', 'HEXAGON',
                        'hexagon', 'hexagon'][index])

        row = self.row_for(question)

        self.assertEqual(row['given'], [{'text': 'hexagon', 'count': 6}])

    def test_only_the_commonest_are_shown_and_the_rest_are_counted(self):
        question = self.question(text='Six different guesses',
                                 options=(('7', True),),
                                 question_type=Question.SHORT_ANSWER)
        for index, student in enumerate(self.students[:6]):
            self.typed(question, student, str(index))

        row = self.row_for(question)

        self.assertEqual(len(row['given']), 3)          # GIVEN_TOP_N
        self.assertEqual(row['given_others'], 3)        # said, not hidden

    def test_the_option_a_multiple_choice_child_picked_is_shown(self):
        question = self.question(
            text='666 in expanded form',
            options=(('600 + 60 + 6', False), ('6 + 6 + 6', True)))
        picked = question.answers.get(answer_text='600 + 60 + 6')
        self.sit(question, wrong=6, option=picked)

        row = self.row_for(question)

        self.assertEqual(row['given'], [{'text': '600 + 60 + 6', 'count': 6}])
        self.assertEqual(row['expected'], ['6 + 6 + 6'])

    def test_correct_answers_are_not_listed_among_the_wrong_ones(self):
        question = self.question(text='Mixed results',
                                 options=(('9', True),),
                                 question_type=Question.SHORT_ANSWER)
        for student in self.students[:5]:
            self.typed(question, student, '8')
        for student in self.students[5:8]:
            self.typed(question, student, '9', correct=True)

        row = self.row_for(question)

        self.assertEqual(row['given'], [{'text': '8', 'count': 5}])

    def test_answers_settled_by_a_review_are_not_used_to_explain_a_later_rate(self):
        """The evidence must cover the same answers the percentage does.

        A reviewed question counts only what has happened since. Explaining
        that rate with answers from before the review would be the row citing
        evidence its own number leaves out.
        """
        question = self.question(text='Reviewed, then answered again',
                                 options=(('12', True),),
                                 question_type=Question.SHORT_ANSWER)
        old = timezone.now() - timedelta(days=3)
        for student in self.students[:5]:
            self.typed(question, student, 'before the review', when=old)
        record_review(question, user=self.superuser,
                      verdict=QuestionReview.VERDICT_CORRECT)
        for student in self.students[5:11]:
            self.typed(question, student, 'after the review')

        row = self.row_for(question)

        self.assertEqual(row['given'],
                         [{'text': 'after the review', 'count': 6}])

    def test_a_question_storing_no_accepted_answer_says_so(self):
        question = self.question(text='No key at all', options=())
        self.sit(question, wrong=6)

        row = self.row_for(question)

        self.assertEqual(row['expected'], [])

    def test_the_dashboard_prints_the_evidence(self):
        question = self.question(text='Shown with its answers',
                                 options=(('148 g', True),),
                                 question_type=Question.SHORT_ANSWER)
        for student in self.students[:6]:
            self.typed(question, student, '148')

        response = self.client.get(reverse('question_health_admin_dashboard'))

        self.assertContains(response, 'What they answered')
        self.assertContains(response, 'What it accepts')
        self.assertContains(response, '148 g')
