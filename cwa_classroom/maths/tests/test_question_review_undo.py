"""Undoing a "Reviewed and correct" verdict given by mistake.

The verdict is one click on a list of ten near-identical rows, and it is a
strong claim: it settles every answer recorded before it and clears the
question from the unhealthy counts. Clicked on the wrong row it used to be
unreachable — the question left the leaderboard, so the only surface that
showed it was the one it had just disappeared from.

What is defended here:

1. Undo must RESTORE the state before the click, not paper over it. A
   counter-verdict would settle the past answers just the same and leave the
   question off the list; only deleting the row brings it back.
2. It must refuse where undoing would be a lie — a verdict somebody has already
   replaced, or one already undone — rather than reporting success.
3. Nothing may vanish silently: the deleted verdict is written to the audit log
   in full before it goes.
"""
import uuid

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from audit.models import AuditLog
from classroom.models import Level, Subject, Topic
from maths.models import Answer, Question, QuestionReview, StudentAnswer
from maths.question_review import record_review, recent_reviews

User = get_user_model()


class ReviewUndoTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            username='undoadmin', email='undo@test.com', password='pass1234')
        cls.subject = Subject.objects.create(name='Mathematics',
                                             slug='mathematics')
        cls.level = Level.objects.create(level_number=7, display_name='Year 7')
        cls.topic = Topic.objects.create(name='Fractions', slug='fractions',
                                         subject=cls.subject)
        cls.students = [
            User.objects.create_user(username=f'undokid{i}',
                                     email=f'uk{i}@test.com', password='pass1234')
            for i in range(8)
        ]

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.superuser)

    # ── fixtures ──────────────────────────────────────────────────────────

    def question(self, text='What is 1/2 + 1/4?'):
        question = Question.objects.create(
            level=self.level, topic=self.topic, question_text=text,
            question_type=Question.MULTIPLE_CHOICE, difficulty=1)
        Answer.objects.create(question=question, answer_text='3/4',
                              is_correct=True, order=0)
        Answer.objects.create(question=question, answer_text='1/4',
                              is_correct=False, order=1)
        return question

    def sit_and_get_wrong(self, question, times=6):
        for student in self.students[:times]:
            StudentAnswer.objects.create(
                student=student, question=question, is_correct=False,
                attempt_id=uuid.uuid4())

    def undo(self, review_id, **kwargs):
        return self.client.post(
            reverse('question_review_undo_admin_dashboard'),
            {'review_id': review_id}, HTTP_HX_REQUEST='true', **kwargs)

    # ── the undo itself ───────────────────────────────────────────────────

    def test_undo_puts_the_question_back_on_the_list(self):
        question = self.question(text='Back on the list after an undo')
        self.sit_and_get_wrong(question)
        review = record_review(question, user=self.superuser,
                               verdict=QuestionReview.VERDICT_CORRECT)

        # It is off the list while the verdict stands.
        panel = self.client.get(reverse('question_health_admin_dashboard'))
        self.assertNotContains(panel, f'wrong-rate-row-{question.id}')

        response = self.undo(review.id)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(QuestionReview.objects.filter(id=review.id).exists())
        # The six answers recorded before the verdict count again, so the
        # question is ranked once more — in the panel that came back, not on
        # some later page load.
        self.assertContains(response, f'wrong-rate-row-{question.id}')
        self.assertContains(response, 'Undone')

    def test_the_deleted_verdict_is_written_to_the_audit_log_first(self):
        question = self.question()
        self.sit_and_get_wrong(question)
        review = record_review(question, user=self.superuser,
                               verdict=QuestionReview.VERDICT_CORRECT,
                               note='misclicked')

        self.undo(review.id)

        entry = AuditLog.objects.get(action='question_review_undone')
        self.assertEqual(entry.detail['question_id'], question.id)
        self.assertEqual(entry.detail['review_id'], review.id)
        self.assertEqual(entry.detail['verdict'],
                         QuestionReview.VERDICT_CORRECT)
        self.assertEqual(entry.detail['reviewed_by_id'], self.superuser.id)
        self.assertEqual(entry.detail['note'], 'misclicked')

    def test_a_needs_fixing_verdict_can_be_undone_too(self):
        """Both verdicts stop the clock, so both are undoable.

        'Needs fixing' settles the answers recorded before it exactly as
        'correct' does (see question_difficulty), so a mistaken one hides the
        evidence just the same.
        """
        question = self.question()
        self.sit_and_get_wrong(question)
        review = record_review(question, user=self.superuser,
                               verdict=QuestionReview.VERDICT_BROKEN)

        response = self.undo(review.id)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(QuestionReview.objects.filter(id=review.id).exists())
        self.assertContains(response, f'wrong-rate-row-{question.id}')

    # ── the refusals ──────────────────────────────────────────────────────

    def test_undoing_twice_says_so_rather_than_looking_like_it_worked(self):
        question = self.question()
        self.sit_and_get_wrong(question)
        review = record_review(question, user=self.superuser,
                               verdict=QuestionReview.VERDICT_CORRECT)
        self.undo(review.id)

        response = self.undo(review.id)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'not there to undo')
        # And no second audit entry claiming a second undo happened.
        self.assertEqual(
            AuditLog.objects.filter(action='question_review_undone').count(), 1)

    def test_a_verdict_somebody_has_already_replaced_is_refused(self):
        """Undo removes a row, so it may only remove the one in force.

        Deleting a superseded verdict would rewrite what a person concluded
        while leaving the verdict actually in force untouched — history lost
        and nothing undone.
        """
        question = self.question()
        self.sit_and_get_wrong(question)
        first = record_review(question, user=self.superuser,
                              verdict=QuestionReview.VERDICT_CORRECT)
        second = record_review(question, user=self.superuser,
                               verdict=QuestionReview.VERDICT_BROKEN)

        response = self.undo(first.id)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'reviewed this question again')
        self.assertTrue(QuestionReview.objects.filter(id=first.id).exists())
        self.assertTrue(QuestionReview.objects.filter(id=second.id).exists())

    def test_an_unknown_review_id_says_so(self):
        response = self.undo(999999)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'not there to undo')

    def test_a_non_superuser_cannot_undo(self):
        question = self.question()
        self.sit_and_get_wrong(question)
        review = record_review(question, user=self.superuser,
                               verdict=QuestionReview.VERDICT_CORRECT)
        client = Client()
        client.force_login(self.students[0])

        response = client.post(
            reverse('question_review_undo_admin_dashboard'),
            {'review_id': review.id})

        self.assertNotEqual(response.status_code, 200)
        self.assertTrue(QuestionReview.objects.filter(id=review.id).exists())

    # ── the strip that offers it ──────────────────────────────────────────

    def test_the_dashboard_lists_the_verdict_with_an_undo_button(self):
        question = self.question(text='Reviewed by mistake')
        self.sit_and_get_wrong(question)
        review = record_review(question, user=self.superuser,
                               verdict=QuestionReview.VERDICT_CORRECT)

        response = self.client.get(
            reverse('question_health_admin_dashboard'))

        self.assertContains(response, 'Just reviewed')
        self.assertContains(response, f'recent-review-{question.id}')
        self.assertContains(response, f'"review_id": "{review.id}"')
        # The question text is there to be re-read, which is the point of the
        # strip: the row it was clicked on has gone.
        self.assertContains(response, 'Reviewed by mistake')

    def test_the_strip_lists_only_the_verdict_that_stands(self):
        question = self.question()
        self.sit_and_get_wrong(question)
        record_review(question, user=self.superuser,
                      verdict=QuestionReview.VERDICT_CORRECT)
        latest = record_review(question, user=self.superuser,
                               verdict=QuestionReview.VERDICT_BROKEN)

        listed = recent_reviews()

        self.assertEqual([r.id for r in listed], [latest.id])

    def test_the_verdict_just_given_can_be_undone_from_what_came_back(self):
        """The round trip the whole feature exists for.

        Mark it reviewed, and the panel that replaces the row must already
        carry the undo for the verdict just recorded — no reload, no hunting.
        """
        question = self.question()
        self.sit_and_get_wrong(question)

        marked = self.client.post(
            reverse('question_reviewed_admin_dashboard'),
            {'question_id': question.id}, HTTP_HX_REQUEST='true')

        review = QuestionReview.objects.get(question=question)
        self.assertNotContains(marked, f'wrong-rate-row-{question.id}')
        self.assertContains(marked, f'"review_id": "{review.id}"')

        undone = self.undo(review.id)
        self.assertContains(undone, f'wrong-rate-row-{question.id}')

    def test_the_notice_that_reports_the_verdict_carries_its_undo(self):
        """Where the row used to be is where the way back belongs.

        The strip at the bottom keeps the undo available afterwards, but the
        moment somebody realises they clicked the wrong row is the moment they
        read this line — ten rows above it.
        """
        question = self.question()
        self.sit_and_get_wrong(question)

        response = self.client.post(
            reverse('question_reviewed_admin_dashboard'),
            {'question_id': question.id}, HTTP_HX_REQUEST='true')

        review = QuestionReview.objects.get(question=question)
        self.assertContains(response, 'wrong-rate-notice-undo')
        body = response.content.decode()
        self.assertIn(f'"review_id": "{review.id}"', body)

    def test_a_failed_review_offers_no_undo_in_its_notice(self):
        response = self.client.post(
            reverse('question_reviewed_admin_dashboard'),
            {'question_id': 99999}, HTTP_HX_REQUEST='true')

        self.assertContains(response, 'nothing was reviewed')
        self.assertNotContains(response, 'wrong-rate-notice-undo')

    def test_the_undo_notice_does_not_offer_a_redo(self):
        """Undo deletes the row, so the id in hand names nothing afterwards.

        A button there would read as "put it back" and answer "that verdict is
        not there to undo" — worse than no button.
        """
        question = self.question()
        self.sit_and_get_wrong(question)
        review = record_review(question, user=self.superuser,
                               verdict=QuestionReview.VERDICT_CORRECT)

        response = self.undo(review.id)

        self.assertContains(response, 'Undone')
        self.assertNotContains(response, 'wrong-rate-notice-undo')

    def test_the_strip_keeps_more_than_one_sitting_of_verdicts(self):
        """Ten was one sitting\'s worth, and the eleventh pushed the first out.

        A reviewer works down the list in one go, and the misclick they want
        back is as likely to be early in that run as late.
        """
        from maths.question_review import RECENT_REVIEW_LIMIT

        self.assertGreaterEqual(RECENT_REVIEW_LIMIT, 25)

        for index in range(12):
            question = self.question(text=f'Reviewed in one sitting {index}')
            self.sit_and_get_wrong(question, times=6)
            record_review(question, user=self.superuser,
                          verdict=QuestionReview.VERDICT_CORRECT)

        listed = recent_reviews()

        self.assertEqual(len(listed), 12)
