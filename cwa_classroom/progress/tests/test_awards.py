"""Recognition rules and their guards (CPP-388 §2.5).

An award that fires for a class of one, or for a student who did nothing, is
worse than no award: it teaches the reader to ignore the section.
"""

from datetime import date, datetime, time

from django.test import TestCase
from django.utils import timezone

from progress import periods, reports
from progress.tests.factories import (
    enrol, make_classroom, make_homework, make_school, make_user, submit,
)

START = date(2026, 8, 17)
END = date(2026, 8, 23)


def at(day, hour=10):
    return timezone.make_aware(
        datetime.combine(day, time(hour, 0)), timezone.get_current_timezone(),
    )


def codes(student, start=START, end=END):
    data = reports.build_report_data(student, periods.WEEKLY, start, end)
    return {award['code'] for award in data['awards']}


class AwardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.classroom = make_classroom(cls.school)
        cls.alice = make_user('alice')
        cls.bob = make_user('bob')
        enrol(cls.classroom, cls.alice)
        enrol(cls.classroom, cls.bob)

    def homework(self, title='HW', due_day=date(2026, 8, 21)):
        return make_homework(self.classroom, due=at(due_day), title=title)

    # -- top scorer ------------------------------------------------------

    def test_top_scorer_goes_to_the_highest_average(self):
        homework = self.homework()
        submit(homework, self.alice, 1, 9, when=at(date(2026, 8, 18)))
        submit(homework, self.bob, 1, 4, when=at(date(2026, 8, 18)))

        self.assertIn('top_scorer', codes(self.alice))
        self.assertNotIn('top_scorer', codes(self.bob))

    def test_a_tie_awards_both_students(self):
        homework = self.homework()
        submit(homework, self.alice, 1, 8, when=at(date(2026, 8, 18)))
        submit(homework, self.bob, 1, 8, when=at(date(2026, 8, 18)))

        self.assertIn('top_scorer', codes(self.alice))
        self.assertIn('top_scorer', codes(self.bob))

    def test_no_class_relative_award_when_nobody_else_took_part(self):
        homework = self.homework()
        submit(homework, self.alice, 1, 9, when=at(date(2026, 8, 18)))

        earned = codes(self.alice)
        self.assertNotIn('top_scorer', earned)
        self.assertNotIn('most_improved', earned)
        self.assertNotIn('hard_worker', earned)

    def test_nobody_wins_top_scorer_when_every_average_is_zero(self):
        homework = self.homework()
        submit(homework, self.alice, 1, 0, when=at(date(2026, 8, 18)))
        submit(homework, self.bob, 1, 0, when=at(date(2026, 8, 18)))

        self.assertNotIn('top_scorer', codes(self.alice))

    # -- hard worker -----------------------------------------------------

    def test_hard_worker_needs_a_retry_not_just_volume(self):
        first = self.homework(title='One', due_day=date(2026, 8, 20))
        second = self.homework(title='Two', due_day=date(2026, 8, 21))
        # Alice: three homework, one attempt each — volume without retrying.
        third = self.homework(title='Three', due_day=date(2026, 8, 22))
        for homework in (first, second, third):
            submit(homework, self.alice, 1, 5, when=at(date(2026, 8, 18)))
        # Bob: fewer homework but he went back.
        submit(first, self.bob, 1, 3, when=at(date(2026, 8, 18)))
        submit(first, self.bob, 2, 7, when=at(date(2026, 8, 19)))

        self.assertNotIn('hard_worker', codes(self.alice))
        self.assertIn('hard_worker', codes(self.bob))

    # -- most improved ---------------------------------------------------

    def test_most_improved_goes_to_the_biggest_first_to_best_gain(self):
        homework = self.homework()
        submit(homework, self.alice, 1, 2, when=at(date(2026, 8, 18)))
        submit(homework, self.alice, 2, 9, when=at(date(2026, 8, 19)))
        submit(homework, self.bob, 1, 6, when=at(date(2026, 8, 18)))
        submit(homework, self.bob, 2, 7, when=at(date(2026, 8, 19)))

        self.assertIn('most_improved', codes(self.alice))
        self.assertNotIn('most_improved', codes(self.bob))

    def test_no_most_improved_when_nobody_improved(self):
        homework = self.homework()
        submit(homework, self.alice, 1, 5, when=at(date(2026, 8, 18)))
        submit(homework, self.bob, 1, 6, when=at(date(2026, 8, 18)))

        self.assertNotIn('most_improved', codes(self.alice))

    # -- fast and accurate -----------------------------------------------

    def test_fast_and_accurate_needs_the_marks_first(self):
        homework = self.homework()
        # Bob is far faster, but 50% is not "accurate".
        submit(homework, self.bob, 1, 5, when=at(date(2026, 8, 18)), seconds=60)
        submit(homework, self.alice, 1, 9, when=at(date(2026, 8, 18)), seconds=600)

        self.assertNotIn('fast_and_accurate', codes(self.bob))
        self.assertIn('fast_and_accurate', codes(self.alice))

    def test_fastest_of_the_accurate_students_wins(self):
        homework = self.homework()
        submit(homework, self.alice, 1, 9, when=at(date(2026, 8, 18)), seconds=600)
        submit(homework, self.bob, 1, 10, when=at(date(2026, 8, 18)), seconds=120)

        self.assertIn('fast_and_accurate', codes(self.bob))
        self.assertNotIn('fast_and_accurate', codes(self.alice))

    # -- individual awards -----------------------------------------------

    def test_perfect_score_needs_no_cohort(self):
        solo_class = make_classroom(self.school, name='Solo', code='RPTSOLO1')
        solo = make_user('solo')
        enrol(solo_class, solo)
        homework = make_homework(solo_class, due=at(date(2026, 8, 21)), title='Solo HW')
        submit(homework, solo, 1, 10, when=at(date(2026, 8, 18)))

        self.assertIn('perfect_score', codes(solo))

    def test_full_completion_needs_at_least_two_homework_due(self):
        only = self.homework(title='Only')
        submit(only, self.alice, 1, 8, when=at(date(2026, 8, 18)))
        self.assertNotIn('full_completion', codes(self.alice))

        second = self.homework(title='Second', due_day=date(2026, 8, 22))
        submit(second, self.alice, 1, 7, when=at(date(2026, 8, 19)))
        self.assertIn('full_completion', codes(self.alice))

    def test_full_completion_is_withheld_when_one_is_skipped(self):
        done = self.homework(title='Done')
        self.homework(title='Skipped', due_day=date(2026, 8, 22))
        submit(done, self.alice, 1, 8, when=at(date(2026, 8, 18)))

        self.assertNotIn('full_completion', codes(self.alice))

    # -- scoping ---------------------------------------------------------

    def test_awards_name_the_class_they_were_earned_in(self):
        homework = self.homework()
        submit(homework, self.alice, 1, 9, when=at(date(2026, 8, 18)))
        submit(homework, self.bob, 1, 4, when=at(date(2026, 8, 18)))

        data = reports.build_report_data(self.alice, periods.WEEKLY, START, END)
        top = next(a for a in data['awards'] if a['code'] == 'top_scorer')
        self.assertEqual(top['classroom'], self.classroom.name)
        self.assertIn('90%', top['detail'])

    def test_a_student_with_no_submissions_earns_nothing(self):
        homework = self.homework()
        submit(homework, self.bob, 1, 10, when=at(date(2026, 8, 18)))
        self.assertEqual(codes(self.alice), set())


