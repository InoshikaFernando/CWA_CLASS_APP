"""
Tests for the "save partial homework / resume later" feature:
the save-progress AJAX endpoint, draft restore on the take page, draft cleanup
on submit, and the independence of drafts from the attempt cap.
"""

import json

from django.test import Client
from django.urls import reverse

from .models import HomeworkDraft, HomeworkSubmission
from .tests import HomeworkTestBase


class SaveProgressEndpointTest(HomeworkTestBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='student1', password='pass1234')
        self.url = reverse('homework:save_progress', kwargs={'homework_id': self.homework.id})

    def _save(self, answers, time_taken=42):
        return self.client.post(
            self.url,
            data=json.dumps({'answers': answers, 'time_taken_seconds': time_taken}),
            content_type='application/json',
        )

    def test_save_creates_draft(self):
        answers = {f'answer_{self.questions[0].id}': '123'}
        resp = self._save(answers, time_taken=42)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertTrue(body['ok'])

        draft = HomeworkDraft.objects.get(homework=self.homework, student=self.student)
        self.assertEqual(draft.answers_data, answers)
        self.assertEqual(draft.time_taken_seconds, 42)

    def test_second_save_upserts_single_row(self):
        self._save({'answer_1': 'a'}, time_taken=10)
        self._save({'answer_1': 'b', 'answer_2': 'c'}, time_taken=99)

        drafts = HomeworkDraft.objects.filter(homework=self.homework, student=self.student)
        self.assertEqual(drafts.count(), 1)
        draft = drafts.first()
        self.assertEqual(draft.answers_data, {'answer_1': 'b', 'answer_2': 'c'})
        self.assertEqual(draft.time_taken_seconds, 99)

    def test_empty_save_does_not_wipe_existing_answers(self):
        # A stray heartbeat from a second tab / freshly-reloaded page can POST an
        # empty form; it must NOT erase a good draft.
        self._save({'answer_1': 'a', 'answer_2': 'b'}, time_taken=120)
        resp = self._save({}, time_taken=130)
        self.assertEqual(resp.status_code, 200)

        draft = HomeworkDraft.objects.get(homework=self.homework, student=self.student)
        self.assertEqual(draft.answers_data, {'answer_1': 'a', 'answer_2': 'b'})
        # The timer still advances on a no-op save.
        self.assertEqual(draft.time_taken_seconds, 130)

    def test_partial_save_merges_rather_than_replaces(self):
        # A smaller payload (e.g. a stale tab that only knows some answers) must
        # only add to / update the draft, never drop keys it didn't send.
        self._save({'answer_1': 'a', 'answer_2': 'b'}, time_taken=50)
        self._save({'answer_1': 'z'}, time_taken=60)

        draft = HomeworkDraft.objects.get(homework=self.homework, student=self.student)
        self.assertEqual(draft.answers_data, {'answer_1': 'z', 'answer_2': 'b'})

    def test_stale_save_does_not_rewind_timer(self):
        self._save({'answer_1': 'a'}, time_taken=300)
        self._save({'answer_1': 'a'}, time_taken=10)

        draft = HomeworkDraft.objects.get(homework=self.homework, student=self.student)
        self.assertEqual(draft.time_taken_seconds, 300)

    def test_save_does_not_create_submission_or_consume_attempt(self):
        self._save({'answer_1': 'a'})
        self.assertEqual(
            HomeworkSubmission.objects.filter(homework=self.homework, student=self.student).count(),
            0,
        )
        self.assertEqual(
            HomeworkSubmission.get_attempt_count(self.homework, self.student), 0
        )

    def test_save_allowed_at_attempt_cap(self):
        # Burn both attempts via real submissions, then confirm a draft can still
        # be saved — a draft never becomes a submission on its own, so it can't
        # exceed the cap.
        take_url = reverse('homework:student_take', kwargs={'homework_id': self.homework.id})
        for _ in range(self.homework.max_attempts):
            data = {'time_taken_seconds': '5'}
            for q in self.questions:
                data[f'answer_{q.id}'] = str(q.answers.get(is_correct=True).id)
            self.client.post(take_url, data)

        resp = self._save({'answer_1': 'a'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['ok'])

    def test_bad_json_rejected(self):
        resp = self.client.post(self.url, data='not-json', content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_requires_login(self):
        self.client.logout()
        resp = self._save({'answer_1': 'a'})
        # LoginRequiredMixin redirects anonymous users to the login page.
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(HomeworkDraft.objects.exists())


class DraftRestoreAndCleanupTest(HomeworkTestBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='student1', password='pass1234')
        self.take_url = reverse('homework:student_take', kwargs={'homework_id': self.homework.id})

    def _make_draft(self, answers, time_taken=77):
        return HomeworkDraft.objects.create(
            homework=self.homework, student=self.student,
            answers_data=answers, time_taken_seconds=time_taken,
        )

    def test_take_get_embeds_saved_answers_and_time(self):
        answers = {f'answer_{self.questions[0].id}': '321'}
        self._make_draft(answers, time_taken=77)

        resp = self.client.get(self.take_url)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        # The saved answer JSON is embedded for the restore script…
        self.assertIn('hw-draft-answers', html)
        self.assertIn('321', html)
        # …and the elapsed time is handed to the timer.
        self.assertIn('data-draft-time="77"', html)

    def test_take_get_without_draft_has_empty_payload(self):
        resp = self.client.get(self.take_url)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('data-draft-time="0"', resp.content.decode())

    def test_submit_deletes_draft(self):
        self._make_draft({f'answer_{self.questions[0].id}': 'x'})
        self.assertTrue(HomeworkDraft.objects.filter(student=self.student).exists())

        data = {'time_taken_seconds': '30'}
        for q in self.questions:
            data[f'answer_{q.id}'] = str(q.answers.get(is_correct=True).id)
        resp = self.client.post(self.take_url, data)

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            HomeworkSubmission.objects.filter(homework=self.homework, student=self.student).count(),
            1,
        )
        self.assertFalse(
            HomeworkDraft.objects.filter(homework=self.homework, student=self.student).exists()
        )

    def test_draft_is_per_student(self):
        # student1's draft must not leak into student2's submit cleanup.
        self._make_draft({'answer_1': 'a'})
        other = Client()
        other.login(username='student2', password='pass1234')
        data = {'time_taken_seconds': '5'}
        for q in self.questions:
            data[f'answer_{q.id}'] = str(q.answers.get(is_correct=True).id)
        other.post(self.take_url, data)

        # student1's draft survives student2 submitting.
        self.assertTrue(
            HomeworkDraft.objects.filter(homework=self.homework, student=self.student).exists()
        )


class DraftStudentListTest(HomeworkTestBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='student1', password='pass1234')
        self.url = reverse('homework:student_list')

    def test_resume_shown_when_draft_exists(self):
        HomeworkDraft.objects.create(
            homework=self.homework, student=self.student,
            answers_data={'answer_1': 'a'}, time_taken_seconds=10,
        )
        resp = self.client.get(self.url)
        html = resp.content.decode()
        self.assertIn('Resume', html)
        self.assertIn('In progress', html)

    def test_no_resume_without_draft(self):
        resp = self.client.get(self.url)
        self.assertNotIn('>Resume<', resp.content.decode())
