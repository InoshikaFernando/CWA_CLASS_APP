"""Topic inventory and merge — what exists, what is wrong, and what moves.

The same topic gets created twice ("Fractions" alongside "Fraction"), which
splits a strand in two: filtering to one copy silently misses every question
filed under the other.

Detection deliberately reports FACTS rather than guessing which names mean the
same thing. A merge is not reversible, so the judgement call stays with a
human.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from classroom.models import Level, School, Subject, Topic
from classroom.topic_merge import (
    exact_name_clashes,
    merge_topics,
    near_duplicate_names,
    normalised_name,
    structural_issues,
    subject_name_clashes,
    topic_inventory,
    validate_merge,
)
from maths.models import Question

User = get_user_model()


class TopicMergeTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username='topicadmin', email='ta@test.com', password='pass1234')
        cls.maths = Subject.objects.create(name='Mathematics', slug='maths-tm')
        cls.science = Subject.objects.create(name='Science', slug='sci-tm')
        cls.level = Level.objects.create(level_number=97, display_name='Y97')

    def _topic(self, name, slug, subject=None, parent=None, active=True):
        return Topic.objects.create(
            name=name, slug=slug, subject=subject or self.maths, parent=parent,
            is_active=active)

    def _question(self, topic, text='1 + 1 = ?'):
        return Question.objects.create(
            level=self.level, topic=topic, question_text=text,
            question_type='multiple_choice')

    def _codes(self, **kwargs):
        return [i['code'] for i in structural_issues(**kwargs)]


class InventoryTests(TopicMergeTestBase):
    """The whole tree in one list — what makes a duplicate obvious to a human."""

    def test_topics_are_grouped_by_subject(self):
        self._topic('Fractions', 'fr-inv', subject=self.maths)
        self._topic('Forces', 'forces-inv', subject=self.science)

        inventory = topic_inventory()
        by_subject = {s['subject']: s for s in inventory}
        self.assertEqual(['Fractions'],
                         [t['name'] for t in by_subject['Mathematics']['topics']])
        self.assertEqual(['Forces'],
                         [t['name'] for t in by_subject['Science']['topics']])

    def test_each_topic_reports_what_it_holds(self):
        topic = self._topic('Addition', 'add-inv')
        self._question(topic)
        self._question(topic, '2 + 2 = ?')
        self._topic('Carrying', 'carry-inv', parent=topic)

        entry = topic_inventory()[0]['topics']
        by_name = {t['name']: t for t in entry}
        self.assertEqual(2, by_name['Addition']['questions'])
        self.assertEqual(1, by_name['Addition']['subtopics'])

    def test_a_subject_reports_its_total(self):
        a = self._topic('Addition', 'add-tot')
        b = self._topic('Division', 'div-tot')
        self._question(a)
        self._question(b)

        entry = topic_inventory()[0]
        self.assertEqual(2, entry['questions'])

    def test_the_inventory_can_be_narrowed_to_one_subject(self):
        self._topic('Fractions', 'fr-nar', subject=self.maths)
        self._topic('Forces', 'forces-nar', subject=self.science)

        inventory = topic_inventory(subject_ids=[self.maths.id])
        self.assertEqual(['Mathematics'], [s['subject'] for s in inventory])


class ExactClashTests(TopicMergeTestBase):
    """Only literal name collisions are reported — no fuzzy matching."""

    def test_two_topics_with_the_same_name_are_reported(self):
        a = self._topic('Addition', 'add-1')
        b = self._topic('Addition', 'add-2')

        clash = exact_name_clashes()[0]
        self.assertEqual({a.id, b.id}, {m['id'] for m in clash['members']})

    def test_case_and_spacing_do_not_hide_a_clash(self):
        # The picker shows both as the same word, so they collide.
        a = self._topic('Addition', 'add-3')
        b = self._topic(' addition ', 'add-4')

        clash = exact_name_clashes()[0]
        self.assertEqual({a.id, b.id}, {m['id'] for m in clash['members']})

    def test_singular_and_plural_are_NOT_treated_as_the_same(self):
        # "Fraction" vs "Fractions" may well be a duplicate — but that is a
        # judgement call, and a merge cannot be undone. Guessing here would
        # also collapse "Mass"/"Masses" and "Time"/"Times".
        self._topic('Fraction', 'fr-sing')
        self._topic('Fractions', 'fr-plur')

        self.assertEqual([], exact_name_clashes())

    def test_the_same_name_under_two_subjects_is_not_a_clash(self):
        # Both subjects legitimately teach Fractions.
        self._topic('Fractions', 'fr-m', subject=self.maths)
        self._topic('Fractions', 'fr-s', subject=self.science)

        self.assertEqual([], exact_name_clashes())

    def test_a_unique_name_is_not_reported(self):
        self._topic('Decimals', 'dec-solo')
        self.assertEqual([], exact_name_clashes())


class StructuralIssueTests(TopicMergeTestBase):
    """Findings that hold regardless of anyone's naming preferences."""

    def test_a_duplicate_name_is_reported(self):
        self._topic('Addition', 'add-s1')
        self._topic('Addition', 'add-s2')
        self.assertIn('DUPLICATE-NAME', self._codes())

    def test_a_topic_with_nothing_in_it_is_reported(self):
        self._topic('Ghost', 'ghost-1')
        self.assertIn('EMPTY-TOPIC', self._codes())

    def test_a_topic_holding_questions_is_not_called_empty(self):
        topic = self._topic('Addition', 'add-full')
        self._question(topic)
        self.assertNotIn('EMPTY-TOPIC', self._codes())

    def test_a_parent_topic_with_no_questions_is_not_called_empty(self):
        parent = self._topic('Number', 'num-parent')
        self._topic('Addition', 'add-child', parent=parent)
        codes = [i['code'] for i in structural_issues()
                 if i['topics'][0]['id'] == parent.id]
        self.assertNotIn('EMPTY-TOPIC', codes)

    def test_an_inactive_topic_still_holding_questions_is_reported(self):
        # Its questions are hidden without having been moved anywhere.
        topic = self._topic('Retired', 'retired-1', active=False)
        self._question(topic)
        self.assertIn('INACTIVE-WITH-QUESTIONS', self._codes())

    def test_an_inactive_empty_topic_is_not_reported_as_hiding_questions(self):
        self._topic('Retired', 'retired-2', active=False)
        self.assertNotIn('INACTIVE-WITH-QUESTIONS', self._codes())

    def test_a_subtopic_whose_parent_sits_in_another_subject_is_reported(self):
        parent = self._topic('Number', 'num-sci', subject=self.science)
        self._topic('Addition', 'add-cross', subject=self.maths, parent=parent)
        self.assertIn('PARENT-IN-OTHER-SUBJECT', self._codes())

    def test_a_tidy_tree_reports_nothing(self):
        parent = self._topic('Number', 'num-ok')
        child = self._topic('Addition', 'add-ok', parent=parent)
        self._question(child)
        self.assertEqual([], structural_issues())


