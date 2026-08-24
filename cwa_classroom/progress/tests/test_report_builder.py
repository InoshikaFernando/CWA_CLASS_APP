"""The report snapshot: totals, topics, attempts, trend (CPP-388)."""

from datetime import date, datetime, time

from django.test import TestCase
from django.utils import timezone

from progress import periods, reports
from progress.tests.factories import (
    answer, enrol, make_classroom, make_homework, make_question, make_school,
    make_topic, make_user, submit,
)

START = date(2026, 8, 17)
END = date(2026, 8, 23)


def at(day, hour=10):
    """A timezone-aware datetime inside the test window."""
    return timezone.make_aware(
        datetime.combine(day, time(hour, 0)), timezone.get_current_timezone(),
    )


class ReportBuilderBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.classroom = make_classroom(cls.school)
        cls.student = make_user('rb_student')
        enrol(cls.classroom, cls.student)


class TotalsTests(ReportBuilderBase):
    def test_no_activity_reports_zeros_rather_than_nothing(self):
        data = reports.build_report_data(
            self.student, periods.WEEKLY, START, END,
        )
        self.assertEqual(data['totals']['submissions'], 0)
        self.assertEqual(data['totals']['avg_best_pct'], 0)
        self.assertEqual(data['topics'], [])
        self.assertEqual(data['awards'], [])

    def test_best_and_first_averages_are_measured_over_the_same_homework(self):
        homework = make_homework(self.classroom, due=at(date(2026, 8, 21)))
        submit(homework, self.student, 1, 4, when=at(date(2026, 8, 18)))
        submit(homework, self.student, 2, 9, when=at(date(2026, 8, 19)))

        totals = reports.build_report_data(
            self.student, periods.WEEKLY, START, END,
        )['totals']

        self.assertEqual(totals['avg_first_pct'], 40)
        self.assertEqual(totals['avg_best_pct'], 90)
        self.assertEqual(totals['improvement_pct'], 50)
        self.assertEqual(totals['submissions'], 2)
        self.assertEqual(totals['homework_attempted'], 1)

    def test_submissions_outside_the_window_are_excluded(self):
        homework = make_homework(self.classroom, due=at(date(2026, 8, 21)))
        submit(homework, self.student, 1, 10, when=at(date(2026, 8, 10)))

        totals = reports.build_report_data(
            self.student, periods.WEEKLY, START, END,
        )['totals']
        self.assertEqual(totals['submissions'], 0)

    def test_the_last_day_of_the_window_is_included(self):
        homework = make_homework(self.classroom, due=at(END))
        submit(homework, self.student, 1, 7, when=at(END, hour=23))

        totals = reports.build_report_data(
            self.student, periods.WEEKLY, START, END,
        )['totals']
        self.assertEqual(totals['submissions'], 1)

    def test_completion_counts_homework_due_in_the_window(self):
        done = make_homework(self.classroom, due=at(date(2026, 8, 20)), title='Done')
        make_homework(self.classroom, due=at(date(2026, 8, 22)), title='Skipped')
        submit(done, self.student, 1, 8, when=at(date(2026, 8, 19)))

        totals = reports.build_report_data(
            self.student, periods.WEEKLY, START, END,
        )['totals']
        self.assertEqual(totals['assigned'], 2)
        self.assertEqual(totals['completed'], 1)
        self.assertEqual(totals['completion_pct'], 50)

    def test_a_first_attempt_after_the_due_date_is_not_on_time(self):
        homework = make_homework(self.classroom, due=at(date(2026, 8, 18)))
        submit(homework, self.student, 1, 8, when=at(date(2026, 8, 20)))

        totals = reports.build_report_data(
            self.student, periods.WEEKLY, START, END,
        )['totals']
        self.assertEqual(totals['on_time_pct'], 0)

    def test_time_on_task_sums_every_attempt(self):
        homework = make_homework(self.classroom, due=at(date(2026, 8, 21)))
        submit(homework, self.student, 1, 4, when=at(date(2026, 8, 18)), seconds=600)
        submit(homework, self.student, 2, 9, when=at(date(2026, 8, 19)), seconds=300)

        totals = reports.build_report_data(
            self.student, periods.WEEKLY, START, END,
        )['totals']
        self.assertEqual(totals['time_minutes'], 15)


