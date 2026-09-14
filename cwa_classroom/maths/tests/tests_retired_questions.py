"""Retiring a question withdraws it without rewriting history (CPP-410).

Three questions from CPP-406 are unanswerable and cannot be repaired without
their source worksheets. Deleting them was the only lever the app had, and
every FK to ``maths.Question`` is ``on_delete=CASCADE`` — so removing one
would have destroyed every homework, worksheet and quiz answer ever given to
it, rewriting completed homework to tidy up a missing diagram.

Retirement is the lever that was missing. The two halves that matter:

* a withdrawn question stops being served — including inside homework that
  already contains it, because it is withdrawn precisely because it is broken;
* nothing about the past moves. No answer row is touched, and ``score`` /
  ``total_questions`` on a finished submission stay exactly as recorded.
"""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from classroom.models import ClassRoom, Level, School, Subject, Topic
from maths.models import Answer, Question

User = get_user_model()


class RetirementFieldTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=962, defaults={'display_name': 'retire fixture'})

    def _q(self, text='Find the value of x.'):
        return Question.objects.create(
            level=self.level, question_text=text,
            question_type=Question.MULTIPLE_CHOICE, difficulty=1, points=1)

    def test_a_new_question_is_live(self):
        q = self._q()
        self.assertFalse(q.is_retired)
        self.assertIsNone(q.retired_at)

    def test_retiring_records_when_and_why(self):
        q = self._q()
        q.retire('No diagram; cannot be answered (CPP-406).')
        q.refresh_from_db()

        self.assertTrue(q.is_retired)
        self.assertIsNotNone(q.retired_at)
        self.assertIn('CPP-406', q.retired_reason)

    def test_unretiring_puts_it_back(self):
        q = self._q()
        q.retire('temporarily broken')
        q.unretire()
        q.refresh_from_db()

        self.assertFalse(q.is_retired)
        self.assertEqual(q.retired_reason, '')

    def test_the_queryset_splits_live_from_retired(self):
        live, gone = self._q('live one'), self._q('withdrawn one')
        gone.retire('broken')

        live_ids = set(Question.objects.live().values_list('id', flat=True))
        retired_ids = set(Question.objects.retired().values_list('id', flat=True))

        self.assertIn(live.id, live_ids)
        self.assertNotIn(gone.id, live_ids)
        self.assertIn(gone.id, retired_ids)

    def test_the_default_manager_still_sees_retired_questions(self):
        """The admin is where a retired question gets repaired.

        Filtering ``get_queryset`` would fail closed for selection, but it
        would also make a withdrawn question unreachable in the admin — and
        then the only way to fix one would be a shell.
        """
        q = self._q()
        q.retire('broken')
        self.assertTrue(Question.objects.filter(pk=q.pk).exists())


class SelectionPathTests(TestCase):
    """Every path that puts a question in front of a student."""

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Retire School')
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', defaults={'name': 'Mathematics'})
        cls.level = Level.objects.create(level_number=961, display_name='Y-retire')
        cls.topic = Topic.objects.create(
            name='Retire Topic', slug='retire-topic', subject=cls.subject)
        cls.classroom = ClassRoom.objects.create(name='R1', school=cls.school)
        cls.classroom.levels.add(cls.level)

    def _q(self, text):
        q = Question.objects.create(
            level=self.level, topic=self.topic, question_text=text,
            question_type=Question.MULTIPLE_CHOICE, difficulty=1, points=1)
        Answer.objects.create(question=q, answer_text='4', is_correct=True, order=0)
        Answer.objects.create(question=q, answer_text='5', is_correct=False, order=1)
        return q

    def test_homework_generation_does_not_pick_a_retired_question(self):
        from classroom.subject_registry import get as get_plugin

        live = self._q('live question')
        gone = self._q('withdrawn question')
        gone.retire('unanswerable')

        picked = get_plugin('mathematics').pick_homework_items(
            self.classroom, [self.topic.id], n=10)
        picked_ids = {getattr(p, 'id', p) for p in picked}

        self.assertIn(live.id, picked_ids)
        self.assertNotIn(gone.id, picked_ids)

    def test_the_teachers_topic_count_matches_the_pool(self):
        """A count that includes withdrawn questions promises what it cannot serve."""
        from classroom.subject_registry import get as get_plugin

        self._q('live question')
        gone = self._q('withdrawn question')
        gone.retire('unanswerable')

        counts = get_plugin('mathematics').topic_content_counts(
            self.classroom, [self.topic.id])

        self.assertEqual(counts.get(self.topic.id), 1)


class TakePageTests(TestCase):
    """A withdrawn question must stop reaching children immediately."""

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Take School')
        cls.level = Level.objects.create(level_number=960, display_name='Y-take')
        cls.classroom = ClassRoom.objects.create(name='T1', school=cls.school)
        cls.teacher = User.objects.create_user(
            username='retireteacher', password='p', email='rt@test.com')

    def _homework_with(self, *questions):
        from homework.models import Homework, HomeworkQuestion

        hw = Homework.objects.create(
            classroom=self.classroom, created_by=self.teacher, title='HW',
            homework_type='topic', num_questions=len(questions),
            due_date=timezone.now() + timedelta(days=1))
        for order, q in enumerate(questions):
            HomeworkQuestion.objects.create(homework=hw, question=q, order=order)
        return hw

    def _q(self, text):
        return Question.objects.create(
            level=self.level, question_text=text,
            question_type=Question.SHORT_ANSWER, difficulty=1, points=1)

    def test_a_retired_question_is_skipped_even_inside_existing_homework(self):
        from homework.views import live_homework_questions

        live, gone = self._q('live'), self._q('withdrawn')
        homework = self._homework_with(live, gone)
        gone.retire('unanswerable')

        served = live_homework_questions(homework)

        self.assertEqual([hwq.question_id for hwq in served], [live.id])

    def test_the_homework_row_itself_is_kept(self):
        """What a homework contained is a fact about the past."""
        live, gone = self._q('live'), self._q('withdrawn')
        homework = self._homework_with(live, gone)
        gone.retire('unanswerable')

        self.assertEqual(homework.homework_questions.count(), 2)

    def test_unretiring_serves_it_again(self):
        from homework.views import live_homework_questions

        live, gone = self._q('live'), self._q('withdrawn')
        homework = self._homework_with(live, gone)
        gone.retire('broken')
        gone.unretire()

        served = live_homework_questions(homework)
        self.assertEqual(len(served), 2)


