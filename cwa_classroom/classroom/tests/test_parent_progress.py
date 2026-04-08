"""
Unit tests for ParentProgressView (CPP-69).

Covers:
- Only approved criteria for the child's school are shown
- Non-approved (draft/pending/rejected) criteria are excluded
- Criteria from other schools are excluded
- 'not_assessed' status when no ProgressRecord exists
- Correct status propagation from ProgressRecord
- Overall and per-group totals are accurate
- Unauthenticated access is redirected
- Non-parent role is denied
- No active child renders empty state
- module_activity: maths topics, number puzzles, and future modules
"""
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import (
    School, SchoolStudent, Subject, Level,
    ParentStudent, ProgressCriteria, ProgressRecord,
)
from maths.models import Question as MathsQuestion, Answer as MathsAnswer, StudentAnswer
from number_puzzles.models import NumberPuzzleLevel, StudentPuzzleProgress


class ParentProgressTestBase(TestCase):
    """Shared fixtures for progress view tests."""

    @classmethod
    def setUpTestData(cls):
        # Roles
        cls.parent_role, _ = Role.objects.get_or_create(
            name=Role.PARENT, defaults={'display_name': 'Parent'},
        )
        cls.teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'},
        )
        cls.student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )

        # Teacher / school admin
        cls.teacher = CustomUser.objects.create_user(
            'prog_teacher', 'wlhtestmails+prog_teacher@gmail.com', 'password1!',
            first_name='Alice', last_name='Teacher',
        )
        cls.teacher.roles.add(cls.teacher_role)

        # School
        cls.school = School.objects.create(
            name='Progress School', slug='progress-school-t', admin=cls.teacher,
        )

        # Student
        cls.student = CustomUser.objects.create_user(
            'prog_student', 'wlhtestmails+prog_student@gmail.com', 'password1!',
            first_name='Bobby', last_name='Learner',
        )
        cls.student.roles.add(cls.student_role)
        SchoolStudent.objects.create(school=cls.school, student=cls.student)

        # Parent
        cls.parent = CustomUser.objects.create_user(
            'prog_parent', 'wlhtestmails+prog_parent@gmail.com', 'password1!',
            first_name='Carol', last_name='Parent',
        )
        cls.parent.roles.add(cls.parent_role)

        # Approved link
        cls.link = ParentStudent.objects.create(
            parent=cls.parent,
            student=cls.student,
            school=cls.school,
            relationship='mother',
            is_active=True,
        )

        # Subject & Level
        cls.subject = Subject.objects.create(
            name='Maths', slug='maths-prog',
        )
        cls.level = Level.objects.create(
            level_number=1, display_name='Year 1',
        )

        # Approved criteria (visible to parent)
        cls.criteria_approved = ProgressCriteria.objects.create(
            school=cls.school,
            subject=cls.subject,
            level=cls.level,
            name='Count to 10',
            status='approved',
            created_by=cls.teacher,
        )
        cls.criteria_approved2 = ProgressCriteria.objects.create(
            school=cls.school,
            subject=cls.subject,
            level=cls.level,
            name='Add single digits',
            status='approved',
            created_by=cls.teacher,
        )

        # Non-approved criteria (should NOT appear)
        cls.criteria_draft = ProgressCriteria.objects.create(
            school=cls.school,
            subject=cls.subject,
            level=cls.level,
            name='Draft Criteria',
            status='draft',
            created_by=cls.teacher,
        )
        cls.criteria_pending = ProgressCriteria.objects.create(
            school=cls.school,
            subject=cls.subject,
            level=cls.level,
            name='Pending Criteria',
            status='pending_approval',
            created_by=cls.teacher,
        )

        # Second school with criteria (should NOT appear)
        cls.other_teacher = CustomUser.objects.create_user(
            'other_teacher_prog', 'wlhtestmails+other_t_prog@gmail.com', 'password1!',
        )
        cls.other_school = School.objects.create(
            name='Other School Prog', slug='other-school-prog', admin=cls.other_teacher,
        )
        cls.criteria_other_school = ProgressCriteria.objects.create(
            school=cls.other_school,
            subject=cls.subject,
            level=cls.level,
            name='Other School Criteria',
            status='approved',
            created_by=cls.other_teacher,
        )

    def _login_parent(self):
        self.client.force_login(self.parent)
        # Ensure active child is set
        session = self.client.session
        session['active_child_id'] = self.student.id
        session.save()


