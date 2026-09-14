"""
CPP-405 — the "Assign to Another Class" screen carries a title field.

One submission fans a homework out to several classes at once, so without a
title field here the only way to rename the copies is to open each one
afterwards. These tests pin the field's behaviour: the copies take the
submitted title, a blank or absent field still falls back to the original (the
screen's older callers post no title at all), an over-long title is refused
rather than truncated, and the "already assigned" duplicate guard follows the
title being assigned rather than the original.
"""

from datetime import timedelta

from django.test import Client
from django.urls import reverse
from django.utils import timezone

from classroom.models import ClassRoom, ClassTeacher

from .models import Homework, HomeworkQuestion
from .tests import HomeworkTestBase


class AssignToClassTitleTest(HomeworkTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='teacher1', password='pass1234')

        self.classroom2 = ClassRoom.objects.create(
            name='Year 6 Maths', code='HWTITLE02', school=self.school,
        )
        ClassTeacher.objects.create(classroom=self.classroom2, teacher=self.teacher)

        self.classroom3 = ClassRoom.objects.create(
            name='Year 7 Maths', code='HWTITLE03', school=self.school,
        )
        ClassTeacher.objects.create(classroom=self.classroom3, teacher=self.teacher)

        self.homework = Homework.objects.create(
            classroom=self.classroom, created_by=self.teacher,
            title='Fractions Week 1', homework_type='topic', num_questions=3,
            due_date=timezone.now() + timedelta(days=7),
        )
        for i, q in enumerate(self.questions[:3]):
            HomeworkQuestion.objects.create(homework=self.homework, question=q, order=i)

        self.url = reverse(
            'homework:assign_to_class', kwargs={'homework_id': self.homework.id}
        )

    def _assign(self, classrooms, **extra):
        data = {'classroom_ids': [str(c.id) for c in classrooms]}
        data.update(extra)
        return self.client.post(self.url, data)

    # -- the field itself ---------------------------------------------------

    def test_form_offers_a_title_field_prefilled_with_the_current_title(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="homework_title"')
        self.assertContains(resp, 'value="Fractions Week 1"')

    def test_copies_take_the_submitted_title(self):
        self._assign([self.classroom2], homework_title='Fractions Week 1 — Year 6')

        copy = Homework.objects.get(classroom=self.classroom2)
        self.assertEqual(copy.title, 'Fractions Week 1 — Year 6')
        # The original is untouched.
        self.homework.refresh_from_db()
        self.assertEqual(self.homework.title, 'Fractions Week 1')

    def test_every_selected_class_gets_the_same_new_title(self):
        self._assign([self.classroom2, self.classroom3], homework_title='Renamed HW')

        titles = set(
            Homework.objects
            .filter(classroom__in=[self.classroom2, self.classroom3])
            .values_list('title', flat=True)
        )
        self.assertEqual(titles, {'Renamed HW'})

    def test_renaming_does_not_disturb_the_shared_question_records(self):
        """The point of this screen is a shared grading cache — a rename must
        not fork the question rows onto new PKs."""
        self._assign([self.classroom2], homework_title='Renamed HW')

        copy = Homework.objects.get(classroom=self.classroom2)
        original_qs = set(self.homework.homework_questions.values_list('question_id', flat=True))
        copy_qs = set(copy.homework_questions.values_list('question_id', flat=True))
        self.assertEqual(original_qs, copy_qs)

    # -- fallbacks ----------------------------------------------------------

    def test_absent_title_field_keeps_the_original_title(self):
        """Older callers post only classroom_ids; they must keep working."""
        self._assign([self.classroom2])

        copy = Homework.objects.get(classroom=self.classroom2)
        self.assertEqual(copy.title, 'Fractions Week 1')

    def test_blank_title_keeps_the_original_title(self):
        self._assign([self.classroom2], homework_title='   ')

        copy = Homework.objects.get(classroom=self.classroom2)
        self.assertEqual(copy.title, 'Fractions Week 1')

    def test_title_is_stripped(self):
        self._assign([self.classroom2], homework_title='  Padded Title  ')

        copy = Homework.objects.get(classroom=self.classroom2)
        self.assertEqual(copy.title, 'Padded Title')

    # -- validation ---------------------------------------------------------

    def test_over_long_title_is_refused_not_truncated(self):
        max_length = Homework._meta.get_field('title').max_length
        resp = self._assign([self.classroom2], homework_title='x' * (max_length + 1))

        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Homework.objects.filter(classroom=self.classroom2).exists())
        messages = [str(m) for m in resp.wsgi_request._messages]
        self.assertTrue(
            any('too long' in m for m in messages),
            f'expected a too-long error, got {messages!r}',
        )

    def test_title_at_the_maximum_length_is_accepted(self):
        max_length = Homework._meta.get_field('title').max_length
        title = 'y' * max_length
        self._assign([self.classroom2], homework_title=title)

        copy = Homework.objects.get(classroom=self.classroom2)
        self.assertEqual(copy.title, title)

    # -- duplicate guard ----------------------------------------------------

    def test_same_title_twice_is_still_skipped(self):
        self._assign([self.classroom2], homework_title='Fractions Week 1')
        self._assign([self.classroom2], homework_title='Fractions Week 1')

        self.assertEqual(
            Homework.objects.filter(
                classroom=self.classroom2, title='Fractions Week 1'
            ).count(),
            1,
        )

    def test_a_new_title_may_target_a_class_that_holds_the_original(self):
        """The duplicate guard follows the title being assigned. A class that
        holds 'Fractions Week 1' is not holding 'Fractions Week 1 (Retake)'."""
        self._assign([self.classroom2], homework_title='Fractions Week 1')
        self._assign([self.classroom2], homework_title='Fractions Week 1 (Retake)')

        titles = set(
            Homework.objects.filter(classroom=self.classroom2).values_list('title', flat=True)
        )
        self.assertEqual(titles, {'Fractions Week 1', 'Fractions Week 1 (Retake)'})

    def test_already_assigned_marks_classes_holding_the_current_title(self):
        self._assign([self.classroom2], homework_title='Fractions Week 1')

        resp = self.client.get(self.url)
        self.assertIn(self.classroom2.id, resp.context['already_assigned'])
        self.assertNotIn(self.classroom3.id, resp.context['already_assigned'])

    # -- permissions --------------------------------------------------------

    def test_another_teacher_cannot_rename_and_assign(self):
        self.client.login(username='teacher2', password='pass1234')
        resp = self._assign([self.classroom2], homework_title='Hijacked')

        self.assertEqual(resp.status_code, 404)
        self.assertFalse(Homework.objects.filter(title='Hijacked').exists())

    def test_a_class_the_teacher_does_not_own_is_ignored(self):
        foreign = ClassRoom.objects.create(
            name='Not Mine', code='HWTITLE99', school=self.school,
        )
        self._assign([foreign], homework_title='Renamed HW')

        self.assertFalse(Homework.objects.filter(classroom=foreign).exists())