class PastMarksAreUntouchedTests(TestCase):
    """The whole reason retirement exists rather than deletion."""

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Marks School')
        cls.level = Level.objects.create(level_number=959, display_name='Y-marks')
        cls.classroom = ClassRoom.objects.create(name='M1', school=cls.school)
        cls.teacher = User.objects.create_user(
            username='marksteacher', password='p', email='mt@test.com')
        cls.student = User.objects.create_user(
            username='marksstudent', password='p', email='ms@test.com')

    def test_retiring_deletes_no_answer_and_moves_no_mark(self):
        from homework.models import (
            Homework, HomeworkQuestion, HomeworkStudentAnswer,
            HomeworkSubmission,
        )

        q = Question.objects.create(
            level=self.level, question_text='The table shows... solve for k.',
            question_type=Question.SHORT_ANSWER, difficulty=1, points=1)
        hw = Homework.objects.create(
            classroom=self.classroom, created_by=self.teacher, title='Exam',
            homework_type='topic', num_questions=2,
            due_date=timezone.now() + timedelta(days=1))
        HomeworkQuestion.objects.create(homework=hw, question=q, order=0)
        submission = HomeworkSubmission.objects.create(
            homework=hw, student=self.student, score=1, total_questions=2)
        answer = HomeworkStudentAnswer.objects.create(
            submission=submission, question=q, text_answer='0.5',
            is_correct=False)

        q.retire('No table attached; unanswerable (CPP-406).')

        answer.refresh_from_db()
        submission.refresh_from_db()
        self.assertTrue(
            HomeworkStudentAnswer.objects.filter(pk=answer.pk).exists(),
            'retiring must never delete a child\'s answer')
        self.assertEqual(answer.text_answer, '0.5')
        self.assertEqual(submission.score, 1)
        self.assertEqual(submission.total_questions, 2)
        self.assertEqual(submission.percentage, 50)

    def test_the_result_page_shows_it_greyed_rather_than_hiding_it(self):
        from django.template.loader import render_to_string
        from homework.models import (
            Homework, HomeworkStudentAnswer, HomeworkSubmission)

        q = Question.objects.create(
            level=self.level, question_text='Solve for k.',
            question_type=Question.SHORT_ANSWER, difficulty=1, points=1)
        hw = Homework.objects.create(
            classroom=self.classroom, created_by=self.teacher, title='Exam',
            homework_type='topic', num_questions=1,
            due_date=timezone.now() + timedelta(days=1))
        submission = HomeworkSubmission.objects.create(
            homework=hw, student=self.student, score=0, total_questions=1)
        answer = HomeworkStudentAnswer.objects.create(
            submission=submission, question=q, text_answer='0.5',
            is_correct=False)
        q.retire('No table attached.')
        answer.refresh_from_db()

        # The partial reads ``ctx.ans`` and takes the question off it.
        html = render_to_string(
            'homework/partials/_maths_result_item.html', {'ctx': {'ans': answer}})

        self.assertIn('Withdrawn', html)
        self.assertIn('opacity-60', html)          # greyed, not removed
        self.assertIn('Solve for k.', html)        # still readable
        self.assertIn('0.5', html)                 # the child's answer survives


class SelectionPathsAreGuardedTests(TestCase):
    """The guard that replaces filtering-by-default.

    ``live()`` is applied explicitly rather than in ``get_queryset``, so that
    retired questions stay visible in the admin. The cost of that choice is
    that a NEW selection path could forget the call and quietly serve a
    withdrawn question. This test is what makes that a build failure instead.

    If you add a path that chooses questions for a student, add it here.
    """

    SELECTION_SITES = [
        ('maths/plugin.py', 'visible_to_classroom(classroom).live()'),
        ('quiz/views.py', 'global_only().live()'),
    ]

    def test_every_known_selection_site_filters_retired_questions(self):
        from pathlib import Path

        from django.conf import settings

        for path, expected in self.SELECTION_SITES:
            with self.subTest(path):
                source = (Path(settings.BASE_DIR) / path).read_text()
                self.assertIn(
                    expected, source,
                    f'{path} chooses questions for a student but no longer '
                    f'calls .live() — a retired question would be served')

    def test_no_selection_site_selects_without_live(self):
        """Catches a second, unfiltered call appearing beside a filtered one."""
        from pathlib import Path

        from django.conf import settings

        for path, _ in self.SELECTION_SITES:
            source = (Path(settings.BASE_DIR) / path).read_text()
            for lineno, line in enumerate(source.split('\n'), 1):
                if 'visible_to_classroom(classroom)' in line or 'global_only()' in line:
                    if 'def ' in line or line.strip().startswith('#'):
                        continue
                    with self.subTest(f'{path}:{lineno}'):
                        self.assertIn(
                            '.live()', line,
                            f'{path}:{lineno} selects questions without '
                            f'.live():\n    {line.strip()}')