class AwardArithmeticTests(TestCase):
    """The award's evidence must agree with the headline figure.

    "Gained 38 percentage points" four lines under "+37 pts" teaches the reader
    not to trust either number, so the two are computed the same way rather
    than by two defensible-but-different routes (mean of per-homework gains vs.
    the difference of the two means).
    """

    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.classroom = make_classroom(cls.school)
        cls.student = make_user('arith_student')
        cls.rival = make_user('arith_rival')
        enrol(cls.classroom, cls.student)
        enrol(cls.classroom, cls.rival)

    def test_most_improved_quotes_the_headline_gain(self):
        # Scores chosen so rounding the mean of gains and subtracting the means
        # would disagree.
        for index, (first, best) in enumerate([(3, 9), (4, 8), (5, 6)]):
            homework = make_homework(
                self.classroom, due=at(date(2026, 8, 21)), title=f'HW{index}',
            )
            submit(homework, self.student, 1, first, when=at(date(2026, 8, 18)))
            submit(homework, self.student, 2, best, when=at(date(2026, 8, 19)))
        submit(
            make_homework(self.classroom, due=at(date(2026, 8, 21)), title='Rival'),
            self.rival, 1, 5, when=at(date(2026, 8, 18)),
        )

        data = reports.build_report_data(
            self.student, periods.WEEKLY, START, END,
        )
        improvement = data['totals']['improvement_pct']
        award = next(a for a in data['awards'] if a['code'] == 'most_improved')

        self.assertIn(f'Gained {improvement} percentage points', award['detail'])
