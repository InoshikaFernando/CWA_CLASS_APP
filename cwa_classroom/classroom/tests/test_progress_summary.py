"""Unit tests for classroom.progress_summary (report/dashboard aggregates, §12.8)."""

import datetime

from django.utils import timezone

from classroom.models import Topic
from classroom.progress_summary import (
    homework_section, worksheet_section, maths_summary, coding_section, build_summary,
)
from homework.models import Homework, HomeworkSubmission
from maths.models import StudentFinalAnswer, BasicFactsResult
from worksheets.models import Worksheet, WorksheetAssignment, WorksheetSubmission

from .test_e2e_attendance_progress import _BaseAttendanceProgressTest


class ProgressSummaryTest(_BaseAttendanceProgressTest):

    # ----- Homework: summary + selected -----------------------------------

    def _homework(self, title, published=True):
        return Homework.objects.create(
            classroom=self.classroom, created_by=self.teacher_user, title=title,
            due_date=timezone.now() + datetime.timedelta(days=7),
            published_at=timezone.now() if published else None,
            publish_at=None if published else timezone.now() + datetime.timedelta(days=3),
        )

    def test_homework_summary(self):
        hw1 = self._homework('HW1')
        self._homework('HW2')                       # assigned, not done
        self._homework('Draft', published=False)    # not assigned
        HomeworkSubmission.objects.create(
            homework=hw1, student=self.student_user, score=8, total_questions=10, points=80.0,
        )
        s = homework_section(self.student_user, self.classroom)
        self.assertEqual(s['mode'], 'summary')
        self.assertEqual(s['assigned'], 2)
        self.assertEqual(s['completed'], 1)
        self.assertEqual(s['completion_pct'], 50)
        self.assertEqual(s['average_pct'], 80)

    def test_homework_selected(self):
        hw1 = self._homework('Fractions')
        hw2 = self._homework('Decimals')
        HomeworkSubmission.objects.create(
            homework=hw1, student=self.student_user, score=9, total_questions=10, points=90.0,
        )
        s = homework_section(self.student_user, self.classroom, mode='selected',
                             ids=[hw1.id, hw2.id])
        self.assertEqual(s['mode'], 'selected')
        by_title = {i['title']: i for i in s['items']}
        self.assertEqual(by_title['Fractions']['pct'], 90)
        self.assertTrue(by_title['Fractions']['attempted'])
        self.assertFalse(by_title['Decimals']['attempted'])
        self.assertIsNone(by_title['Decimals']['pct'])

    # ----- Worksheets: summary + selected ---------------------------------

    def _worksheet_assignment(self, name):
        ws = Worksheet.objects.create(
            school=self.school, name=name, original_filename=f'{name}.pdf',
        )
        return WorksheetAssignment.objects.create(worksheet=ws, classroom=self.classroom)

    def test_worksheet_summary(self):
        a1 = self._worksheet_assignment('WS1')
        self._worksheet_assignment('WS2')           # assigned, not done
        WorksheetSubmission.objects.create(
            assignment=a1, student=self.student_user, score=7, total_questions=10,
            completed_at=timezone.now(),
        )
        s = worksheet_section(self.student_user, self.classroom)
        self.assertEqual(s['mode'], 'summary')
        self.assertEqual(s['assigned'], 2)
        self.assertEqual(s['completed'], 1)
        self.assertEqual(s['completion_pct'], 50)
        self.assertEqual(s['average_pct'], 70)

    def test_worksheet_selected(self):
        a1 = self._worksheet_assignment('Shapes')
        a2 = self._worksheet_assignment('Angles')
        WorksheetSubmission.objects.create(
            assignment=a1, student=self.student_user, score=6, total_questions=10,
            completed_at=timezone.now(),
        )
        s = worksheet_section(self.student_user, self.classroom, mode='selected',
                              ids=[a1.id, a2.id])
        by_title = {i['title']: i for i in s['items']}
        self.assertEqual(by_title['Shapes']['pct'], 60)
        self.assertFalse(by_title['Angles']['attempted'])

    # ----- Maths: summary + breakdowns ------------------------------------

    def test_maths_summary_numbers(self):
        self.assertEqual(
            maths_summary(self.student_user),
            {'topics_attempted': 0, 'average_pct': 0, 'basic_facts_levels': 0},
        )

    def test_maths_breakdowns_opt_in(self):
        topic = Topic.objects.create(subject=self.subject, name='Algebra')
        StudentFinalAnswer.objects.create(
            student=self.student_user, topic=topic, level=self.level,
            quiz_type='topic', attempt_number=1, score=9, total_questions=10,
            points=90.0, time_taken_seconds=0,
        )
        StudentFinalAnswer.objects.create(
            student=self.student_user, level=self.level, quiz_type='times_table',
            operation='multiplication', table_number=7, attempt_number=1,
            score=8, total_questions=10, points=80.0, time_taken_seconds=0,
        )
        BasicFactsResult.objects.create(
            student=self.student_user, subtopic='Addition', level_number=1,
            score=10, total_points=10, points=100.0, time_taken_seconds=0,
        )
        # Without opt-in, no breakdown keys.
        plain = maths_summary(self.student_user)
        self.assertNotIn('times_tables', plain)
        self.assertNotIn('topics', plain)

        s = maths_summary(self.student_user, times_tables=True, topics=True, basic_facts=True)
        self.assertEqual(s['topics'][0], {'name': 'Algebra', 'best_pct': 90})
        tt = s['times_tables'][0]
        self.assertEqual(tt['table'], 7)
        self.assertEqual(tt['multiplication_pct'], 80)
        self.assertIsNone(tt['division_pct'])
        self.assertEqual(s['basic_facts'][0],
                         {'subtopic': 'Addition', 'level': 1, 'best_pct': 100})

    # ----- Coding + orchestrator ------------------------------------------

    def test_coding_summary_zero_state(self):
        self.assertEqual(
            coding_section(self.student_user),
            {'mode': 'summary', 'exercises_completed': 0, 'problems_solved': 0},
        )

    def test_coding_selected_per_topic(self):
        from coding.models import (
            CodingLanguage, CodingTopic, TopicLevel, CodingExercise,
            StudentExerciseSubmission,
        )
        lang = CodingLanguage.objects.create(name='RptLang', slug='rpt-lang', order=1)
        topic = CodingTopic.objects.create(language=lang, name='Loops', slug='loops')
        tl = TopicLevel.objects.create(topic=topic, level_choice='beginner')
        ex1 = CodingExercise.objects.create(topic_level=tl, title='Ex1', order=1)
        CodingExercise.objects.create(topic_level=tl, title='Ex2', order=2)
        StudentExerciseSubmission.objects.create(
            student=self.student_user, exercise=ex1, is_completed=True,
        )
        s = coding_section(self.student_user, mode='selected', language_ids=[lang.id])
        self.assertEqual(s['mode'], 'selected')
        py = s['languages'][0]
        self.assertEqual(py['name'], 'RptLang')
        self.assertEqual(py['topics'][0],
                         {'name': 'Loops', 'completed': 1, 'total': 2, 'pct': 50})

    def test_build_summary_includes_only_selected(self):
        out = build_summary(
            self.student_user, self.classroom,
            homework=True, worksheets=True, maths=False, coding=False,
        )
        self.assertEqual(set(out), {'homework', 'worksheets'})
        self.assertEqual(out['homework']['mode'], 'summary')

    def test_build_summary_skips_class_sections_without_class(self):
        out = build_summary(self.student_user, None, homework=True, worksheets=True,
                            maths=True, coding=True)
        self.assertNotIn('homework', out)
        self.assertNotIn('worksheets', out)
        self.assertEqual(set(out), {'maths', 'coding'})
