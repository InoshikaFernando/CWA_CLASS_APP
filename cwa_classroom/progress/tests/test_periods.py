"""Period-window maths (CPP-388).

The window is where the off-by-one bugs live: a week that ends a day early
silently drops Sunday's homework out of every report, and nothing goes red.
"""

from datetime import date

from django.test import TestCase

from classroom.models import AcademicYear, Term
from progress import periods
from progress.tests.factories import make_school, make_user


class WeekWindowTests(TestCase):
    def test_week_runs_monday_to_sunday(self):
        start, end = periods.week_window(date(2026, 8, 20))  # a Thursday
        self.assertEqual(start, date(2026, 8, 17))
        self.assertEqual(end, date(2026, 8, 23))

    def test_a_monday_belongs_to_its_own_week(self):
        start, end = periods.week_window(date(2026, 8, 17))
        self.assertEqual(start, date(2026, 8, 17))
        self.assertEqual(end, date(2026, 8, 23))

    def test_a_sunday_belongs_to_the_week_that_is_ending(self):
        start, end = periods.week_window(date(2026, 8, 23))
        self.assertEqual(start, date(2026, 8, 17))

    def test_previous_week_is_the_one_that_just_closed(self):
        start, end = periods.previous_week(date(2026, 8, 24))  # the Monday after
        self.assertEqual((start, end), (date(2026, 8, 17), date(2026, 8, 23)))

    def test_week_spanning_a_year_boundary(self):
        start, end = periods.week_window(date(2027, 1, 1))  # a Friday
        self.assertEqual(start, date(2026, 12, 28))
        self.assertEqual(end, date(2027, 1, 3))


class MonthWindowTests(TestCase):
    def test_month_runs_first_to_last_day(self):
        start, end = periods.month_window(date(2026, 8, 14))
        self.assertEqual((start, end), (date(2026, 8, 1), date(2026, 8, 31)))

    def test_february_in_a_leap_year(self):
        start, end = periods.month_window(date(2028, 2, 10))
        self.assertEqual(end, date(2028, 2, 29))

    def test_previous_month_from_the_first_of_january(self):
        start, end = periods.previous_month(date(2027, 1, 1))
        self.assertEqual((start, end), (date(2026, 12, 1), date(2026, 12, 31)))


class DuePeriodTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.year = AcademicYear.objects.create(
            school=cls.school, year=2026,
            start_date=date(2026, 2, 1), end_date=date(2026, 12, 15),
        )
        cls.term = Term.objects.create(
            school=cls.school, academic_year=cls.year, name='Term 3',
            start_date=date(2026, 7, 20), end_date=date(2026, 9, 25),
        )

    def test_monday_makes_the_weekly_report_due(self):
        due = periods.due_periods(date(2026, 8, 24))  # Monday
        self.assertEqual([entry[0] for entry in due], [periods.WEEKLY])
        self.assertEqual(due[0][1], date(2026, 8, 17))

    def test_a_midweek_day_is_a_legitimate_no_op(self):
        self.assertEqual(periods.due_periods(date(2026, 8, 26)), [])

    def test_the_first_of_the_month_makes_the_monthly_report_due(self):
        due = periods.due_periods(date(2026, 9, 1))  # a Tuesday
        self.assertEqual([entry[0] for entry in due], [periods.MONTHLY])
        self.assertEqual(due[0][1:3], (date(2026, 8, 1), date(2026, 8, 31)))

    def test_a_monday_that_is_also_the_first_makes_both_due(self):
        due = periods.due_periods(date(2026, 6, 1))  # Monday 1 June 2026
        self.assertEqual(
            sorted(entry[0] for entry in due),
            [periods.MONTHLY, periods.WEEKLY],
        )

    def test_the_day_after_a_term_ends_makes_the_term_report_due(self):
        due = periods.due_periods(date(2026, 9, 26))
        types = [entry[0] for entry in due]
        self.assertIn(periods.TERM, types)
        term_entry = next(e for e in due if e[0] == periods.TERM)
        self.assertEqual(term_entry[1:3], (date(2026, 7, 20), date(2026, 9, 25)))
        self.assertEqual(term_entry[3], self.term)

    def test_the_last_day_of_term_is_not_yet_due(self):
        # Generating on the final day would race that day's submissions.
        self.assertEqual(
            [e[0] for e in periods.due_periods(date(2026, 9, 25))], [],
        )


class LabelTests(TestCase):
    def test_weekly_label_names_the_monday(self):
        self.assertEqual(
            periods.label_for(periods.WEEKLY, date(2026, 8, 17), date(2026, 8, 23)),
            'Week of 17 Aug 2026',
        )

    def test_monthly_label_is_the_month(self):
        self.assertEqual(
            periods.label_for(periods.MONTHLY, date(2026, 8, 1), date(2026, 8, 31)),
            'August 2026',
        )

    def test_term_label_uses_the_term_name_and_year(self):
        school = make_school(slug='label-school', name='Label School')
        year = AcademicYear.objects.create(
            school=school, year=2026,
            start_date=date(2026, 2, 1), end_date=date(2026, 12, 15),
        )
        term = Term.objects.create(
            school=school, academic_year=year, name='Term 2',
            start_date=date(2026, 5, 1), end_date=date(2026, 7, 1),
        )
        self.assertEqual(
            periods.label_for(periods.TERM, term.start_date, term.end_date, term),
            'Term 2 2026',
        )


class StudentSchoolTests(TestCase):
    def test_an_individual_learner_has_no_school(self):
        student = make_user('lonely')
        self.assertIsNone(periods.student_school(student))

    def test_class_membership_resolves_the_school(self):
        from progress.tests.factories import enrol, make_classroom

        school = make_school(slug='resolve-school', name='Resolve School')
        classroom = make_classroom(school)
        student = make_user('enrolled')
        enrol(classroom, student)
        self.assertEqual(periods.student_school(student), school)
