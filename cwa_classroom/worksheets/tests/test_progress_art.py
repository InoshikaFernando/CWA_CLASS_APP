"""Progress art on the worksheet session page.

A worksheet session is answered one question per page and is explicitly
resumable — the view already finds the first unanswered question and counts the
rest. So the drawing needs nothing new to resume: `answered_count` is the
progress. The only thing worth storing is WHICH picture, pinned on the
submission so a sheet finished over two afternoons is the same drawing both
times.
"""

from django.urls import reverse

from classroom import progress_art
from classroom.models import Level
from maths.models import Answer as MathsAnswer
from worksheets.models import (
    Worksheet, WorksheetAssignment, WorksheetQuestion, WorksheetStudentAnswer,
    WorksheetSubmission,
)
from worksheets.tests.test_views import SessionDispatchTestBase


class WorksheetProgressArtTest(SessionDispatchTestBase):

    def _worksheet(self, question_count=6, level=None):
        """A worksheet of *question_count* MCQs, assigned to the test class."""
        ws = Worksheet.objects.create(
            school=self.school, name='Art Worksheet', original_filename='',
            pdf_file=None, created_by=self.owner, level=level,
        )
        questions = []
        for i in range(question_count):
            q = self._make_question(question_text=f'Art Q{i + 1}')
            MathsAnswer.objects.create(
                question=q, answer_text='Right', is_correct=True, order=0)
            WorksheetQuestion.objects.create(
                worksheet=ws, question=q, subject_slug='mathematics',
                content_id=q.pk, order=i + 1,
            )
            questions.append(q)
        ws.refresh_question_count()
        assignment = WorksheetAssignment.objects.create(
            worksheet=ws, classroom=self.classroom, assigned_by=self.owner,
        )
        return assignment, questions

    def _answer(self, submission, question):
        WorksheetStudentAnswer.objects.create(
            submission=submission, question=question,
            subject_slug='mathematics', content_id=question.pk,
            is_correct=True, points_earned=1.0,
        )

    def _session(self, assignment):
        self.client.force_login(self.student)
        return self.client.get(reverse('worksheets:session', args=[assignment.pk]))

    # ── the panel ────────────────────────────────────────────────────────

    def test_panel_is_rendered_with_the_question_total(self):
        assignment, _ = self._worksheet(question_count=6)
        resp = self._session(assignment)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['progress_art']['total'], 6)
        self.assertEqual(resp.context['progress_art']['done'], 0)
        self.assertContains(resp, 'data-progress-art')

    def test_progress_follows_the_answers_already_recorded(self):
        assignment, questions = self._worksheet(question_count=6)
        resp = self._session(assignment)           # creates the submission
        submission = WorksheetSubmission.objects.get(
            assignment=assignment, student=self.student)
        self._answer(submission, questions[0])
        self._answer(submission, questions[1])

        resp = self._session(assignment)
        self.assertEqual(resp.context['progress_art']['done'], 2)

    def test_the_question_count_sets_the_tier(self):
        """A 6-question sheet earns a simple picture; a 90-question one earns
        the most detailed tier. That proportionality is the point of tiering."""
        short, _ = self._worksheet(question_count=6)
        self.assertEqual(
            progress_art.get(self._session(short).context['progress_art']['key']).tier,
            progress_art.TIER_SIMPLE,
        )
        long_sheet, _ = self._worksheet(question_count=90)
        self.assertEqual(
            progress_art.get(self._session(long_sheet).context['progress_art']['key']).tier,
            progress_art.TIER_EPIC,
        )

    # ── pinning the choice ───────────────────────────────────────────────

    def test_the_picture_is_pinned_on_the_submission(self):
        assignment, _ = self._worksheet()
        shown = self._session(assignment).context['progress_art']['key']
        submission = WorksheetSubmission.objects.get(
            assignment=assignment, student=self.student)
        self.assertEqual(submission.art_picture_key, shown)

    def test_a_resumed_session_continues_the_same_picture(self):
        assignment, questions = self._worksheet()
        self._session(assignment)
        submission = WorksheetSubmission.objects.get(
            assignment=assignment, student=self.student)
        submission.art_picture_key = 'castle'       # pretend yesterday chose this
        submission.save(update_fields=['art_picture_key'])
        self._answer(submission, questions[0])

        art = self._session(assignment).context['progress_art']
        self.assertEqual(art['key'], 'castle')
        self.assertEqual(art['done'], 1)

    def test_a_retired_picture_key_is_replaced_rather_than_blanking_the_panel(self):
        assignment, _ = self._worksheet()
        self._session(assignment)
        submission = WorksheetSubmission.objects.get(
            assignment=assignment, student=self.student)
        submission.art_picture_key = 'gone-from-the-catalogue'
        submission.save(update_fields=['art_picture_key'])

        art = self._session(assignment).context['progress_art']
        self.assertIn(art['key'], progress_art.PICTURES)
        submission.refresh_from_db()
        self.assertEqual(submission.art_picture_key, art['key'])

    # ── banding by year ──────────────────────────────────────────────────

    def test_the_worksheets_own_level_decides_the_band(self):
        """A Year 6 class can be set a Year 2 sheet. The sheet's level is the
        better guide to what the student is working at, so it wins."""
        year2 = Level.objects.get_or_create(
            level_number=2, defaults={'display_name': 'Year 2'})[0]
        assignment, _ = self._worksheet(question_count=8, level=year2)
        key = self._session(assignment).context['progress_art']['key']
        self.assertIn(
            progress_art.get(key).band,
            (progress_art.BAND_JUNIOR, progress_art.BAND_ANY),
        )

    def test_a_senior_sheet_is_never_given_a_junior_only_picture(self):
        year8 = Level.objects.get_or_create(
            level_number=8, defaults={'display_name': 'Year 8'})[0]
        assignment, _ = self._worksheet(question_count=8, level=year8)
        key = self._session(assignment).context['progress_art']['key']
        self.assertNotEqual(progress_art.get(key).band, progress_art.BAND_JUNIOR)
