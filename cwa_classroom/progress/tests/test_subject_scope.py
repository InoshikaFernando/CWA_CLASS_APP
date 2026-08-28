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

    def test_default_slug_homework_counts_for_whatever_class_it_is_in(self):
        """A REVERSAL of an earlier assertion here, on purpose.

        This test used to require that a maths-slugged homework sitting in the
        coding class be excluded. That is no longer right, because
        Homework.subject_slug DEFAULTS to 'mathematics': the value means "not
        stated" far more often than it means "this is maths", every pre-refactor
        row having been back-filled with it.

        Excluding those rows from a non-maths report would empty every Science
        or Languages class the moment its subject was set — the report would
        say the child did nothing, which reads as fact rather than as a missing
        configuration. Counting them costs an occasional over-report of one
        genuinely-maths item, and that disappears the moment the homework says
        which subject it is.
        """
        data = self._data([self.coding_class.id])

        self.assertEqual(data['totals']['homework_attempted'], 2)
        self.assertEqual(
            {row['topic'] for row in data['topics']} - {'Unclassified'}, set(),
            'a coding report should carry no maths topic rows',
        )

    def test_a_maths_report_takes_the_default_rows_as_its_own(self):
        """For maths the default and the truth coincide, so nothing changes."""
        data = self._data([self.maths_class.id])

        self.assertEqual(data['totals']['homework_attempted'], 1)

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


class QuizzesFollowTheSubjectTests(TestCase):
    """A coding report carries coding quizzes, not nothing and not maths ones.

    Quizzes were treated as maths-only, because the maths quiz app was the only
    source read. BrainBuzz sessions carry a classroom.Subject FK, so the quiz
    strand can and should follow the report's subject.
    """

    @classmethod
    def setUpTestData(cls):
        from brainbuzz.models import (
            BrainBuzzAnswer, BrainBuzzParticipant, BrainBuzzSession,
            BrainBuzzSessionQuestion,
        )

        cls.school = make_school()
        cls.student = make_user('qz_student', first_name='Avisha')
        cls.host = make_user('qz_host', 'teacher')
        cls.maths = _subject('mathematics', 'Mathematics')
        cls.coding = _subject('coding', 'Coding')

        cls.start, cls.end = periods.previous_week(periods.today())
        when = timezone.make_aware(timezone.datetime.combine(
            cls.start + timedelta(days=1),
            timezone.datetime.min.time().replace(hour=10),
        ))

        def play(subject, code, correct, total):
            session = BrainBuzzSession.objects.create(
                code=code, host=cls.host, subject=subject, status='finished',
            )
            participant = BrainBuzzParticipant.objects.create(
                session=session, student=cls.student, nickname=f'n{code}',
            )
            for index in range(total):
                question = BrainBuzzSessionQuestion.objects.create(
                    session=session, order=index, question_text='q',
                    question_type='multiple_choice', options_json={},
                    source_model='MathsQuestion', source_id=1,
                )
                answer = BrainBuzzAnswer.objects.create(
                    participant=participant, session_question=question,
                    time_taken_ms=1000, is_correct=index < correct,
                )
                BrainBuzzAnswer.objects.filter(pk=answer.pk).update(
                    submitted_at=when,
                )

        play(cls.coding, 'CODE01', correct=3, total=4)
        play(cls.maths, 'MATH01', correct=1, total=4)

    def _quizzes(self, slugs):
        from progress.reports import quizzes_section

        return quizzes_section(self.student, self.start, self.end, slugs)

    def test_a_coding_report_carries_the_coding_quiz(self):
        section = self._quizzes({'coding'})

        self.assertEqual(section['attempted'], 1)
        self.assertEqual(section['items'][0]['name'], 'Coding quiz')
        self.assertEqual(section['items'][0]['best_pct'], 75)

    def test_a_coding_report_does_not_carry_the_maths_quiz(self):
        section = self._quizzes({'coding'})

        self.assertEqual(
            [item['name'] for item in section['items']], ['Coding quiz'],
        )

    def test_a_maths_report_carries_the_maths_quiz(self):
        section = self._quizzes({'mathematics'})

        self.assertEqual(
            [item['name'] for item in section['items']], ['Mathematics quiz'],
        )
        self.assertEqual(section['items'][0]['best_pct'], 25)

    def test_unscoped_carries_both(self):
        section = self._quizzes(None)

        self.assertEqual(section['attempted'], 2)

    def test_a_session_played_once_reports_no_gain(self):
        """First and best are the same figure; claiming improvement would lie."""
        section = self._quizzes({'coding'})

        item = section['items'][0]
        self.assertEqual(item['first_pct'], item['best_pct'])
        self.assertEqual(item['gain_pct'], 0)