class ParentProgressViewAccessTest(ParentProgressTestBase):

    def test_unauthenticated_redirects_to_login(self):
        resp = self.client.get(reverse('parent_progress'))
        self.assertRedirects(resp, f'/accounts/login/?next={reverse("parent_progress")}',
                             fetch_redirect_response=False)

    def test_non_parent_role_denied(self):
        self.client.force_login(self.teacher)
        resp = self.client.get(reverse('parent_progress'))
        # Should be forbidden (403) or redirect away
        self.assertIn(resp.status_code, [302, 403])

    def test_parent_can_access(self):
        self._login_parent()
        resp = self.client.get(reverse('parent_progress'))
        self.assertEqual(resp.status_code, 200)


class ParentProgressViewCriteriaFilterTest(ParentProgressTestBase):

    def setUp(self):
        self._login_parent()

    def test_approved_criteria_appear(self):
        resp = self.client.get(reverse('parent_progress'))
        content = resp.content.decode()
        self.assertIn('Count to 10', content)
        self.assertIn('Add single digits', content)

    def test_draft_criteria_excluded(self):
        resp = self.client.get(reverse('parent_progress'))
        self.assertNotIn('Draft Criteria', resp.content.decode())

    def test_pending_approval_criteria_excluded(self):
        resp = self.client.get(reverse('parent_progress'))
        self.assertNotIn('Pending Criteria', resp.content.decode())

    def test_other_school_criteria_excluded(self):
        resp = self.client.get(reverse('parent_progress'))
        self.assertNotIn('Other School Criteria', resp.content.decode())

    def test_grouped_progress_in_context(self):
        resp = self.client.get(reverse('parent_progress'))
        self.assertIn('grouped_progress', resp.context)
        # Should have one group (same subject+level)
        self.assertEqual(len(resp.context['grouped_progress']), 1)

    def test_overall_total_counts_approved_only(self):
        resp = self.client.get(reverse('parent_progress'))
        overall = resp.context['overall']
        # 2 approved criteria for the school
        self.assertEqual(overall['total'], 2)


class ParentProgressViewStatusTest(ParentProgressTestBase):

    def setUp(self):
        self._login_parent()

    def test_no_record_shows_not_assessed(self):
        """Criteria with no ProgressRecord should appear as 'not_assessed'."""
        resp = self.client.get(reverse('parent_progress'))
        group = resp.context['grouped_progress'][0]
        statuses = [e['status'] for e in group['entries']]
        self.assertIn('not_assessed', statuses)

    def test_achieved_record_shows_achieved(self):
        ProgressRecord.objects.create(
            student=self.student,
            criteria=self.criteria_approved,
            status='achieved',
            recorded_by=self.teacher,
        )
        resp = self.client.get(reverse('parent_progress'))
        group = resp.context['grouped_progress'][0]
        entries_by_criteria = {e['criteria'].id: e for e in group['entries']}
        self.assertEqual(entries_by_criteria[self.criteria_approved.id]['status'], 'achieved')

    def test_in_progress_record_shows_in_progress(self):
        ProgressRecord.objects.create(
            student=self.student,
            criteria=self.criteria_approved,
            status='in_progress',
            recorded_by=self.teacher,
        )
        resp = self.client.get(reverse('parent_progress'))
        group = resp.context['grouped_progress'][0]
        entries_by_criteria = {e['criteria'].id: e for e in group['entries']}
        self.assertEqual(entries_by_criteria[self.criteria_approved.id]['status'], 'in_progress')

    def test_latest_record_used_when_multiple_exist(self):
        """When multiple records exist for the same criteria, the latest (highest ID) is used."""
        ProgressRecord.objects.create(
            student=self.student,
            criteria=self.criteria_approved,
            status='in_progress',
            recorded_by=self.teacher,
        )
        ProgressRecord.objects.create(
            student=self.student,
            criteria=self.criteria_approved,
            status='achieved',
            recorded_by=self.teacher,
        )
        resp = self.client.get(reverse('parent_progress'))
        group = resp.context['grouped_progress'][0]
        entries_by_criteria = {e['criteria'].id: e for e in group['entries']}
        self.assertEqual(entries_by_criteria[self.criteria_approved.id]['status'], 'achieved')

    def test_overall_counts_match_entries(self):
        ProgressRecord.objects.create(
            student=self.student,
            criteria=self.criteria_approved,
            status='achieved',
            recorded_by=self.teacher,
        )
        # criteria_approved2 has no record → not_assessed
        resp = self.client.get(reverse('parent_progress'))
        overall = resp.context['overall']
        self.assertEqual(overall['total'], 2)
        self.assertEqual(overall['achieved'], 1)
        self.assertEqual(overall['not_assessed'], 1)
        self.assertEqual(overall['in_progress'], 0)

    def test_notes_from_record_in_context(self):
        ProgressRecord.objects.create(
            student=self.student,
            criteria=self.criteria_approved,
            status='achieved',
            notes='Great work counting!',
            recorded_by=self.teacher,
        )
        resp = self.client.get(reverse('parent_progress'))
        group = resp.context['grouped_progress'][0]
        entries_by_criteria = {e['criteria'].id: e for e in group['entries']}
        self.assertEqual(entries_by_criteria[self.criteria_approved.id]['notes'], 'Great work counting!')

    def test_recorded_by_in_context(self):
        ProgressRecord.objects.create(
            student=self.student,
            criteria=self.criteria_approved,
            status='achieved',
            recorded_by=self.teacher,
        )
        resp = self.client.get(reverse('parent_progress'))
        group = resp.context['grouped_progress'][0]
        entries_by_criteria = {e['criteria'].id: e for e in group['entries']}
        self.assertEqual(entries_by_criteria[self.criteria_approved.id]['recorded_by'], self.teacher)


