"""The chart plots strands; the table keeps every sub-topic (CPP-388).

The report used to plot one bar per sub-topic. That read fine over a handful,
but a term covers around thirty of them and the picture became a wall of 6pt
labels that answered no question a parent actually has. "Is she behind in
Number or in Geometry?" is a question they do have, so the chart rolls up to
the strand and the table underneath still lists every sub-topic.

These tests pin the two halves apart: the rollup must be *computed from the
counts* (not averaged over sub-topics), it must be *frozen into the snapshot*
(a topic re-parented next term must not redraw a report already sent), and an
old snapshot with no rollup must keep charting what it always charted.
"""

from datetime import date, datetime, time

from django.test import TestCase
from django.utils import timezone

from progress import periods, reports
from progress.models import PeriodReport
from progress.tests.factories import (
    answer, enrol, make_classroom, make_homework, make_question, make_school,
    make_topic, make_user, submit,
)

START = date(2026, 8, 17)
END = date(2026, 8, 23)


def at(day, hour=10):
    return timezone.make_aware(
        datetime.combine(day, time(hour, 0)), timezone.get_current_timezone(),
    )


class TopicGroupsBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.classroom = make_classroom(cls.school)
        cls.student = make_user('tg_student')
        enrol(cls.classroom, cls.student)

    def build(self):
        return reports.build_report_data(
            self.student, periods.WEEKLY, START, END,
        )

    def submission(self):
        homework = make_homework(self.classroom, due=at(date(2026, 8, 21)))
        return submit(homework, self.student, 1, 3, when=at(date(2026, 8, 19)))


class RollupTests(TopicGroupsBase):
    def test_sub_topics_of_one_strand_become_one_bar(self):
        number = make_topic('Number')
        fractions = make_topic('Fractions', parent=number)
        decimals = make_topic('Decimals', parent=number)
        sub = self.submission()
        answer(sub, make_question(fractions, text='q1'), True)
        answer(sub, make_question(decimals, text='q2'), False)

        data = self.build()

        self.assertEqual([row['topic'] for row in data['topic_groups']], ['Number'])
        self.assertEqual(
            sorted(row['topic'] for row in data['topics']),
            ['Decimals', 'Fractions'],
        )

    def test_a_times_table_rolls_up_to_the_strand_not_its_parent(self):
        """The tree is three deep under the times tables.

        ``Number > Division > Division (3x)``. Grouping on the immediate parent
        would put "Division" on the chart as if it were a strand, eleven times
        over, while Number itself never appeared.
        """
        number = make_topic('Number')
        division = make_topic('Division', parent=number)
        three = make_topic('Division (3x)', parent=division)
        sub = self.submission()
        answer(sub, make_question(three, text='q1'), True)

        data = self.build()

        self.assertEqual([row['topic'] for row in data['topic_groups']], ['Number'])

    def test_a_strand_answered_directly_is_its_own_bar(self):
        number = make_topic('Number')
        sub = self.submission()
        answer(sub, make_question(number, text='q1'), True)

        data = self.build()

        self.assertEqual([row['topic'] for row in data['topic_groups']], ['Number'])

    def test_accuracy_is_recomputed_from_counts_not_averaged(self):
        """A two-question topic must not weigh as much as a sixty-question one.

        Averaging the sub-topic percentages here would give (0 + 100) / 2 = 50
        and report a child as half-right on a strand they got 3 of 4 right.
        """
        number = make_topic('Number')
        fractions = make_topic('Fractions', parent=number)
        decimals = make_topic('Decimals', parent=number)
        sub = self.submission()
        for i in range(3):
            answer(sub, make_question(fractions, text=f'f{i}'), True)
        answer(sub, make_question(decimals, text='d0'), False)

        group = self.build()['topic_groups'][0]

        self.assertEqual(group['answered'], 4)
        self.assertEqual(group['correct'], 3)
        self.assertEqual(group['accuracy_pct'], 75)

    def test_each_group_says_how_many_sub_topics_it_covers(self):
        number = make_topic('Number')
        sub = self.submission()
        answer(sub, make_question(make_topic('Fractions', parent=number), text='q1'), True)
        answer(sub, make_question(make_topic('Decimals', parent=number), text='q2'), True)

        self.assertEqual(self.build()['topic_groups'][0]['topics'], 2)

    def test_weakest_strand_is_first(self):
        number = make_topic('Number')
        geometry = make_topic('Geometry')
        sub = self.submission()
        answer(sub, make_question(make_topic('Fractions', parent=number), text='q1'), True)
        answer(sub, make_question(make_topic('Angles', parent=geometry), text='q2'), False)

        groups = self.build()['topic_groups']

        self.assertEqual([row['topic'] for row in groups], ['Geometry', 'Number'])

    def test_topicless_answers_group_under_unclassified(self):
        sub = self.submission()
        answer(sub, make_question(None, text='q1'), True)

        groups = self.build()['topic_groups']

        self.assertEqual([row['topic'] for row in groups], [reports.UNCLASSIFIED])

    def test_strands_of_the_same_name_under_different_subjects_stay_apart(self):
        """Two "Loops" in two languages are two topics, not one.

        Coding topics are flat, so their group is the language. The tally keys
        on (group, name), which is what keeps them separate — keying on the
        name alone would silently add them together.
        """
        number = make_topic('Number')
        geometry = make_topic('Geometry')
        sub = self.submission()
        answer(sub, make_question(
            make_topic('Shapes', parent=number, slug='number-shapes'), text='q1'), True)
        answer(sub, make_question(
            make_topic('Shapes', parent=geometry, slug='geometry-shapes'), text='q2'), False)

        data = self.build()

        self.assertEqual(len(data['topics']), 2)
        self.assertEqual(len(data['topic_groups']), 2)


