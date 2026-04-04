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
"""
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import (
    School, SchoolStudent, Subject, Level,
    ParentStudent, ProgressCriteria, ProgressRecord,
)


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
            'prog_teacher', 'prog_teacher@test.com', 'pass1234',
            first_name='Alice', last_name='Teacher',
        )
        cls.teacher.roles.add(cls.teacher_role)

        # School
        cls.school = School.objects.create(
            name='Progress School', slug='progress-school-t', admin=cls.teacher,
        )

        # Student
        cls.student = CustomUser.objects.create_user(
            'prog_student', 'prog_student@test.com', 'pass1234',
            first_name='Bobby', last_name='Learner',
        )
        cls.student.roles.add(cls.student_role)
        SchoolStudent.objects.create(school=cls.school, student=cls.student)

        # Parent
        cls.parent = CustomUser.objects.create_user(
            'prog_parent', 'prog_parent@test.com', 'pass1234',
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
            'other_teacher_prog', 'other_t_prog@test.com', 'pass1234',
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
            'no_child_parent_prog', 'no_child_prog@test.com', 'pass1234',
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