class TopicTests(ReportBuilderBase):
    def test_accuracy_is_computed_per_topic_from_the_answers_given(self):
        fractions = make_topic('Fractions')
        decimals = make_topic('Decimals')
        homework = make_homework(self.classroom, due=at(date(2026, 8, 21)))
        submission = submit(homework, self.student, 1, 3, when=at(date(2026, 8, 19)))

        answer(submission, make_question(fractions), True)
        answer(submission, make_question(fractions, text='q2'), True)
        answer(submission, make_question(decimals, text='q3'), False)
        answer(submission, make_question(decimals, text='q4'), True)

        topics = reports.build_report_data(
            self.student, periods.WEEKLY, START, END,
        )['topics']
        by_name = {row['topic']: row for row in topics}

        self.assertEqual(by_name['Fractions']['accuracy_pct'], 100)
        self.assertEqual(by_name['Decimals']['accuracy_pct'], 50)
        self.assertEqual(by_name['Decimals']['answered'], 2)

    def test_topicless_answers_are_grouped_not_dropped(self):
        homework = make_homework(self.classroom, due=at(date(2026, 8, 21)))
        submission = submit(homework, self.student, 1, 1, when=at(date(2026, 8, 19)))
        answer(submission, make_question(None), True)
        answer(submission, make_question(None, text='q2'), False)

        topics = reports.build_report_data(
            self.student, periods.WEEKLY, START, END,
        )['topics']
        self.assertEqual(len(topics), 1)
        self.assertEqual(topics[0]['topic'], reports.UNCLASSIFIED)
        self.assertEqual(topics[0]['answered'], 2)

    def test_weakest_topic_is_listed_first(self):
        strong = make_topic('Strong')
        weak = make_topic('Weak')
        homework = make_homework(self.classroom, due=at(date(2026, 8, 21)))
        submission = submit(homework, self.student, 1, 1, when=at(date(2026, 8, 19)))
        answer(submission, make_question(strong), True)
        answer(submission, make_question(weak, text='q2'), False)

        topics = reports.build_report_data(
            self.student, periods.WEEKLY, START, END,
        )['topics']
        self.assertEqual(topics[0]['topic'], 'Weak')


class AttemptsTests(ReportBuilderBase):
    def test_each_homework_reports_first_best_and_gain(self):
        homework = make_homework(self.classroom, due=at(date(2026, 8, 21)))
        submit(homework, self.student, 1, 3, when=at(date(2026, 8, 18)))
        submit(homework, self.student, 2, 6, when=at(date(2026, 8, 19)))
        submit(homework, self.student, 3, 9, when=at(date(2026, 8, 20)))

        attempts = reports.build_report_data(
            self.student, periods.WEEKLY, START, END,
        )['attempts']
        row = attempts['items'][0]

        self.assertEqual(row['attempts'], 3)
        self.assertEqual(row['first_pct'], 30)
        self.assertEqual(row['best_pct'], 90)
        self.assertEqual(row['gain_pct'], 60)

    def test_best_is_the_highest_score_not_the_last_one(self):
        homework = make_homework(self.classroom, due=at(date(2026, 8, 21)))
        submit(homework, self.student, 1, 3, when=at(date(2026, 8, 18)))
        submit(homework, self.student, 2, 9, when=at(date(2026, 8, 19)))
        submit(homework, self.student, 3, 5, when=at(date(2026, 8, 20)))

        attempts = reports.build_report_data(
            self.student, periods.WEEKLY, START, END,
        )['attempts']
        self.assertEqual(attempts['items'][0]['best_pct'], 90)

    def test_distribution_buckets_three_or_more_together(self):
        once = make_homework(self.classroom, due=at(date(2026, 8, 20)), title='Once')
        thrice = make_homework(self.classroom, due=at(date(2026, 8, 21)), title='Thrice')
        submit(once, self.student, 1, 5, when=at(date(2026, 8, 18)))
        for attempt in (1, 2, 3, 4):
            submit(thrice, self.student, attempt, attempt * 2, when=at(date(2026, 8, 19)))

        attempts = reports.build_report_data(
            self.student, periods.WEEKLY, START, END,
        )['attempts']
        buckets = {entry['label']: entry['count'] for entry in attempts['distribution']}

        self.assertEqual(buckets, {'1': 1, '3+': 1})
        self.assertEqual(attempts['repeated'], 1)
        self.assertEqual(attempts['repeat_rate_pct'], 50)

    def test_biggest_gain_is_listed_first(self):
        small = make_homework(self.classroom, due=at(date(2026, 8, 20)), title='Small')
        big = make_homework(self.classroom, due=at(date(2026, 8, 21)), title='Big')
        submit(small, self.student, 1, 5, when=at(date(2026, 8, 18)))
        submit(small, self.student, 2, 6, when=at(date(2026, 8, 18)))
        submit(big, self.student, 1, 1, when=at(date(2026, 8, 19)))
        submit(big, self.student, 2, 9, when=at(date(2026, 8, 19)))

        attempts = reports.build_report_data(
            self.student, periods.WEEKLY, START, END,
        )['attempts']
        self.assertEqual(attempts['items'][0]['title'], 'Big')