class SubjectClashTests(TopicMergeTestBase):
    """Two subjects named Mathematics is why the picker lists it twice."""

    def test_two_subjects_with_the_same_name_are_reported(self):
        other = Subject.objects.create(name='Mathematics', slug='maths-two')
        clash = subject_name_clashes()[0]
        self.assertEqual({self.maths.id, other.id}, {m['id'] for m in clash})

    def test_a_school_copy_is_reported_with_its_school_named(self):
        # A school's own custom subject is not necessarily a mistake, so the
        # school is shown and the call is left to a human.
        school = School.objects.create(name='Wizards', slug='wizards-tm')
        Subject.objects.create(name='Mathematics', slug='maths-sch',
                               school=school)
        clash = subject_name_clashes()[0]
        schools = {m['school'] for m in clash}
        self.assertIn('Wizards', schools)
        self.assertIn(None, schools)

    def test_distinct_subject_names_are_not_reported(self):
        self.assertEqual([], subject_name_clashes())


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

    def test_a_merged_name_clash_stops_being_reported(self):
        keep = self._topic('Addition', 'add-k6')
        dupe = self._topic('Addition', 'add-d6')
        self._question(keep)

        merge_topics(keep, [dupe], actor=self.admin)

        self.assertEqual([], exact_name_clashes())
        self.assertNotIn('DUPLICATE-NAME', self._codes())


class NormalisedNameTests(TestCase):
    """The comparison key — every rule replayable by hand, no scoring."""

    def test_case_and_surrounding_space_are_discarded(self):
        self.assertEqual(normalised_name('  Fractions '),
                         normalised_name('fractions'))

    def test_an_ampersand_reads_as_and(self):
        self.assertEqual(normalised_name('Ratio & Proportion'),
                         normalised_name('Ratio and Proportion'))

    def test_punctuation_is_not_a_difference(self):
        self.assertEqual(normalised_name('Time: 24-hour clock'),
                         normalised_name('Time 24 hour clock'))

    def test_filler_words_are_discarded(self):
        self.assertEqual(normalised_name('Addition of Fractions'),
                         normalised_name('Addition Fractions'))

    def test_a_plural_reads_as_its_singular(self):
        self.assertEqual(normalised_name('Place Values'),
                         normalised_name('Place Value'))

    def test_a_y_plural_reads_as_its_singular(self):
        self.assertEqual(normalised_name('Probabilities'),
                         normalised_name('Probability'))

    def test_a_double_s_word_is_left_whole(self):
        # "Mass" must not be trimmed to "Mas"; it may still meet "Masses".
        self.assertEqual(normalised_name('Mass'), 'mass')
        self.assertEqual(normalised_name('Masses'), 'mass')

    def test_a_short_word_is_left_whole(self):
        # Trimming "is" to "i" would collide with anything else two letters long.
        self.assertEqual(normalised_name('Is'), 'is')

    def test_word_order_is_discarded(self):
        self.assertEqual(normalised_name('Fractions & Decimals'),
                         normalised_name('Decimals and Fraction'))

    def test_different_topics_keep_different_keys(self):
        self.assertNotEqual(normalised_name('Addition'),
                            normalised_name('Subtraction'))

    def test_a_name_of_nothing_but_filler_reduces_to_empty(self):
        self.assertEqual(normalised_name('the and of'), '')


