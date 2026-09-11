"""A merged-away topic id redirects to its survivor instead of 404ing.

``topic_merge.merge_topics`` deletes the absorbed topic once its rows are
re-pointed. Links already out in the world — a bookmark, an open tab, a
browser history entry — cannot be re-pointed, so before ``TopicAlias`` every
one of them became a bare 404 the moment a merge ran. That is what took
``/maths/level/6/topic/198/quiz/`` off the air on 10 Sep for a topic merged on
3 Sep: "Rounding and Decimals" had been absorbed into "Decimals".

The 404 is still the right answer for an id that never existed. These tests
pin both halves.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from classroom.models import Level, Subject, Topic, TopicAlias
from classroom.topic_merge import merge_topics
from maths.models import Answer, Question

User = get_user_model()


class TopicAliasTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='alias-student', email='as@test.com', password='pass1234')
        cls.maths = Subject.objects.create(name='Mathematics', slug='maths-alias')
        cls.level = Level.objects.create(level_number=96, display_name='Y96')

    def _topic(self, name, slug):
        topic = Topic.objects.create(name=name, slug=slug, subject=self.maths)
        topic.levels.add(self.level)
        return topic

    def _question(self, topic):
        """A question the quiz can actually serve, so a hit renders rather than
        bouncing to home with 'no questions available'."""
        q = Question.objects.create(
            level=self.level, topic=topic, question_text='0.5 rounds to?',
            question_type='multiple_choice')
        Answer.objects.create(question=q, answer_text='1', is_correct=True)
        Answer.objects.create(question=q, answer_text='0', is_correct=False)
        return q


class MergeRecordsTheRetiredId(TopicAliasTestBase):

    def test_merge_writes_an_alias_for_each_absorbed_topic(self):
        keep = self._topic('Decimals', 'decimals-a')
        gone = self._topic('Rounding and Decimals', 'rounding-a')
        gone_id = gone.id

        summary = merge_topics(keep, [gone])

        self.assertEqual(summary['aliased'], 1)
        alias = TopicAlias.objects.get(old_topic_id=gone_id)
        self.assertEqual(alias.topic_id, keep.id)
        self.assertEqual(alias.old_name, 'Rounding and Decimals')
        self.assertEqual(alias.old_slug, 'rounding-a')

    def test_resolve_returns_the_survivor(self):
        keep = self._topic('Decimals', 'decimals-b')
        gone = self._topic('Rounding and Decimals', 'rounding-b')
        gone_id = gone.id
        merge_topics(keep, [gone])

        self.assertEqual(TopicAlias.resolve(gone_id), keep)

    def test_resolve_is_none_for_an_id_that_never_existed(self):
        self.assertIsNone(TopicAlias.resolve(9_999_999))

    def test_a_topic_merged_twice_still_resolves(self):
        """A → B, then B → C. The alias for A must follow to C.

        The absorbed row's aliases are ordinary rows referencing a topic, so
        the merge's own related-objects walk re-points them. Without that, the
        second merge would cascade-delete A's alias and A would 404 again.
        """
        first = self._topic('Rounding', 'chain-a')
        middle = self._topic('Rounding and Decimals', 'chain-b')
        final = self._topic('Decimals', 'chain-c')
        first_id, middle_id = first.id, middle.id

        merge_topics(middle, [first])
        merge_topics(final, [middle])

        self.assertEqual(TopicAlias.resolve(first_id), final)
        self.assertEqual(TopicAlias.resolve(middle_id), final)


class QuizUrlSurvivesTheMerge(TopicAliasTestBase):

    def setUp(self):
        self.client.force_login(self.student)

    def _quiz_url(self, topic_id):
        return reverse('topic_quiz', kwargs={
            'subject': 'maths', 'level_number': self.level.level_number,
            'topic_id': topic_id})

    def test_the_old_quiz_link_redirects_to_the_survivors_quiz(self):
        keep = self._topic('Decimals', 'decimals-q')
        gone = self._topic('Rounding and Decimals', 'rounding-q')
        self._question(gone)
        gone_id = gone.id

        merge_topics(keep, [gone])

        response = self.client.get(self._quiz_url(gone_id))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], self._quiz_url(keep.id))

    def test_the_redirect_target_actually_serves(self):
        """The whole point is a working quiz, not a tidier 404."""
        keep = self._topic('Decimals', 'decimals-s')
        gone = self._topic('Rounding and Decimals', 'rounding-s')
        self._question(gone)          # moves to keep during the merge
        gone_id = gone.id

        merge_topics(keep, [gone])

        response = self.client.get(self._quiz_url(gone_id), follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['topic'], keep)

    def test_results_link_redirects_too(self):
        keep = self._topic('Decimals', 'decimals-r')
        gone = self._topic('Rounding and Decimals', 'rounding-r')
        gone_id = gone.id
        merge_topics(keep, [gone])

        url = reverse('topic_results', kwargs={
            'subject': 'maths', 'level_number': self.level.level_number,
            'topic_id': gone_id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('topic_results', kwargs={
            'subject': 'maths', 'level_number': self.level.level_number,
            'topic_id': keep.id}))

    def test_an_id_that_never_existed_still_404s(self):
        """An alias makes a MOVED topic reachable. It does not invent one."""
        response = self.client.get(self._quiz_url(9_999_999))
        self.assertEqual(response.status_code, 404)

    def test_a_live_topic_is_served_not_redirected(self):
        topic = self._topic('Decimals', 'decimals-live')
        self._question(topic)

        response = self.client.get(self._quiz_url(topic.id))
        self.assertEqual(response.status_code, 200)

    def test_an_alias_never_shadows_a_live_topic(self):
        """A live id wins over any alias row claiming it."""
        keep = self._topic('Decimals', 'decimals-sh')
        live = self._topic('Percentages', 'percentages-sh')
        self._question(live)
        TopicAlias.objects.create(old_topic_id=live.id, topic=keep,
                                  old_name='stale', old_slug='stale')

        response = self.client.get(self._quiz_url(live.id))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['topic'], live)


class TheReportedUrl(TestCase):
    """The exact incident, reproduced end to end.

    10 Sep 20:02, a Year 6 student opened
    ``/maths/level/6/topic/198/quiz/`` and got a bare 404. Topic 198
    "Rounding and Decimals" had been absorbed into 160 "Decimals" a week
    earlier, on 3 Sep 06:04, by one of 32 merges in a single
    ``merge_maths_topics`` run that retired 59 maths topic ids.

    Ids are pinned to the real ones so this reads as the incident it is.
    """

    DEAD_URL = '/maths/level/6/topic/198/quiz/'
    LIVE_URL = '/maths/level/6/topic/160/quiz/'

    def setUp(self):
        self.student = User.objects.create_user(
            username='dihansa-repro', email='dr@test.com', password='pass1234')
        self.client.force_login(self.student)

        maths = Subject.objects.create(name='Mathematics', slug='maths-repro')
        self.level = Level.objects.create(level_number=6, display_name='Year 6')

        self.keep = Topic.objects.create(
            id=160, name='Decimals', slug='decimals-repro', subject=maths)
        self.gone = Topic.objects.create(
            id=198, name='Rounding and Decimals', slug='rounding-repro',
            subject=maths)
        for topic in (self.keep, self.gone):
            topic.levels.add(self.level)

        question = Question.objects.create(
            level=self.level, topic=self.gone, question_text='Round 0.5',
            question_type='multiple_choice')
        Answer.objects.create(question=question, answer_text='1', is_correct=True)
        Answer.objects.create(question=question, answer_text='0', is_correct=False)

    def test_before_the_alias_the_url_is_a_dead_end(self):
        """Delete 198 without recording where it went — the old behaviour."""
        self.gone.delete()

        self.assertEqual(self.client.get(self.DEAD_URL).status_code, 404)

    def test_after_the_merge_the_url_redirects_and_serves(self):
        merge_topics(self.keep, [self.gone])

        response = self.client.get(self.DEAD_URL)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], self.LIVE_URL)

        followed = self.client.get(self.DEAD_URL, follow=True)
        self.assertEqual(followed.status_code, 200)
        self.assertEqual(followed.context['topic'], self.keep)
        self.assertContains(followed, 'Decimals')