class TrendTests(ReportBuilderBase):
    def test_a_weekly_report_buckets_by_day(self):
        homework = make_homework(self.classroom, due=at(date(2026, 8, 23)))
        submit(homework, self.student, 1, 4, when=at(date(2026, 8, 18)))
        submit(homework, self.student, 2, 8, when=at(date(2026, 8, 20)))

        trend = reports.build_report_data(
            self.student, periods.WEEKLY, START, END,
        )['trend']
        self.assertEqual([point['avg_pct'] for point in trend], [40, 80])
        self.assertEqual(trend[0]['label'], 'Tue 18 Aug')

    def test_a_monthly_report_buckets_by_week(self):
        homework = make_homework(self.classroom, due=at(date(2026, 8, 31)))
        submit(homework, self.student, 1, 4, when=at(date(2026, 8, 4)))
        submit(homework, self.student, 2, 6, when=at(date(2026, 8, 6)))
        submit(homework, self.student, 3, 10, when=at(date(2026, 8, 18)))

        trend = reports.build_report_data(
            self.student, periods.MONTHLY, date(2026, 8, 1), date(2026, 8, 31),
        )['trend']
        # Two calendar weeks, and the first is the mean of its two attempts.
        self.assertEqual(len(trend), 2)
        self.assertEqual(trend[0]['avg_pct'], 50)
        self.assertEqual(trend[1]['avg_pct'], 100)


class ScopeTests(ReportBuilderBase):
    def test_another_students_work_never_leaks_in(self):
        other = make_user('rb_other')
        enrol(self.classroom, other)
        homework = make_homework(self.classroom, due=at(date(2026, 8, 21)))
        submit(homework, other, 1, 10, when=at(date(2026, 8, 19)))

        totals = reports.build_report_data(
            self.student, periods.WEEKLY, START, END,
        )['totals']
        self.assertEqual(totals['submissions'], 0)

    def test_homework_for_a_class_the_student_left_is_not_counted_as_assigned(self):
        from classroom.models import ClassStudent

        other_class = make_classroom(self.school, name='Old Class', code='RPTOLD01')
        link = enrol(other_class, self.student)
        ClassStudent.objects.filter(pk=link.pk).update(is_active=False)
        make_homework(other_class, due=at(date(2026, 8, 20)), title='Left behind')

        totals = reports.build_report_data(
            self.student, periods.WEEKLY, START, END,
        )['totals']
        self.assertEqual(totals['assigned'], 0)


class SoftDeletedHomeworkTests(ReportBuilderBase):
    """A homework the teacher removed is hidden everywhere else, so hide it here.

    Its submissions stay in the database — that is the whole point of the soft
    delete — which means the report has to exclude them explicitly. A related
    lookup joins the table directly and never sees ``Homework.objects``.
    """

    def test_deleted_homework_drops_out_of_the_totals(self):
        kept = make_homework(self.classroom, due=at(date(2026, 8, 20)), title='Kept')
        removed = make_homework(self.classroom, due=at(date(2026, 8, 21)), title='Removed')
        submit(kept, self.student, 1, 8, when=at(date(2026, 8, 18)))
        submit(removed, self.student, 1, 2, when=at(date(2026, 8, 19)))

        removed.soft_delete()

        data = reports.build_report_data(self.student, periods.WEEKLY, START, END)

        self.assertEqual(data['totals']['submissions'], 1)
        self.assertEqual(data['totals']['avg_best_pct'], 80)
        self.assertEqual(data['totals']['assigned'], 1)
        self.assertEqual([row['title'] for row in data['attempts']['items']], ['Kept'])

    def test_deleted_homework_does_not_skew_a_classmates_award(self):
        rival = make_user('rb_rival')
        enrol(self.classroom, rival)
        removed = make_homework(self.classroom, due=at(date(2026, 8, 21)), title='Removed')
        kept = make_homework(self.classroom, due=at(date(2026, 8, 20)), title='Kept')
        # The rival's only high score is on the homework that gets removed.
        submit(removed, rival, 1, 10, when=at(date(2026, 8, 18)))
        submit(kept, rival, 1, 3, when=at(date(2026, 8, 18)))
        submit(kept, self.student, 1, 8, when=at(date(2026, 8, 18)))

        removed.soft_delete()

        codes = {
            award['code'] for award in
            reports.build_report_data(
                self.student, periods.WEEKLY, START, END)['awards']
        }
        self.assertIn('top_scorer', codes)