class NearDuplicateTests(TopicMergeTestBase):
    """Names that differ only in spelling — a question for a human, not a merge."""

    def test_a_plural_twin_is_reported(self):
        self._topic('Place Value', 'pv-nd')
        self._topic('Place Values', 'pvs-nd')

        clusters = near_duplicate_names()
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0]['names'], ['place value', 'place values'])

    def test_an_ampersand_twin_is_reported(self):
        self._topic('Ratio & Proportion', 'rp1-nd')
        self._topic('Ratio and Proportion', 'rp2-nd')

        self.assertEqual(len(near_duplicate_names()), 1)

    def test_the_cluster_reports_what_each_row_holds(self):
        keep = self._topic('Fractions', 'fr1-nd')
        self._topic('Fraction', 'fr2-nd')
        self._question(keep)

        cluster = near_duplicate_names()[0]
        self.assertEqual(cluster['total_questions'], 1)
        # Busiest row first — the obvious survivor is the one to read first.
        self.assertEqual(cluster['members'][0]['id'], keep.id)

    def test_twins_under_different_strands_are_still_one_cluster(self):
        number = self._topic('Number', 'num-nd')
        algebra = self._topic('Algebra', 'alg-nd')
        self._topic('Indices', 'ind1-nd', parent=number)
        self._topic('Index', 'ind2-nd', parent=algebra)
        self._topic('Indice', 'ind3-nd', parent=algebra)

        clusters = near_duplicate_names()
        names = [c['names'] for c in clusters]
        self.assertIn(['indice', 'indices'], names)

    def test_the_same_name_in_two_subjects_is_not_a_cluster(self):
        self._topic('Fractions', 'fr-m-nd', subject=self.maths)
        self._topic('Fraction', 'fr-s-nd', subject=self.science)

        self.assertEqual(near_duplicate_names(), [])

    def test_an_exact_clash_alone_is_left_to_the_exact_matcher(self):
        # Two rows literally named "Addition" are DUPLICATE-NAME, already
        # reported; repeating them here would bury the new findings.
        self._topic('Addition', 'a1-nd')
        self._topic('Addition', 'a2-nd')

        self.assertEqual(near_duplicate_names(), [])
        self.assertEqual(len(exact_name_clashes()), 1)

    def test_an_exact_clash_inside_a_near_cluster_is_still_reported(self):
        self._topic('Addition', 'a3-nd')
        self._topic('Addition', 'a4-nd')
        self._topic('Additions', 'a5-nd')

        cluster = near_duplicate_names()[0]
        self.assertEqual(cluster['names'], ['addition', 'additions'])
        self.assertEqual(len(cluster['members']), 3)

    def test_names_that_reduce_to_nothing_are_not_grouped(self):
        # Two junk names both reduce to '' — that is not evidence they match.
        self._topic('the', 'the-nd')
        self._topic('of', 'of-nd')

        self.assertEqual(near_duplicate_names(), [])

    def test_a_tidy_tree_reports_nothing(self):
        self._topic('Addition', 'add-nd')
        self._topic('Subtraction', 'sub-nd')

        self.assertEqual(near_duplicate_names(), [])

    def test_the_search_can_be_narrowed_to_one_subject(self):
        self._topic('Fractions', 'fr1-sc-nd', subject=self.maths)
        self._topic('Fraction', 'fr2-sc-nd', subject=self.maths)
        self._topic('Forces', 'fo1-sc-nd', subject=self.science)
        self._topic('Force', 'fo2-sc-nd', subject=self.science)

        clusters = near_duplicate_names([self.science.id])
        self.assertEqual([c['subject'] for c in clusters], ['Science'])

    def test_a_reported_cluster_can_be_merged_away(self):
        keep = self._topic('Place Value', 'pv1-mg')
        gone = self._topic('Place Values', 'pv2-mg')
        self._question(gone)

        merge_topics(keep, [gone])

        self.assertEqual(near_duplicate_names(), [])
        self.assertEqual(Question.objects.filter(topic=keep).count(), 1)