class SnapshotTests(TopicGroupsBase):
    def test_the_strand_is_frozen_onto_each_sub_topic_row(self):
        number = make_topic('Number')
        sub = self.submission()
        answer(sub, make_question(make_topic('Fractions', parent=number), text='q1'), True)

        self.assertEqual(self.build()['topics'][0]['group'], 'Number')

    def test_re_parenting_a_topic_does_not_redraw_a_saved_report(self):
        number = make_topic('Number')
        geometry = make_topic('Geometry')
        fractions = make_topic('Fractions', parent=number)
        sub = self.submission()
        answer(sub, make_question(fractions, text='q1'), True)
        report = PeriodReport(
            student=self.student, school=self.school,
            period_type=periods.WEEKLY, period_start=START, period_end=END,
            data=self.build(),
        )

        fractions.parent = geometry
        fractions.save(update_fields=['parent'])

        self.assertEqual([row['topic'] for row in report.topic_groups], ['Number'])

    def test_an_old_snapshot_charts_its_sub_topics_rather_than_nothing(self):
        """Reports written before the rollup carry no strand to roll up to.

        There is nothing to derive one from — those rows never recorded a
        parent — so the chart shows what it always showed instead of an empty
        panel.
        """
        report = PeriodReport(
            student=self.student, school=self.school,
            period_type=periods.WEEKLY, period_start=START, period_end=END,
            data={'topics': [
                {'topic': 'Fractions', 'answered': 4, 'correct': 2,
                 'accuracy_pct': 50},
            ]},
        )

        self.assertEqual([row['topic'] for row in report.topic_groups], ['Fractions'])

    def test_topics_switched_off_leaves_both_lists_empty(self):
        number = make_topic('Number')
        sub = self.submission()
        answer(sub, make_question(make_topic('Fractions', parent=number), text='q1'), True)

        data = reports.build_report_data(
            self.student, periods.WEEKLY, START, END,
            content={'include_topics': False},
        )

        self.assertEqual(data['topics'], [])
        self.assertEqual(data['topic_groups'], [])


class PluginPathTests(TestCase):
    """Each plugin names the group a reader already thinks in."""

    def test_coding_groups_a_topic_under_its_language(self):
        """"Loops" means one thing in Python and another in Scratch.

        Coding topics are flat — ``CodingTopic`` has no parent — so a child
        working across two languages otherwise gets two identically named bars
        added together.
        """
        from coding.models import (
            CodingExercise, CodingLanguage, CodingTopic, TopicLevel,
        )
        from coding.plugin import CodingExercisePlugin

        language = CodingLanguage.objects.create(name='Python', slug='tg-py')
        topic = CodingTopic.objects.create(
            name='Loops', slug='tg-loops', language=language,
        )
        level = TopicLevel.objects.create(
            topic=topic, level_choice=TopicLevel.BEGINNER,
        )
        exercise = CodingExercise.objects.create(
            title='Count to 5', topic_level=level, description='d',
        )

        paths = CodingExercisePlugin().content_topic_paths([exercise.id])

        self.assertEqual(paths[exercise.id], ('Python', 'Loops'))

    def test_a_plugin_with_no_grouping_still_names_its_topics(self):
        """The default keeps a plugin on the chart rather than off it.

        Without this, a subject that never overrode the hook would contribute
        no rows to the rollup and vanish from the picture entirely — a silent
        loss, which is exactly the failure mode the report is meant to avoid.
        """
        from classroom.subject_registry import SubjectPlugin

        class Flat(SubjectPlugin):
            slug = 'flat'

            def content_topic_names(self, content_ids):
                return {7: 'Handwriting'}

        self.assertEqual(Flat().content_topic_paths([7]), {7: ('', 'Handwriting')})
