"""The hub counts a question against its TOPIC's subject, not its level's.

``Question.level`` is a year / difficulty band that happens to carry a
``subject`` FK. That FK was NULL on Year levels 1-9 for most of this app's life
(``setup_dev`` created them with a display name only; migration 0101 backfilled
Year 10 alone), so joining the hub's counters through the level counted almost
nothing — a student who had answered 4 of 205 questions was shown "80%" because
the denominator only saw the five Year 10 questions.

Joining through the topic fixes the count AND makes the pending Level.subject
backfill invisible to students, which is what the invariance test below pins:
filling in Level.subject must not move a single hub number.
"""

from django.test import TestCase

from accounts.models import CustomUser
from classroom.models import Level, Subject, Topic
from classroom.views import (
    _annotate_apps_with_progress, _compute_subject_progress,
    _subject_has_questions,
)
from maths.models import Question, StudentAnswer


def _backfill_level_subjects(subject):
    """Exactly what the pending migration does."""
    return Level.objects.filter(
        subject__isnull=True, level_number__lt=200,
    ).update(subject=subject)


class HubSubjectJoinTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.maths, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})
        cls.topic = Topic.objects.create(
            subject=cls.maths, name='Number', slug='number')

        # Year 10 — the one level migration 0101 gave a subject.
        cls.y10 = Level.objects.create(
            level_number=10, display_name='Year 10', subject=cls.maths)
        # Year 5 — as setup_dev creates it: subject is NULL.
        cls.y5 = Level.objects.create(level_number=5, display_name='Year 5')

        cls.student = CustomUser.objects.create_user(
            username='hubstudent', password='pw1!',
            email='wlhtestmails+hub@gmail.com')

    def _make_questions(self, level, n, topic=True):
        for i in range(n):
            Question.objects.create(
                question_text=f'{level.display_name} Q{i}',
                level=level,
                topic=self.topic if topic else None,
            )

    # -- the bug this fixes --------------------------------------------

    def test_questions_count_even_when_their_level_has_no_subject(self):
        self._make_questions(self.y5, 200)

        progress = _compute_subject_progress(
            self.student, [self.maths.id], school=None)

        self.assertEqual(progress['total'], 200)

    def test_card_is_enabled_from_topic_subject_alone(self):
        self._make_questions(self.y5, 1)
        self.assertTrue(_subject_has_questions(self.maths, school=None))

    # -- the invariant that lets the backfill ship ---------------------

    def test_backfilling_level_subject_does_not_move_hub_numbers(self):
        self._make_questions(self.y10, 5)
        self._make_questions(self.y5, 200)
        for q in Question.objects.filter(level=self.y10)[:4]:
            StudentAnswer.objects.create(
                student=self.student, question=q, is_correct=True)

        before_gate = _subject_has_questions(self.maths, school=None)
        before = _compute_subject_progress(
            self.student, [self.maths.id], school=None)

        updated = _backfill_level_subjects(self.maths)
        self.assertEqual(updated, 1, 'the Year 5 level should have been backfilled')

        after_gate = _subject_has_questions(self.maths, school=None)
        after = _compute_subject_progress(
            self.student, [self.maths.id], school=None)

        self.assertEqual(before, after)
        self.assertEqual(before_gate, after_gate)
        # And the figure is the true one, not the pre-fix 4-of-5.
        self.assertEqual(after, {'completed': 4, 'total': 205, 'pct': 2})

    # -- the topic-less fallback ---------------------------------------

    def test_topicless_question_falls_back_to_its_level_subject(self):
        self._make_questions(self.y10, 3, topic=False)

        progress = _compute_subject_progress(
            self.student, [self.maths.id], school=None)

        self.assertEqual(progress['total'], 3)

    def test_topicless_question_on_a_subjectless_level_is_not_counted(self):
        """Nothing ties it to a subject, so it must not be attributed to one."""
        self._make_questions(self.y5, 3, topic=False)

        progress = _compute_subject_progress(
            self.student, [self.maths.id], school=None)

        self.assertEqual(progress['total'], 0)

    def test_no_double_counting_across_the_two_branches(self):
        self._make_questions(self.y10, 4)          # topic set, level subject set
        self._make_questions(self.y10, 2, topic=False)   # topic null, level set

        progress = _compute_subject_progress(
            self.student, [self.maths.id], school=None)

        self.assertEqual(progress['total'], 6)

    # -- the per-subject rollup uses the same rule ---------------------

    def test_app_rollup_matches_the_single_subject_figure(self):
        from classroom.models import SubjectApp

        self._make_questions(self.y5, 7)
        app = SubjectApp.objects.create(
            name='Maths Hub', slug='maths-hub', subject=self.maths,
            is_active=True, is_coming_soon=False)

        _annotate_apps_with_progress([app], self.student)

        self.assertEqual(app.progress['total'], 7)
