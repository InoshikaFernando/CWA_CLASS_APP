"""Progress art on the homework take page.

The headline requirement for homework is *resume*: a student saves a paper
half-finished and picks it up the next day with the drawing exactly where they
left it. That works by splitting the state in two —

* **how much is drawn** is counted from the saved draft on every load, so it
  needs no storing and can never drift from the answers;
* **which picture it is** IS stored, on the draft, because that is the one bit
  that cannot be re-derived safely — re-picking it would swap the drawing under
  a student the moment the catalogue changed.

These tests hold both halves of that down.
"""

import json

from django.test import Client
from django.urls import reverse

from classroom import progress_art
from .models import HomeworkDraft
from .tests import HomeworkTestBase


class TakePagePanelTest(HomeworkTestBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='student1', password='pass1234')
        self.url = reverse('homework:student_take', kwargs={'homework_id': self.homework.id})

    def _art(self, response):
        return response.context['progress_art']

    def test_panel_is_rendered_with_the_question_total(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        art = self._art(resp)
        self.assertEqual(art['total'], 5)
        self.assertEqual(art['done'], 0)
        self.assertContains(resp, 'data-progress-art')

    def test_each_question_block_is_an_answer_group(self):
        # The live count on this page works by counting `data-pa-group` blocks;
        # without the attribute the drawing would sit still while the student
        # worked and only catch up on reload.
        resp = self.client.get(self.url)
        self.assertEqual(resp.content.decode().count('data-pa-group'), 5)

    def test_progress_is_counted_from_the_saved_draft(self):
        HomeworkDraft.objects.create(
            homework=self.homework, student=self.student,
            answers_data={
                f'answer_{self.questions[0].id}': '1',
                f'answer_{self.questions[1].id}': '2',
            },
        )
        art = self._art(self.client.get(self.url))
        self.assertEqual(art['done'], 2)

    def test_an_untouched_widget_skeleton_is_not_progress(self):
        # draw-on-grid and friends autosave `{"segments": []}` before anything
        # is drawn. Counting it would hand out picture for no work done.
        HomeworkDraft.objects.create(
            homework=self.homework, student=self.student,
            answers_data={f'answer_{self.questions[0].id}': '{"segments": []}'},
        )
        art = self._art(self.client.get(self.url))
        self.assertEqual(art['done'], 0)

    def test_answered_questions_are_flagged_for_the_template(self):
        HomeworkDraft.objects.create(
            homework=self.homework, student=self.student,
            answers_data={f'answer_{self.questions[2].id}': '7'},
        )
        resp = self.client.get(self.url)
        flags = [item['is_answered'] for item in resp.context['items']]
        self.assertEqual(flags, [False, False, True, False, False])

    def test_the_picture_does_not_change_between_visits(self):
        first = self._art(self.client.get(self.url))['key']
        for _ in range(3):
            self.assertEqual(self._art(self.client.get(self.url))['key'], first)

    def test_a_stored_picture_is_kept_even_if_it_is_off_tier(self):
        """The resume guarantee. A student half-way through must keep their
        drawing even if the homework shrinks, or the catalogue gains entries
        that would now be picked instead."""
        HomeworkDraft.objects.create(
            homework=self.homework, student=self.student,
            answers_data={}, art_picture_key='city',
        )
        self.assertEqual(self._art(self.client.get(self.url))['key'], 'city')

    def test_a_retired_picture_key_falls_back_rather_than_blanking(self):
        HomeworkDraft.objects.create(
            homework=self.homework, student=self.student,
            answers_data={}, art_picture_key='no-such-picture',
        )
        art = self._art(self.client.get(self.url))
        self.assertIn(art['key'], progress_art.PICTURES)

    def test_two_students_can_get_different_pictures(self):
        mine = self._art(self.client.get(self.url))['key']
        other = Client()
        other.login(username='student2', password='pass1234')
        theirs = other.get(self.url).context['progress_art']['key']
        # Not necessarily different (the tier is small), but both must be real.
        self.assertIn(mine, progress_art.PICTURES)
        self.assertIn(theirs, progress_art.PICTURES)


class SaveProgressPinsThePictureTest(HomeworkTestBase):
    def setUp(self):
        self.client = Client()
        self.client.login(username='student1', password='pass1234')
        self.take_url = reverse('homework:student_take', kwargs={'homework_id': self.homework.id})
        self.save_url = reverse('homework:save_progress', kwargs={'homework_id': self.homework.id})

    def _save(self, answers):
        return self.client.post(
            self.save_url,
            data=json.dumps({'answers': answers, 'time_taken_seconds': 5}),
            content_type='application/json',
        )

    def test_first_save_stores_a_picture_key(self):
        self._save({f'answer_{self.questions[0].id}': '1'})
        draft = HomeworkDraft.objects.get(homework=self.homework, student=self.student)
        self.assertIn(draft.art_picture_key, progress_art.PICTURES)

    def test_the_stored_key_matches_what_the_take_page_showed(self):
        shown = self.client.get(self.take_url).context['progress_art']['key']
        self._save({f'answer_{self.questions[0].id}': '1'})
        draft = HomeworkDraft.objects.get(homework=self.homework, student=self.student)
        self.assertEqual(draft.art_picture_key, shown)

    def test_later_saves_do_not_reroll_the_picture(self):
        self._save({f'answer_{self.questions[0].id}': '1'})
        draft = HomeworkDraft.objects.get(homework=self.homework, student=self.student)
        draft.art_picture_key = 'castle'
        draft.save(update_fields=['art_picture_key'])

        self._save({f'answer_{self.questions[1].id}': '2'})
        draft.refresh_from_db()
        self.assertEqual(draft.art_picture_key, 'castle')

    def test_a_client_supplied_key_is_ignored(self):
        """The key is derived server-side on purpose: accepting one from the
        page would let a student reroll until they liked the drawing, and would
        defeat the point of pinning it at all."""
        self.client.post(
            self.save_url,
            data=json.dumps({
                'answers': {f'answer_{self.questions[0].id}': '1'},
                'time_taken_seconds': 5,
                'art_picture_key': 'city',
            }),
            content_type='application/json',
        )
        draft = HomeworkDraft.objects.get(homework=self.homework, student=self.student)
        self.assertNotEqual(draft.art_picture_key, 'city')

    def test_resume_continues_the_same_drawing(self):
        """The end-to-end promise: save two answers today, come back tomorrow,
        and both the picture and how much of it is drawn are still right."""
        self._save({
            f'answer_{self.questions[0].id}': '1',
            f'answer_{self.questions[1].id}': '2',
        })
        stored = HomeworkDraft.objects.get(
            homework=self.homework, student=self.student).art_picture_key

        fresh = Client()
        fresh.login(username='student1', password='pass1234')
        art = fresh.get(self.take_url).context['progress_art']
        self.assertEqual(art['key'], stored)
        self.assertEqual(art['done'], 2)
        self.assertEqual(art['total'], 5)