class SubjectPracticeTests(TestCase):
    """Practice a student does in the subject's own app, not as homework.

    progress/README.md has listed coding.StudentProblemSubmission as a source
    since CPP-388, and nothing read it: a student who spent a week on coding
    exercises got a report saying they had done nothing. That is the same
    complaint that added the maths times-tables strand.
    """

    @classmethod
    def setUpTestData(cls):
        from coding.models import (
            CodingExercise, CodingLanguage, CodingProblem, CodingTopic,
            StudentExerciseSubmission, StudentProblemSubmission, TopicLevel,
        )

        cls.student = make_user('sp_student', first_name='Avisha')
        cls.start, cls.end = periods.previous_week(periods.today())
        when = timezone.make_aware(timezone.datetime.combine(
            cls.start + timedelta(days=1),
            timezone.datetime.min.time().replace(hour=10),
        ))

        language = CodingLanguage.objects.create(name='Python', slug='python')
        topic = CodingTopic.objects.create(name='Loops', language=language)
        level = TopicLevel.objects.create(
            topic=topic, level_choice=TopicLevel.BEGINNER,
        )
        exercise = CodingExercise.objects.create(
            title='For loops', topic_level=level, description='d',
        )
        row = StudentExerciseSubmission.objects.create(
            student=cls.student, exercise=exercise, code_submitted='x',
            is_completed=True,
        )
        StudentExerciseSubmission.objects.filter(pk=row.pk).update(
            submitted_at=when,
        )

        problem = CodingProblem.objects.create(
            title='FizzBuzz', language=language, description='d',
        )
        for attempt, (visible, hidden) in enumerate([(1, 0), (2, 2)], start=1):
            StudentProblemSubmission.objects.create(
                student=cls.student, problem=problem, attempt_number=attempt,
                code_submitted='x', visible_passed=visible, visible_total=2,
                hidden_passed=hidden, hidden_total=2, submitted_at=when,
            )

    def _section(self, slugs):
        from progress.reports import subject_practice_section

        return subject_practice_section(
            self.student, self.start, self.end, slugs,
        )

    def test_a_coding_report_carries_the_practice(self):
        section = self._section({'coding'})

        self.assertEqual(section['items'], 2)
        self.assertEqual(
            section['sections'][0]['label'], 'Coding practice',
        )

    def test_a_retried_problem_reports_the_gain(self):
        """1 of 4 tests, then 4 of 4 — the improvement the section exists for."""
        section = self._section({'coding'})

        rows = {r['name']: r for r in section['sections'][0]['rows']}
        self.assertEqual(rows['FizzBuzz']['first_pct'], 25)
        self.assertEqual(rows['FizzBuzz']['best_pct'], 100)
        self.assertEqual(rows['FizzBuzz']['gain_pct'], 75)

    def test_a_completed_exercise_is_full_marks_with_no_gain(self):
        """An exercise has no partial credit: it was finished or it was not."""
        section = self._section({'coding'})

        rows = {r['name']: r for r in section['sections'][0]['rows']}
        self.assertEqual(rows['For loops']['best_pct'], 100)
        self.assertEqual(rows['For loops']['gain_pct'], 0)

    def test_a_maths_report_carries_none_of_it(self):
        self.assertEqual(self._section({'mathematics'})['items'], 0)

    def test_an_unscoped_report_carries_none_of_it(self):
        """Only meaningful once the report knows its subject."""
        self.assertEqual(self._section(None)['items'], 0)

    def test_it_counts_as_activity(self):
        from progress.reports import build_report_data

        data = build_report_data(
            self.student, periods.WEEKLY, self.start, self.end,
            classroom_ids=None,
        )
        self.assertIn('subject_practice', data)


