"""Merging duplicated topic rows — detection, guardrails, and what moves.

The same topic gets created twice ("Fractions" alongside "Fraction"), which
splits a strand in two: filtering to one copy silently misses every question
filed under the other.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from classroom.models import Level, Subject, Topic
from classroom.topic_merge import (
    find_duplicate_groups,
    merge_topics,
    normalise,
    validate_merge,
)
from maths.models import Question

User = get_user_model()


class NormaliseTests(TestCase):

    def test_a_trailing_plural_does_not_hide_a_duplicate(self):
        self.assertEqual(normalise('Fraction'), normalise('Fractions'))

    def test_case_and_spacing_are_noise(self):
        self.assertEqual(normalise('  ADDITION '), normalise('Addition'))

    def test_punctuation_is_noise(self):
        self.assertEqual(normalise('Add & Subtract'), normalise('Add Subtract'))

    def test_a_short_word_ending_in_s_is_left_alone(self):
        # 'Mass' must not become 'Mas' and collide with something unrelated.
        self.assertEqual(normalise('Mass'), 'mass')

    def test_genuinely_different_topics_do_not_collide(self):
        self.assertNotEqual(normalise('Fractions'), normalise('Decimals'))


class TopicMergeTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username='topicadmin', email='ta@test.com', password='pass1234')
        cls.maths = Subject.objects.create(name='Mathematics', slug='maths-tm')
        cls.science = Subject.objects.create(name='Science', slug='sci-tm')
        cls.level = Level.objects.create(level_number=97, display_name='Y97')

    def _topic(self, name, slug, subject=None, parent=None):
        return Topic.objects.create(
            name=name, slug=slug, subject=subject or self.maths, parent=parent)

    def _question(self, topic, text='1 + 1 = ?'):
        return Question.objects.create(
            level=self.level, topic=topic, question_text=text,
            question_type='multiple_choice')


class DetectionTests(TopicMergeTestBase):

    def test_singular_and_plural_are_grouped(self):
        a = self._topic('Fractions', 'fractions-a')
        b = self._topic('Fraction', 'fraction-b')

        groups = find_duplicate_groups()
        ids = {t['id'] for g in groups for t in g['members']}
        self.assertEqual({a.id, b.id}, ids)

    def test_a_topic_with_no_twin_is_not_reported(self):
        self._topic('Decimals', 'decimals-solo')
        self.assertEqual([], find_duplicate_groups())

    def test_the_same_name_under_two_subjects_is_not_a_duplicate(self):
        # Both subjects legitimately teach Fractions; merging them would move
        # questions out of the subject they belong to.
        self._topic('Fractions', 'fr-maths', subject=self.maths)
        self._topic('Fractions', 'fr-sci', subject=self.science)
        self.assertEqual([], find_duplicate_groups())

    def test_the_copy_holding_the_most_questions_is_suggested(self):
        small = self._topic('Fraction', 'fr-small')
        big = self._topic('Fractions', 'fr-big')
        self._question(big)
        self._question(big, '2 + 2 = ?')
        self._question(small)

        group = find_duplicate_groups()[0]
        self.assertEqual(big.id, group['suggested_keep_id'])
        self.assertEqual(3, group['total_questions'])

    def test_each_member_reports_what_it_holds(self):
        keep = self._topic('Addition', 'add-1')
        dupe = self._topic('Additions', 'add-2')
        self._question(keep)
        self._topic('Carrying', 'carry-1', parent=dupe)

        group = find_duplicate_groups()[0]
        by_id = {m['id']: m for m in group['members']}
        self.assertEqual(1, by_id[keep.id]['questions'])
        self.assertEqual(1, by_id[dupe.id]['subtopics'])


class GuardrailTests(TopicMergeTestBase):

    def test_merging_across_subjects_is_refused(self):
        a = self._topic('Fractions', 'fr-m', subject=self.maths)
        b = self._topic('Fractions', 'fr-s', subject=self.science)
        ok, err = validate_merge(a, b)
        self.assertFalse(ok)
        self.assertIn('different subjects', err)

    def test_merging_a_topic_into_itself_is_refused(self):
        a = self._topic('Fractions', 'fr-self')
        ok, _ = validate_merge(a, a)
        self.assertFalse(ok)

    def test_merging_a_parent_into_its_own_child_is_refused(self):
        parent = self._topic('Number', 'number-p')
        child = self._topic('Number', 'number-c', parent=parent)
        ok, err = validate_merge(child, parent)
        self.assertFalse(ok)
        self.assertIn('parent', err)

    def test_a_refused_pair_aborts_the_whole_batch(self):
        # A partial merge is worse than none, so validation runs up front.
        keep = self._topic('Fractions', 'fr-keep')
        fine = self._topic('Fraction', 'fr-fine')
        bad = self._topic('Fractions', 'fr-bad', subject=self.science)
        self._question(fine)

        with self.assertRaises(ValueError):
            merge_topics(keep, [fine, bad], actor=self.admin)

        # Nothing moved, nothing deleted.
        self.assertTrue(Topic.objects.filter(id=fine.id).exists())
        self.assertEqual(1, Question.objects.filter(topic_id=fine.id).count())


class MergeTests(TopicMergeTestBase):

    def test_questions_move_to_the_survivor(self):
        keep = self._topic('Fractions', 'fr-k')
        dupe = self._topic('Fraction', 'fr-d')
        moved = self._question(dupe)

        merge_topics(keep, [dupe], actor=self.admin)

        moved.refresh_from_db()
        self.assertEqual(keep.id, moved.topic_id)

    def test_the_absorbed_topic_is_deleted(self):
        # Leaving an inactive twin in the picker would defeat the purpose.
        keep = self._topic('Fractions', 'fr-k2')
        dupe = self._topic('Fraction', 'fr-d2')

        merge_topics(keep, [dupe], actor=self.admin)

        self.assertFalse(Topic.objects.filter(id=dupe.id).exists())
        self.assertTrue(Topic.objects.filter(id=keep.id).exists())

    def test_several_topics_can_be_merged_at_once(self):
        keep = self._topic('Fractions', 'fr-k3')
        d1 = self._topic('Fraction', 'fr-d3')
        d2 = self._topic('fractions', 'fr-d4')
        q1, q2 = self._question(d1), self._question(d2)

        summary = merge_topics(keep, [d1, d2], actor=self.admin)

        q1.refresh_from_db()
        q2.refresh_from_db()
        self.assertEqual(keep.id, q1.topic_id)
        self.assertEqual(keep.id, q2.topic_id)
        self.assertEqual(2, len(summary['absorbed']))

    def test_subtopics_are_reparented_not_orphaned(self):
        # Topic.parent is SET_NULL, so deleting without this would silently
        # detach the children from their strand.
        keep = self._topic('Number', 'num-k')
        dupe = self._topic('Numbers', 'num-d')
        child = self._topic('Rounding', 'round-1', parent=dupe)

        summary = merge_topics(keep, [dupe], actor=self.admin)

        child.refresh_from_db()
        self.assertEqual(keep.id, child.parent_id)
        self.assertEqual(1, summary['reparented'])

    def test_the_summary_reports_what_moved(self):
        keep = self._topic('Fractions', 'fr-k5')
        dupe = self._topic('Fraction', 'fr-d5')
        self._question(dupe)
        self._question(dupe, '3 + 3 = ?')

        summary = merge_topics(keep, [dupe], actor=self.admin)

        self.assertEqual(keep.id, summary['keep_id'])
        self.assertEqual(2, summary['repointed'].get('maths.Question'))

    def test_the_merged_group_no_longer_reports_as_duplicate(self):
        keep = self._topic('Fractions', 'fr-k6')
        dupe = self._topic('Fraction', 'fr-d6')

        merge_topics(keep, [dupe], actor=self.admin)

        self.assertEqual([], find_duplicate_groups())