class ParentProgressViewNoChildTest(TestCase):
    """When no child is linked the view renders an empty state."""

    @classmethod
    def setUpTestData(cls):
        cls.parent_role, _ = Role.objects.get_or_create(
            name=Role.PARENT, defaults={'display_name': 'Parent'},
        )
        cls.parent = CustomUser.objects.create_user(
            'no_child_parent_prog', 'wlhtestmails+no_child_prog@gmail.com', 'password1!',
        )
        cls.parent.roles.add(cls.parent_role)

    def test_no_child_renders_empty_state(self):
        self.client.force_login(self.parent)
        resp = self.client.get(reverse('parent_progress'))
        self.assertEqual(resp.status_code, 200)
        # grouped_progress should be absent or empty
        self.assertFalse(resp.context.get('grouped_progress'))

    def test_no_child_no_crash(self):
        self.client.force_login(self.parent)
        resp = self.client.get(reverse('parent_progress'))
        self.assertEqual(resp.status_code, 200)


class ParentProgressViewGroupingTest(ParentProgressTestBase):
    """Tests for multi-group progress (different subject / level combinations)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # Add a second subject with its own approved criterion
        cls.subject2 = Subject.objects.create(name='English', slug='english-prog')
        cls.criteria_english = ProgressCriteria.objects.create(
            school=cls.school,
            subject=cls.subject2,
            level=cls.level,
            name='Read a sentence',
            status='approved',
            created_by=cls.teacher,
        )

    def setUp(self):
        self._login_parent()

    def test_two_groups_when_two_subjects(self):
        resp = self.client.get(reverse('parent_progress'))
        self.assertEqual(len(resp.context['grouped_progress']), 2)

    def test_overall_total_spans_all_groups(self):
        resp = self.client.get(reverse('parent_progress'))
        overall = resp.context['overall']
        # 2 maths + 1 english
        self.assertEqual(overall['total'], 3)

    def test_english_criteria_in_page(self):
        resp = self.client.get(reverse('parent_progress'))
        self.assertIn('Read a sentence', resp.content.decode())


class ParentProgressModuleActivityTest(ParentProgressTestBase):
    """
    Tests for module_activity — maths and number puzzles stats on the progress page.
    Uses the shared ParentProgressTestBase fixtures (student, parent, school, link).
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # Maths question + answers for topic-level stats
        from classroom.models import Topic
        cls.maths_subject, _ = Subject.objects.get_or_create(
            slug='maths-mod-test', defaults={'name': 'Maths Mod Test'},
        )
        cls.topic, _ = Topic.objects.get_or_create(
            name='Algebra', subject=cls.maths_subject,
            defaults={'slug': 'algebra-mod-test'},
        )
        cls.maths_level, _ = Level.objects.get_or_create(
            level_number=99, defaults={'display_name': 'Test Level'}
        )
        cls.q1 = MathsQuestion.objects.create(
            level=cls.maths_level, topic=cls.topic,
            question_text='2 + 2 = ?', question_type='multiple_choice', difficulty=1, points=1,
        )
        cls.a_correct = MathsAnswer.objects.create(question=cls.q1, answer_text='4', is_correct=True)
        cls.a_wrong = MathsAnswer.objects.create(question=cls.q1, answer_text='5', is_correct=False)

        # Number puzzle level
        cls.puzzle_level = NumberPuzzleLevel.objects.create(
            number=99, name='Test Level', slug='test-level-mod',
            min_operand=1, max_operand=9, num_operands=2,
            puzzles_per_set=10, unlock_threshold=5, order=99,
        )

    def setUp(self):
        self._login_parent()

    # --- No activity ---

    def test_no_activity_returns_empty_module_list(self):
        resp = self.client.get(reverse('parent_progress'))
        self.assertEqual(resp.context['module_activity'], [])

    # --- Maths module ---

    def test_maths_activity_appears_when_answers_exist(self):
        import uuid
        StudentAnswer.objects.create(
            student=self.student, question=self.q1,
            selected_answer=self.a_correct, is_correct=True,
            attempt_id=uuid.uuid4(),
        )
        resp = self.client.get(reverse('parent_progress'))
        modules = resp.context['module_activity']
        names = [m['module'] for m in modules]
        self.assertIn('Maths', names)

    def test_maths_shows_correct_topic_label(self):
        import uuid
        StudentAnswer.objects.create(
            student=self.student, question=self.q1,
            selected_answer=self.a_correct, is_correct=True,
            attempt_id=uuid.uuid4(),
        )
        resp = self.client.get(reverse('parent_progress'))
        maths = next(m for m in resp.context['module_activity'] if m['module'] == 'Maths')
        labels = [r['label'] for r in maths['rows']]
        self.assertIn('Algebra', labels)

    def test_maths_accuracy_calculated_correctly(self):
        import uuid
        StudentAnswer.objects.create(
            student=self.student, question=self.q1,
            selected_answer=self.a_correct, is_correct=True,
            attempt_id=uuid.uuid4(),
        )
        StudentAnswer.objects.create(
            student=self.student, question=self.q1,
            selected_answer=self.a_wrong, is_correct=False,
            attempt_id=uuid.uuid4(),
        )
        resp = self.client.get(reverse('parent_progress'))
        maths = next(m for m in resp.context['module_activity'] if m['module'] == 'Maths')
        row = next(r for r in maths['rows'] if r['label'] == 'Algebra')
        self.assertEqual(row['total'], 2)
        self.assertEqual(row['correct'], 1)
        self.assertEqual(row['pct'], 50)

    def test_maths_answers_from_other_student_not_included(self):
        """Another student's answers must not pollute this child's stats."""
        import uuid
        other = CustomUser.objects.create_user(
            'other_s_mod', 'wlhtestmails+other_s_mod@gmail.com', 'pw',
        )
        StudentAnswer.objects.create(
            student=other, question=self.q1,
            selected_answer=self.a_correct, is_correct=True,
            attempt_id=uuid.uuid4(),
        )
        resp = self.client.get(reverse('parent_progress'))
        modules = resp.context['module_activity']
        self.assertEqual(modules, [])

    # --- Number Puzzles module ---

    def test_number_puzzles_appear_when_progress_exists(self):
        StudentPuzzleProgress.objects.create(
            student=self.student, level=self.puzzle_level,
            total_puzzles_attempted=10, total_puzzles_correct=7,
        )
        resp = self.client.get(reverse('parent_progress'))
        names = [m['module'] for m in resp.context['module_activity']]
        self.assertIn('Number Puzzles', names)

    def test_number_puzzles_accuracy_calculated_correctly(self):
        StudentPuzzleProgress.objects.create(
            student=self.student, level=self.puzzle_level,
            total_puzzles_attempted=10, total_puzzles_correct=8,
        )
        resp = self.client.get(reverse('parent_progress'))
        puzzles = next(m for m in resp.context['module_activity'] if m['module'] == 'Number Puzzles')
        row = puzzles['rows'][0]
        self.assertEqual(row['total'], 10)
        self.assertEqual(row['correct'], 8)
        self.assertEqual(row['pct'], 80)

    def test_number_puzzles_zero_attempts_excluded(self):
        """Rows with total_puzzles_attempted=0 must not show up."""
        StudentPuzzleProgress.objects.create(
            student=self.student, level=self.puzzle_level,
            total_puzzles_attempted=0, total_puzzles_correct=0,
        )
        resp = self.client.get(reverse('parent_progress'))
        names = [m['module'] for m in resp.context['module_activity']]
        self.assertNotIn('Number Puzzles', names)

    # --- Both modules ---

    def test_both_modules_shown_together(self):
        import uuid
        StudentAnswer.objects.create(
            student=self.student, question=self.q1,
            selected_answer=self.a_correct, is_correct=True,
            attempt_id=uuid.uuid4(),
        )
        StudentPuzzleProgress.objects.create(
            student=self.student, level=self.puzzle_level,
            total_puzzles_attempted=5, total_puzzles_correct=3,
        )
        resp = self.client.get(reverse('parent_progress'))
        names = [m['module'] for m in resp.context['module_activity']]
        self.assertIn('Maths', names)
        self.assertIn('Number Puzzles', names)