class OverallExcludesCompletionOnlyTests(TestCase):
    """Finishing something is effort; it must not set the achievement figure.

    Found on the test site: a coding row read 90% homework and 96% Overall,
    because 97 of 102 counted items were coding exercises and an exercise
    scores 100 for being finished. The headline had become a completion rate
    sitting in the same column as a maths average that really is accuracy.
    """

    @classmethod
    def setUpTestData(cls):
        from coding.models import (
            CodingExercise, CodingLanguage, CodingProblem, CodingTopic,
            StudentExerciseSubmission, StudentProblemSubmission, TopicLevel,
        )

        cls.student = make_user('ov_student', first_name='Aadya')
        cls.start, cls.end = periods.previous_week(periods.today())
        when = timezone.make_aware(timezone.datetime.combine(
            cls.start + timedelta(days=1),
            timezone.datetime.min.time().replace(hour=10),
        ))

        language = CodingLanguage.objects.create(name='Python', slug='py-ov')
        topic = CodingTopic.objects.create(name='Loops', language=language)
        level = TopicLevel.objects.create(
            topic=topic, level_choice=TopicLevel.BEGINNER,
        )

        # Ten finished exercises: a lot of effort, all scoring 100 for "done".
        for index in range(10):
            exercise = CodingExercise.objects.create(
                title=f'Exercise {index}', topic_level=level, description='d',
            )
            row = StudentExerciseSubmission.objects.create(
                student=cls.student, exercise=exercise, code_submitted='x',
                is_completed=True,
            )
            StudentExerciseSubmission.objects.filter(pk=row.pk).update(
                submitted_at=when,
            )

        # One graded problem, done badly.
        problem = CodingProblem.objects.create(
            title='FizzBuzz', language=language, description='d',
        )
        StudentProblemSubmission.objects.create(
            student=cls.student, problem=problem, attempt_number=1,
            code_submitted='x', visible_passed=1, visible_total=2,
            hidden_passed=0, hidden_total=2, submitted_at=when,
        )

    def _section(self):
        from progress.reports import subject_practice_section

        return subject_practice_section(
            self.student, self.start, self.end, {'coding'},
        )

    def test_all_the_work_is_still_counted_as_effort(self):
        section = self._section()

        self.assertEqual(section['items'], 11)

    def test_only_the_graded_work_reaches_the_headline(self):
        section = self._section()

        self.assertEqual(section['scored_items'], 1)
        # The problem passed 1 of 4 tests.
        self.assertEqual(section['scored_avg_best_pct'], 25)

    def test_ten_finished_exercises_do_not_drown_out_one_bad_problem(self):
        """The regression itself: without the split this averaged ~93%."""
        section = self._section()

        self.assertLess(section['scored_avg_best_pct'], 50)

    def test_the_excluded_effort_still_counts_as_activity(self):
        """Left out of the average, still counted as work done.

        activity_items is what has_activity reads, so dropping the exercises
        from it would tell a child a week of coding did not happen.
        """
        from progress.reports import build_report_data

        school = make_school(name='Ov School', slug='ov-school')
        room = make_classroom(school, name='Coding', code='OV000001')
        room.subject = _subject('coding', 'Coding')
        room.save(update_fields=['subject'])
        enrol(room, self.student)

        data = build_report_data(
            self.student, periods.WEEKLY, self.start, self.end,
            classroom_ids=[room.id],
        )

        self.assertEqual(data['subject_practice']['items'], 11)
        self.assertEqual(data['subject_practice']['scored_items'], 1)
        # 10 unscored exercises + the 1 scored problem.
        self.assertEqual(data['totals']['activity_items'], 11)
        # The headline is the problem's mark, not the completion rate.
        self.assertEqual(data['totals']['overall_avg_pct'], 25)


class DepartmentDecidesTheSubjectTests(TestCase):
    """Mapping a department to a subject applies to reports immediately.

    Requiring someone to also run a backfill afterwards is a way to have the
    setting look applied while the reports quietly disagree with it.
    """

    @classmethod
    def setUpTestData(cls):
        from classroom.models import Department

        cls.school = make_school(name='Dept School', slug='dept-school')
        cls.coding = _subject('coding', 'Coding')
        cls.maths = _subject('mathematics', 'Mathematics')
        cls.dept = Department.objects.create(
            name='Information Technology', slug='it', school=cls.school,
        )

    def _room(self, name, code, subject=None):
        from progress.reports import covered_subject_slugs

        room = make_classroom(self.school, name=name, code=code)
        room.department = self.dept
        room.subject = subject
        room.save(update_fields=['department', 'subject'])
        return room, covered_subject_slugs

    def test_a_class_with_no_subject_takes_its_departments(self):
        self.dept.subjects.set([self.coding])
        room, covered = self._room('Scratch 05', 'DP000001')

        self.assertEqual(covered([room]), {'coding'})

    def test_the_classs_own_subject_still_wins(self):
        self.dept.subjects.set([self.coding])
        room, covered = self._room('Maths in IT', 'DP000002', subject=self.maths)

        self.assertEqual(covered([room]), {'mathematics'})

    def test_a_department_mapped_to_two_subjects_decides_nothing(self):
        """Two is not an answer, and unscoped is the safe fallback."""
        self.dept.subjects.set([self.coding, self.maths])
        room, covered = self._room('Mixed', 'DP000003')

        self.assertIsNone(covered([room]))

    def test_a_department_mapped_to_nothing_decides_nothing(self):
        self.dept.subjects.set([])
        room, covered = self._room('Unmapped', 'DP000004')

        self.assertIsNone(covered([room]))
