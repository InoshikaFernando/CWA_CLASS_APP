"""Reported questions, and the human verdict that clears them (CPP-398).

Two halves of one loop. A student reports the question they are actually
looking at, and it becomes unhealthy on the health pages even when every
deterministic check passes it. A super-admin who looks and finds it sound marks
it "Reviewed and correct", and it leaves the list — but only for as long as that
verdict honestly applies.

The suppression rules are what these tests exist to pin. A clearance that
outlived an edit, or survived a second complaint, would be the dashboard
vouching for text nobody read, which is worse than the false positives it was
added to remove.
"""
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from classroom.models import Level, Subject, Topic
from maths.models import (
    Answer, Question, QuestionHealthSnapshot, QuestionReport, QuestionReview)
from maths.question_review import (
    USER_REPORTED, ReviewState, record_review, report_detail)

User = get_user_model()


class ReviewTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            username='reviewadmin', email='ra@test.com', password='pass1234')
        cls.student = User.objects.create_user(
            username='reviewstudent', email='rs@test.com', password='pass1234')

        cls.maths = Subject.objects.create(name='Mathematics', slug='maths-rv')
        cls.y7 = Level.objects.create(level_number=7, display_name='Year 7')
        cls.topic = Topic.objects.create(
            name='Fractions', slug='fractions-rv', subject=cls.maths)

    def _question(self, text='What is 1/2 + 1/4?',
                  options=(('3/4', True), ('1/4', False), ('2/4', False))):
        """A question the deterministic verifier has no objection to."""
        q = Question.objects.create(
            level=self.y7, topic=self.topic, question_text=text,
            question_type='multiple_choice')
        for order, (label, correct) in enumerate(options):
            Answer.objects.create(question=q, answer_text=label,
                                  is_correct=correct, order=order)
        return q

    def _report(self, question, note='This one is wrong'):
        return QuestionReport.objects.create(
            question=question, reported_by=self.student, note=note)

    def _run(self, **params):
        params.setdefault('run', '1')
        return self.client.get(reverse('question_check_admin_dashboard'), params)


