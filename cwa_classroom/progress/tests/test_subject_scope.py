"""A report covers one subject's work, not every subject the student touches.

Found on the test site: previewing a coding class showed the student's times
tables and basic facts, because three of the five strands took no scoping
argument at all and every one of them is maths.

    quizzes_section(student, start, end)
    times_tables_section(student, start, end)
    basic_facts_section(student, start, end)

Homework was scoped by classroom but never by subject, so a mixed class list
mixed the subjects too.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from classroom.models import Subject
from maths.models import BasicFactsResult
from progress import periods
from progress.reports import build_report_data, covered_subject_slugs
from progress.tests.factories import (
    enrol, make_classroom, make_homework, make_school, make_user, submit,
)


def _subject(slug, name):
    subject, _ = Subject.objects.get_or_create(
        slug=slug, school=None, defaults={'name': name},
    )
    return subject


class CoveredSubjectSlugsTests(TestCase):
    """The rule that decides whether scoping is safe to apply at all."""

    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()

    def test_it_reads_the_slug_off_each_class(self):
        maths = make_classroom(self.school, name='Maths 5', code='SS000001')
        maths.subject = _subject('mathematics', 'Mathematics')
        maths.save(update_fields=['subject'])

        self.assertEqual(covered_subject_slugs([maths]), {'mathematics'})

    def test_a_class_with_no_subject_makes_the_answer_unknown(self):
        """None means "do not scope" — and must not be confused with empty.

        Dropping a class's work because somebody left the subject field blank
        would be a worse bug than the one this fixes, so an unknown anywhere
        in the scope disables scoping for the whole report.
        """
        known = make_classroom(self.school, name='Coding', code='SS000002')
        known.subject = _subject('coding', 'Coding')
        known.save(update_fields=['subject'])
        blank = make_classroom(self.school, name='Untagged', code='SS000003')

        self.assertIsNone(covered_subject_slugs([known, blank]))
        self.assertIsNone(covered_subject_slugs([]))


class ReportSubjectScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.student = make_user('ss_student', first_name='Avisha')

        cls.maths_class = make_classroom(
            cls.school, name='Maths 5', code='SS000010',
        )
        cls.maths_class.subject = _subject('mathematics', 'Mathematics')
        cls.maths_class.save(update_fields=['subject'])

        cls.coding_class = make_classroom(
            cls.school, name='Web Programming', code='SS000011',
        )
        cls.coding_class.subject = _subject('coding', 'Coding')
        cls.coding_class.save(update_fields=['subject'])

        enrol(cls.maths_class, cls.student)
        enrol(cls.coding_class, cls.student)

        cls.start, cls.end = periods.previous_week(periods.today())
        when = timezone.make_aware(
            timezone.datetime.combine(
                cls.start + timedelta(days=1), timezone.datetime.min.time(),
            ).replace(hour=10),
        )

        # Maths practice that belongs to no class at all: this is the work that
        # was leaking into every report regardless of scope.
        facts = BasicFactsResult.objects.create(
            student=cls.student, subtopic='PlaceValue', level_number=1,
            session_id='s', score=8, total_points=10,
            time_taken_seconds=60, points=8,
        )
        BasicFactsResult.objects.filter(pk=facts.pk).update(completed_at=when)

        maths_hw = make_homework(cls.maths_class, due=when, title='Fractions')
        submit(maths_hw, cls.student, 1, 7, when=when)

        coding_hw = make_homework(cls.coding_class, due=when, title='Loops')
        coding_hw.subject_slug = 'coding'
        coding_hw.save(update_fields=['subject_slug'])
        submit(coding_hw, cls.student, 1, 9, when=when)

        # A maths homework sitting in the coding class. Homework carries its
        # own subject_slug, so a class is not a reliable proxy for one — and
        # filtering by classroom alone cannot catch this row.
        stray = make_homework(cls.coding_class, due=when, title='Stray maths')
        submit(stray, cls.student, 1, 3, when=when)

    def _data(self, classroom_ids):
        return build_report_data(
            self.student, periods.WEEKLY, self.start, self.end,
            classroom_ids=classroom_ids,
        )

    def test_a_coding_report_carries_no_basic_facts(self):
        data = self._data([self.coding_class.id])

        self.assertEqual(data['basic_facts']['subtopics'], 0)
        self.assertEqual(data['times_tables']['tables'], 0)
        self.assertEqual(data['quizzes']['attempted'], 0)

    def test_a_maths_homework_inside_the_coding_class_is_still_excluded(self):
        """Classroom scoping cannot catch this one; only the subject can."""
        data = self._data([self.coding_class.id])

        self.assertEqual(data['totals']['homework_attempted'], 1)
        self.assertEqual(
            {row['topic'] for row in data['topics']} - {'Unclassified'}, set(),
            'a coding report should carry no maths topic rows',
        )

    def test_a_maths_report_still_carries_its_maths_practice(self):
        """The regression this fix could most easily cause."""
        data = self._data([self.maths_class.id])

        self.assertEqual(data['basic_facts']['subtopics'], 1)
        self.assertEqual(data['totals']['homework_attempted'], 1)

    def test_an_unscoped_report_is_unchanged(self):
        """classroom_ids=None still means everything, as it always did."""
        data = self._data(None)

        self.assertEqual(data['basic_facts']['subtopics'], 1)
        self.assertEqual(data['totals']['homework_attempted'], 3)
