"""Quiz, times-table and basic-facts sections (CPP-388 follow-up).

The ticket said the report should read homework submissions, so that is what it
did — and a child who spends a week on times tables showed as having done
nothing. These strands read the same closed window, so "this period" still
means one thing across the whole report.
"""

from datetime import date, datetime, time

from django.test import TestCase
from django.utils import timezone

from maths.models import BasicFactsResult, StudentFinalAnswer
from progress import periods, reports
from progress.tests.factories import (
    enrol, make_classroom, make_homework, make_school, make_topic, make_user,
    submit,
)

START, END = date(2026, 8, 17), date(2026, 8, 23)
OUTSIDE = date(2026, 8, 10)


def at(day, hour=10):
    return timezone.make_aware(
        datetime.combine(day, time(hour, 0)), timezone.get_current_timezone(),
    )


def quiz(student, **kwargs):
    when = kwargs.pop('when')
    row = StudentFinalAnswer.objects.create(student=student, **kwargs)
    StudentFinalAnswer.objects.filter(pk=row.pk).update(completed_at=when)
    return row


class MathsActivityBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.classroom = make_classroom(cls.school)
        cls.student = make_user('ma_student')
        enrol(cls.classroom, cls.student)
        cls.fractions = make_topic('Fractions')

    def data(self):
        return reports.build_report_data(
            self.student, periods.WEEKLY, START, END,
        )


class QuizSectionTests(MathsActivityBase):
    def test_quiz_attempts_report_first_versus_best_like_homework(self):
        quiz(self.student, topic=self.fractions, quiz_type='topic',
             score=3, total_questions=10, points=3, when=at(date(2026, 8, 18)))
        quiz(self.student, topic=self.fractions, quiz_type='topic',
             score=9, total_questions=10, points=9, when=at(date(2026, 8, 19)))

        section = self.data()['quizzes']
        self.assertEqual(section['attempted'], 1)
        self.assertEqual(section['attempts'], 2)
        self.assertEqual(section['avg_first_pct'], 30)
        self.assertEqual(section['avg_best_pct'], 90)
        self.assertEqual(section['items'][0]['gain_pct'], 60)

    def test_a_mixed_quiz_has_no_topic_and_is_bucketed_not_dropped(self):
        quiz(self.student, topic=None, quiz_type='mixed',
             score=7, total_questions=10, points=7, when=at(date(2026, 8, 18)))

        section = self.data()['quizzes']
        self.assertEqual(section['attempted'], 1)
        self.assertEqual(section['items'][0]['name'], 'Mixed quiz')

    def test_attempts_outside_the_window_are_excluded(self):
        quiz(self.student, topic=self.fractions, quiz_type='topic',
             score=10, total_questions=10, points=10, when=at(OUTSIDE))

        self.assertEqual(self.data()['quizzes']['attempts'], 0)

    def test_times_table_attempts_do_not_leak_into_the_quiz_section(self):
        quiz(self.student, quiz_type='times_table', table_number=7,
             operation='multiplication', score=8, total_questions=10, points=8,
             when=at(date(2026, 8, 18)))

        self.assertEqual(self.data()['quizzes']['attempts'], 0)


class TimesTableSectionTests(MathsActivityBase):
    def test_best_is_kept_per_table_and_operation(self):
        for score in (4, 9):
            quiz(self.student, quiz_type='times_table', table_number=7,
                 operation='multiplication', score=score, total_questions=10,
                 points=score, when=at(date(2026, 8, 18)))
        quiz(self.student, quiz_type='times_table', table_number=7,
             operation='division', score=6, total_questions=10, points=6,
             when=at(date(2026, 8, 19)))

        section = self.data()['times_tables']
        self.assertEqual(section['tables'], 1)
        row = section['items'][0]
        self.assertEqual(row['table'], 7)
        self.assertEqual(row['multiplication_pct'], 90)
        self.assertEqual(row['division_pct'], 60)

    def test_a_legacy_attempt_with_no_operation_still_counts(self):
        quiz(self.student, quiz_type='times_table', table_number=3,
             operation='', score=8, total_questions=10, points=8,
             when=at(date(2026, 8, 18)))

        section = self.data()['times_tables']
        self.assertEqual(section['tables'], 1)
        self.assertEqual(section['items'][0]['best_pct'], 80)


class BasicFactsSectionTests(MathsActivityBase):
    def make(self, subtopic, level, score, when):
        row = BasicFactsResult.objects.create(
            student=self.student, subtopic=subtopic, level_number=level,
            session_id='s', score=score, total_points=10,
            time_taken_seconds=60, points=score,
        )
        BasicFactsResult.objects.filter(pk=row.pk).update(completed_at=when)

    def test_best_per_subtopic_is_reported(self):
        self.make('Addition', 3, 6, at(date(2026, 8, 18)))
        self.make('Addition', 7, 10, at(date(2026, 8, 19)))
        self.make('Division', 2, 5, at(date(2026, 8, 20)))

        section = self.data()['basic_facts']
        self.assertEqual(section['subtopics'], 2)
        addition = next(i for i in section['items'] if i['subtopic'] == 'Addition')
        self.assertEqual(addition['best_pct'], 100)
        self.assertEqual(addition['level'], 7)

    def test_place_value_gets_a_readable_label(self):
        self.make('PlaceValue', 1, 9, at(date(2026, 8, 18)))
        self.assertEqual(
            self.data()['basic_facts']['items'][0]['subtopic'], 'Place Value',
        )


class OverallActivityTests(MathsActivityBase):
    def test_practice_alone_counts_as_activity(self):
        """A week spent on times tables is not "no activity"."""
        quiz(self.student, quiz_type='times_table', table_number=5,
             operation='multiplication', score=8, total_questions=10, points=8,
             when=at(date(2026, 8, 18)))

        data = self.data()
        self.assertEqual(data['totals']['submissions'], 0)
        self.assertEqual(data['totals']['activity_items'], 1)
        self.assertEqual(data['totals']['overall_avg_pct'], 80)

    def test_the_overall_average_weights_each_strand_by_what_was_attempted(self):
        # Four homework at 50%, one perfect times table. The table must not
        # drag the overall up as if it were half the child's work.
        for index in range(4):
            homework = make_homework(
                self.classroom, due=at(date(2026, 8, 21)), title=f'HW{index}',
            )
            submit(homework, self.student, 1, 5, when=at(date(2026, 8, 18)))
        quiz(self.student, quiz_type='times_table', table_number=2,
             operation='multiplication', score=10, total_questions=10,
             points=10, when=at(date(2026, 8, 19)))

        totals = self.data()['totals']
        self.assertEqual(totals['avg_best_pct'], 50)      # homework alone
        self.assertEqual(totals['activity_items'], 5)
        self.assertEqual(totals['overall_avg_pct'], 60)   # (4*50 + 1*100) / 5

    def test_a_period_with_nothing_at_all_is_still_empty(self):
        totals = self.data()['totals']
        self.assertEqual(totals['activity_items'], 0)
        self.assertEqual(totals['overall_avg_pct'], 0)