class ReviewStateTests(ReviewTestBase):
    """The rules that decide whether a clearance still stands."""

    def test_an_unreported_unreviewed_question_is_neither_open_nor_cleared(self):
        question = self._question()
        state = ReviewState([question.id])
        self.assertEqual(state.open_reports(question), [])
        self.assertFalse(state.is_cleared(question))

    def test_a_report_is_open_until_somebody_reviews_it(self):
        question = self._question()
        self._report(question)
        self.assertEqual(ReviewState([question.id]).report_count(question), 1)

    def test_a_review_answers_the_reports_that_came_before_it(self):
        question = self._question()
        self._report(question)
        record_review(question, user=self.superuser,
                      verdict=QuestionReview.VERDICT_CORRECT)
        state = ReviewState([question.id])
        self.assertEqual(state.open_reports(question), [])
        self.assertTrue(state.is_cleared(question))

    def test_a_report_after_the_review_re_opens_the_question(self):
        """A second, independent complaint is new evidence, not the old one."""
        question = self._question()
        self._report(question)
        review = record_review(question, user=self.superuser,
                               verdict=QuestionReview.VERDICT_CORRECT)
        later = QuestionReport.objects.create(
            question=question, reported_by=self.student, note='Still wrong')
        QuestionReport.objects.filter(pk=later.pk).update(
            created_at=review.reviewed_at + timezone.timedelta(minutes=5))

        state = ReviewState([question.id])
        self.assertEqual(state.report_count(question), 1)
        self.assertFalse(state.is_cleared(question))

    def test_editing_the_question_makes_the_clearance_stale(self):
        question = self._question()
        record_review(question, user=self.superuser,
                      verdict=QuestionReview.VERDICT_CORRECT)
        self.assertTrue(ReviewState([question.id]).is_cleared(question))

        question.question_text = 'What is 1/2 + 1/4, in its simplest form?'
        question.save(update_fields=['question_text', 'updated_at'])
        question.refresh_from_db()

        self.assertFalse(
            ReviewState([question.id]).is_cleared(question),
            'a clearance must not vouch for text edited after it was given')

    def test_a_later_broken_verdict_beats_an_earlier_correct_one(self):
        question = self._question()
        first = record_review(question, user=self.superuser,
                              verdict=QuestionReview.VERDICT_CORRECT)
        second = record_review(question, user=self.superuser,
                               verdict=QuestionReview.VERDICT_BROKEN)
        QuestionReview.objects.filter(pk=second.pk).update(
            reviewed_at=first.reviewed_at + timezone.timedelta(minutes=1))

        self.assertFalse(ReviewState([question.id]).is_cleared(question))

    def test_an_earlier_broken_verdict_does_not_outlive_a_later_correct_one(self):
        question = self._question()
        first = record_review(question, user=self.superuser,
                              verdict=QuestionReview.VERDICT_BROKEN)
        second = record_review(question, user=self.superuser,
                               verdict=QuestionReview.VERDICT_CORRECT)
        QuestionReview.objects.filter(pk=second.pk).update(
            reviewed_at=first.reviewed_at + timezone.timedelta(minutes=1))

        self.assertTrue(ReviewState([question.id]).is_cleared(question))

    def test_record_review_snapshots_the_content_version(self):
        """Without it the review never goes stale, so it never stops vouching."""
        question = self._question()
        review = record_review(question, user=self.superuser,
                               verdict=QuestionReview.VERDICT_CORRECT)
        self.assertEqual(review.question_updated_at, question.updated_at)
        self.assertFalse(review.is_stale)

    def test_state_for_one_batch_ignores_other_questions(self):
        reported, other = self._question(), self._question(text='2 + 2?')
        self._report(reported)
        state = ReviewState([other.id])
        self.assertEqual(state.report_count(other), 0)

    def test_report_detail_names_the_count_and_quotes_the_note(self):
        question = self._question()
        self._report(question, note='the answer was 23 or 23 pencils but why')
        reports = ReviewState([question.id]).open_reports(question)
        detail = report_detail(reports)
        self.assertIn('Reported by a user', detail)
        self.assertIn('23 pencils', detail)

    def test_report_detail_pluralises_for_several_reporters(self):
        question = self._question()
        self._report(question)
        self._report(question)
        reports = ReviewState([question.id]).open_reports(question)
        self.assertIn('Reported by 2 users', report_detail(reports))


class ReportedQuestionsOnTheCheckPageTests(ReviewTestBase):
    """A complaint has to reach the page where questions get fixed."""

    def setUp(self):
        self.client.login(username='reviewadmin', password='pass1234')

    def test_a_reported_question_is_listed_even_though_it_verifies_clean(self):
        """The verifier having no objection is why the complaint matters."""
        question = self._question()
        self.assertNotContains(self._run(), f'issue-row-{question.id}')

        self._report(question, note='the answer was 23 or 23 pencils but why')
        response = self._run()
        self.assertContains(response, f'issue-row-{question.id}')
        self.assertContains(response, 'Reported by a user')
        self.assertContains(response, '23 pencils')

    def test_a_reviewed_and_correct_question_leaves_the_list(self):
        question = self._question()
        self._report(question)
        record_review(question, user=self.superuser,
                      verdict=QuestionReview.VERDICT_CORRECT)
        self.assertNotContains(self._run(), f'issue-row-{question.id}')

    def test_clearing_a_verifier_finding_removes_it_too(self):
        """The false positives are the reason this verdict exists."""
        broken = self._question(options=(('3/4', False), ('1/4', False)))
        self.assertContains(self._run(), f'issue-row-{broken.id}')

        record_review(broken, user=self.superuser,
                      verdict=QuestionReview.VERDICT_CORRECT)
        self.assertNotContains(self._run(), f'issue-row-{broken.id}')

    def test_the_page_says_how_many_it_is_not_showing(self):
        """A question that vanishes silently is how a bank reads clean."""
        broken = self._question(options=(('3/4', False), ('1/4', False)))
        record_review(broken, user=self.superuser,
                      verdict=QuestionReview.VERDICT_CORRECT)
        response = self._run()
        self.assertContains(response, 'cleared-note')
        self.assertContains(response, 'not listed')

    def test_a_report_filter_finds_reported_questions(self):
        question = self._question()
        self._report(question)
        response = self._run(problem=USER_REPORTED)
        self.assertContains(response, f'issue-row-{question.id}')

    def test_a_report_filter_excludes_other_findings(self):
        broken = self._question(options=(('3/4', False), ('1/4', False)))
        response = self._run(problem=USER_REPORTED)
        self.assertNotContains(response, f'issue-row-{broken.id}')

    def test_the_reported_code_is_never_advisory(self):
        """A student saying they were marked wrong is not a presentation nit."""
        from maths.views_admin import ADVISORY_LABELS
        self.assertNotIn(USER_REPORTED, ADVISORY_LABELS)

    def test_a_reported_question_shows_without_ticking_advisory(self):
        question = self._question()
        self._report(question)
        self.assertContains(self._run(), f'issue-row-{question.id}')


class ReviewVerdictActionTests(ReviewTestBase):
    """"Reviewed and correct" as a bulk action on the check page."""

    def setUp(self):
        self.client.login(username='reviewadmin', password='pass1234')
        self.url = reverse('question_bulk_fix_admin_dashboard')

    def _apply(self, action, question, follow=True):
        return self.client.post(self.url, {
            'action': action,
            'question_id': [str(question.id)],
            'next': reverse('question_check_admin_dashboard'),
        }, follow=follow)

    def test_marking_correct_records_the_verdict_and_the_reviewer(self):
        question = self._question()
        self._report(question)
        self._apply('mark_reviewed_correct', question)

        review = QuestionReview.objects.get(question=question)
        self.assertEqual(review.verdict, QuestionReview.VERDICT_CORRECT)
        self.assertEqual(review.reviewed_by, self.superuser)
        self.assertEqual(review.question_updated_at, question.updated_at)

    def test_marking_correct_clears_the_question(self):
        question = self._question()
        self._report(question)
        self._apply('mark_reviewed_correct', question)
        self.assertTrue(ReviewState([question.id]).is_cleared(question))

    def test_marking_broken_keeps_the_question_listed(self):
        question = self._question()
        self._report(question)
        self._apply('mark_reviewed_broken', question)

        self.assertEqual(QuestionReview.objects.get(question=question).verdict,
                         QuestionReview.VERDICT_BROKEN)
        self.assertFalse(ReviewState([question.id]).is_cleared(question))

    def test_the_success_message_does_not_claim_a_fix(self):
        """Nothing about the question changed — a person's reading was recorded."""
        question = self._question()
        response = self._apply('mark_reviewed_correct', question)
        body = response.content.decode()
        self.assertIn('reviewed', body)
        self.assertNotIn('1 question fixed', body)

    def test_clearing_an_already_cleared_question_does_not_stack_rows(self):
        question = self._question()
        self._apply('mark_reviewed_correct', question)
        self._apply('mark_reviewed_correct', question)
        self.assertEqual(QuestionReview.objects.filter(question=question).count(), 1)

    def test_a_question_edited_since_can_be_cleared_again(self):
        question = self._question()
        self._apply('mark_reviewed_correct', question)

        question.question_text = 'Reworded'
        question.save(update_fields=['question_text', 'updated_at'])
        self._apply('mark_reviewed_correct', question)

        self.assertEqual(QuestionReview.objects.filter(question=question).count(), 2)

    def test_the_verdict_is_written_to_the_audit_log(self):
        from audit.models import AuditLog

        question = self._question()
        self._apply('mark_reviewed_correct', question)
        self.assertTrue(
            AuditLog.objects.filter(
                action='bulk_fix_mark_reviewed_correct').exists())

    def test_automatic_fixing_never_records_a_verdict(self):
        """A sweep saying "reviewed and correct" would be nobody's judgement."""
        from maths.views_admin import MANUAL_FIXES, auto_fix_sequence
        self.assertFalse(set(auto_fix_sequence({USER_REPORTED})) & MANUAL_FIXES)
        self.assertEqual(auto_fix_sequence({USER_REPORTED}), [])

    def test_auto_leaves_a_reported_question_to_a_person(self):
        question = self._question()
        self._report(question)
        self._apply('auto', question)
        self.assertFalse(QuestionReview.objects.filter(question=question).exists())

    def test_a_non_superuser_cannot_record_a_verdict(self):
        question = self._question()
        self.client.logout()
        self.client.login(username='reviewstudent', password='pass1234')
        response = self._apply('mark_reviewed_correct', question, follow=False)
        # Not a redirect back to the check page — the superuser gate turned it
        # away before the view ran.
        self.assertNotEqual(
            response.get('Location', ''),
            reverse('question_check_admin_dashboard'))
        self.assertFalse(QuestionReview.objects.filter(question=question).exists())

    def test_an_anonymous_visitor_cannot_record_a_verdict(self):
        question = self._question()
        self.client.logout()
        self._apply('mark_reviewed_correct', question)
        self.assertFalse(QuestionReview.objects.filter(question=question).exists())

    def test_both_verdicts_are_offered_on_the_page(self):
        # The action menu only renders once there is something to act on.
        self._question(options=(('3/4', False), ('1/4', False)))
        response = self.client.get(
            reverse('question_check_admin_dashboard'), {'run': '1'})
        self.assertContains(response, 'mark_reviewed_correct')
        self.assertContains(response, 'Reviewed and correct')
        self.assertContains(response, 'mark_reviewed_broken')


class SnapshotTests(ReviewTestBase):
    """The nightly recorder has to agree with the live page."""

    def test_a_reported_question_counts_as_blocking(self):
        question = self._question()
        self._report(question)
        call_command('record_question_health', quiet=True)

        snapshot = QuestionHealthSnapshot.objects.first()
        self.assertEqual(snapshot.questions_blocking, 1)
        self.assertEqual(snapshot.issue_counts.get(USER_REPORTED), 1)

    def test_a_cleared_question_is_left_out_of_the_counts(self):
        broken = self._question(options=(('3/4', False), ('1/4', False)))
        record_review(broken, user=self.superuser,
                      verdict=QuestionReview.VERDICT_CORRECT)
        call_command('record_question_health', quiet=True)

        snapshot = QuestionHealthSnapshot.objects.first()
        self.assertEqual(snapshot.questions_blocking, 0)
        self.assertEqual(snapshot.questions_cleared, 1)

    def test_a_cleared_question_is_kept_out_of_the_drill_down(self):
        broken = self._question(options=(('3/4', False), ('1/4', False)))
        record_review(broken, user=self.superuser,
                      verdict=QuestionReview.VERDICT_CORRECT)
        call_command('record_question_health', quiet=True)

        snapshot = QuestionHealthSnapshot.objects.first()
        self.assertNotIn(broken.id,
                         [row['id'] for row in snapshot.flagged_questions])

    def test_clearing_a_question_moves_the_headline_number(self):
        """The point of the verdict: a list a reviewer can actually shrink."""
        broken = self._question(options=(('3/4', False), ('1/4', False)))
        call_command('record_question_health', quiet=True)
        before = QuestionHealthSnapshot.objects.first().health_percent

        record_review(broken, user=self.superuser,
                      verdict=QuestionReview.VERDICT_CORRECT)
        call_command('record_question_health', quiet=True)
        after = QuestionHealthSnapshot.objects.first().health_percent

        self.assertGreater(after, before)

    def test_a_cleared_question_reported_again_comes_back(self):
        question = self._question()
        review = record_review(question, user=self.superuser,
                               verdict=QuestionReview.VERDICT_CORRECT)
        report = self._report(question)
        QuestionReport.objects.filter(pk=report.pk).update(
            created_at=review.reviewed_at + timezone.timedelta(minutes=5))

        call_command('record_question_health', quiet=True)
        snapshot = QuestionHealthSnapshot.objects.first()
        self.assertEqual(snapshot.questions_blocking, 1)
        self.assertEqual(snapshot.questions_cleared, 0)

    def test_the_dashboard_shows_what_it_is_not_counting(self):
        broken = self._question(options=(('3/4', False), ('1/4', False)))
        record_review(broken, user=self.superuser,
                      verdict=QuestionReview.VERDICT_CORRECT)
        call_command('record_question_health', quiet=True)

        self.client.login(username='reviewadmin', password='pass1234')
        response = self.client.get(
            reverse('question_health_admin_dashboard'))
        self.assertContains(response, 'cleared-tile')
        self.assertContains(response, 'Cleared by review')
