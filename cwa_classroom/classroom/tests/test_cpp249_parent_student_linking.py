"""
Unit tests for CPP-249: Add/link parent when adding student, add/link student when adding parent.

Covers:
1. ParentAccountSearchView filters by PARENT role only
2. _inline_create_parent shows warning when max-parent limit hit
3. _inline_link_parent shows warning when already_linked or max-parent limit hit
4. AddParentView.post() handles inline_student_action='link'
5. StudentAccountSearchView returns school's students with already_linked annotation
"""
import pytest
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.messages import get_messages

from accounts.models import CustomUser, Role, UserRole
from classroom.models import School, SchoolStudent, ParentStudent


def _make_user(username, role_name, email=None):
    user = CustomUser.objects.create_user(
        username=username,
        email=email or f'{username}@test.local',
        password='testpass123',
        first_name=username.capitalize(),
        last_name='Test',
    )
    role, _ = Role.objects.get_or_create(name=role_name, defaults={'display_name': role_name.title()})
    UserRole.objects.create(user=user, role=role)
    return user


def _make_school(admin_user, name='Test School'):
    return School.objects.create(
        name=name,
        slug=name.lower().replace(' ', '-'),
        admin=admin_user,
        is_active=True,
        is_published=True,
    )


class ParentAccountSearchRoleFilterTest(TestCase):
    """ParentAccountSearchView should only return PARENT-role users."""

    def setUp(self):
        self.hoi = _make_user('hoi_srch', Role.HEAD_OF_INSTITUTE)
        self.school = _make_school(self.hoi)
        self.client.force_login(self.hoi)

        self.parent = _make_user('parent_srch', Role.PARENT, email='parent_srch@test.local')
        self.student = _make_user('stu_srch', Role.STUDENT, email='stu_srch@test.local')
        self.teacher = _make_user('tch_srch', Role.TEACHER, email='tch_srch@test.local')

    def _get(self, q):
        url = reverse('admin_school_parent_search', args=[self.school.id])
        return self.client.get(url, {'q': q})

    def test_returns_parent_role_users(self):
        resp = self._get('srch')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'parent_srch@test.local')

    def test_excludes_student_role_users(self):
        resp = self._get('srch')
        self.assertNotContains(resp, 'stu_srch@test.local')

    def test_excludes_teacher_role_users(self):
        resp = self._get('srch')
        self.assertNotContains(resp, 'tch_srch@test.local')

    def test_already_linked_annotation_shown(self):
        student = _make_user('link_stu', Role.STUDENT)
        SchoolStudent.objects.create(school=self.school, student=student)
        ParentStudent.objects.create(
            parent=self.parent, student=student, school=self.school,
            relationship='guardian', is_primary_contact=True,
        )
        url = reverse('admin_school_parent_search', args=[self.school.id])
        resp = self.client.get(url, {'q': 'srch', 'student_id': str(student.id)})
        self.assertContains(resp, 'Already linked')

    def test_short_query_returns_empty(self):
        resp = self._get('x')
        self.assertNotContains(resp, 'parent_srch@test.local')

    def test_cross_school_student_id_not_annotated(self):
        """S3: student_id from a different school must not leak already_linked data."""
        other_admin = _make_user('other_adm_s3', Role.ADMIN)
        other_school = _make_school(other_admin, 'Other School S3')
        other_student = _make_user('other_stu_s3', Role.STUDENT)
        SchoolStudent.objects.create(school=other_school, student=other_student)
        # Link self.parent to other_school's student — should NOT be visible via self.school's search
        ParentStudent.objects.create(
            parent=self.parent, student=other_student, school=other_school,
            relationship='guardian', is_primary_contact=True,
        )
        url = reverse('admin_school_parent_search', args=[self.school.id])
        resp = self.client.get(url, {'q': 'srch', 'student_id': str(other_student.id)})
        self.assertNotContains(resp, 'Already linked')


class InlineCreateParentWarningTest(TestCase):
    """_inline_create_parent must warn when parent email already belongs to an existing account."""

    def setUp(self):
        self.hoi = _make_user('hoi_cp', Role.HEAD_OF_INSTITUTE)
        self.school = _make_school(self.hoi)
        self.client.force_login(self.hoi)

    def test_warning_shown_when_parent_email_already_exists(self):
        # Pre-create a user with the email we'll try to use for the inline parent
        _make_user('existing_par_cp', Role.PARENT, email='new_parent_cp@test.local')
        url = reverse('admin_school_students', args=[self.school.id])
        resp = self.client.post(url, {
            'first_name': 'New',
            'last_name': 'Student',
            'email': 'new_stu_cp@test.local',
            'password': 'testpass123',
            'parent_action': 'new',
            'parent_first_name': 'New',
            'parent_last_name': 'Parent',
            'parent_email': 'new_parent_cp@test.local',
            'parent_relationship': 'guardian',
        }, follow=True)
        msgs = [str(m) for m in get_messages(resp.wsgi_request)]
        self.assertTrue(
            any('already belongs to an existing account' in m for m in msgs),
            f'Expected duplicate-email warning, got: {msgs}',
        )


class InlineLinkParentWarningTest(TestCase):
    """_inline_link_parent must warn when already_linked or max-parent limit hit."""

    def setUp(self):
        self.hoi = _make_user('hoi_lp', Role.HEAD_OF_INSTITUTE)
        self.school = _make_school(self.hoi)
        self.student = _make_user('stu_lp', Role.STUDENT)
        SchoolStudent.objects.create(school=self.school, student=self.student)
        self.parent = _make_user('par_lp', Role.PARENT)
        self.client.force_login(self.hoi)

    def _post_link(self, parent_id):
        url = reverse('admin_school_students', args=[self.school.id])
        return self.client.post(url, {
            'first_name': 'New',
            'last_name': f'Stu{parent_id}',
            'email': f'new_stu_lp_{parent_id}@test.local',
            'password': 'testpass123',
            'parent_action': 'link',
            'parent_id': str(parent_id),
            'parent_relationship': 'guardian',
        }, follow=True)

    def test_warning_when_max_parents_reached(self):
        """_inline_link_parent warns when student already has 2 active parents."""
        from django.test import RequestFactory
        from django.contrib.messages.storage.fallback import FallbackStorage
        from classroom.views_admin import _inline_link_parent

        # Pre-fill student with 2 parents (at the limit)
        for i in range(2):
            p = _make_user(f'maxpar_p{i}_lp', Role.PARENT)
            ParentStudent.objects.create(
                parent=p, student=self.student, school=self.school,
                relationship='guardian', is_primary_contact=(i == 0),
            )

        # Call _inline_link_parent directly via RequestFactory so the student
        # is pre-existing (not newly created), allowing the max-parent path to fire.
        factory = RequestFactory()
        request = factory.post('/', {
            'parent_id': str(self.parent.id),
            'parent_relationship': 'guardian',
        })
        request.user = self.hoi
        setattr(request, 'session', 'session')
        setattr(request, '_messages', FallbackStorage(request))

        _inline_link_parent(request, self.school, self.student)

        msgs = [str(m) for m in get_messages(request)]
        self.assertTrue(
            any('already has 2 linked parents' in m for m in msgs),
            f'Expected max-parent warning, got: {msgs}',
        )


class AddParentViewInlineStudentLinkTest(TestCase):
    """AddParentView.post() with inline_student_action='link' creates ParentStudent."""

    def setUp(self):
        self.hoi = _make_user('hoi_apl', Role.HEAD_OF_INSTITUTE)
        self.school = _make_school(self.hoi)
        self.student = _make_user('stu_apl', Role.STUDENT)
        SchoolStudent.objects.create(school=self.school, student=self.student)
        self.client.force_login(self.hoi)

    def test_link_student_creates_parent_student_record(self):
        url = reverse('admin_school_add_parent', args=[self.school.id])
        resp = self.client.post(url, {
            'first_name': 'Link',
            'last_name': 'Parent',
            'email': 'link_parent_apl@test.local',
            'phone': '',
            'relationship': 'guardian',
            'inline_student_action': 'link',
            'inline_student_id': str(self.student.id),
        }, follow=True)
        self.assertIn(resp.status_code, [200, 302])
        parent = CustomUser.objects.filter(email='link_parent_apl@test.local').first()
        self.assertIsNotNone(parent, 'Parent user should have been created')
        self.assertTrue(
            ParentStudent.objects.filter(parent=parent, student=self.student, school=self.school).exists(),
            'ParentStudent link should exist',
        )

    def test_link_with_missing_student_id_shows_error(self):
        url = reverse('admin_school_add_parent', args=[self.school.id])
        resp = self.client.post(url, {
            'first_name': 'Link',
            'last_name': 'Parent',
            'email': 'link_parent_err@test.local',
            'phone': '',
            'relationship': 'guardian',
            'inline_student_action': 'link',
            'inline_student_id': '',
        })
        msgs = [str(m) for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any('select a student' in m.lower() for m in msgs))

    def test_link_with_wrong_school_student_shows_error(self):
        other_school = _make_school(_make_user('other_admin_apl', Role.ADMIN), 'Other School APL')
        other_student = _make_user('other_stu_apl', Role.STUDENT)
        SchoolStudent.objects.create(school=other_school, student=other_student)
        url = reverse('admin_school_add_parent', args=[self.school.id])
        resp = self.client.post(url, {
            'first_name': 'Link',
            'last_name': 'Parent',
            'email': 'link_parent_ws@test.local',
            'phone': '',
            'relationship': 'guardian',
            'inline_student_action': 'link',
            'inline_student_id': str(other_student.id),
        })
        msgs = [str(m) for m in get_messages(resp.wsgi_request)]
        self.assertTrue(any('not found' in m.lower() for m in msgs))


class StudentAccountSearchViewTest(TestCase):
    """StudentAccountSearchView returns school students with already_linked annotation."""

    def setUp(self):
        self.hoi = _make_user('hoi_sas', Role.HEAD_OF_INSTITUTE)
        self.school = _make_school(self.hoi)
        self.student = _make_user('stu_sas', Role.STUDENT, email='stu_sas@test.local')
        SchoolStudent.objects.create(school=self.school, student=self.student)
        self.parent = _make_user('par_sas', Role.PARENT)
        self.client.force_login(self.hoi)

    def _get(self, q, **params):
        url = reverse('admin_school_student_search', args=[self.school.id])
        return self.client.get(url, {'q': q, **params})

    def test_returns_school_students(self):
        resp = self._get('sas')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'stu_sas@test.local')

    def test_excludes_other_school_students(self):
        other_school = _make_school(_make_user('other_adm_sas', Role.ADMIN), 'Other SAS')
        other_stu = _make_user('other_stu_sas', Role.STUDENT, email='other_stu_sas@test.local')
        SchoolStudent.objects.create(school=other_school, student=other_stu)
        resp = self._get('sas')
        self.assertNotContains(resp, 'other_stu_sas@test.local')

    def test_already_linked_annotation_shown(self):
        ParentStudent.objects.create(
            parent=self.parent, student=self.student, school=self.school,
            relationship='guardian', is_primary_contact=True,
        )
        resp = self._get('sas', parent_id=str(self.parent.id))
        self.assertContains(resp, 'Already linked')

    def test_not_already_linked_shows_select(self):
        resp = self._get('sas', parent_id=str(self.parent.id))
        self.assertContains(resp, 'Select')
        self.assertNotContains(resp, 'Already linked')

    def test_short_query_returns_empty(self):
        resp = self._get('x')
        self.assertNotContains(resp, 'stu_sas@test.local')

    def test_non_parent_role_id_not_annotated(self):
        """S4: parent_id for a non-PARENT user must not be used for already_linked lookup."""
        teacher = _make_user('tch_s4_sas', Role.TEACHER)
        # Link self.student to teacher record (shouldn't happen in prod, but test the guard)
        ParentStudent.objects.create(
            parent=teacher, student=self.student, school=self.school,
            relationship='guardian', is_primary_contact=True,
        )
        # Passing a teacher's ID as parent_id — should not show Already linked
        resp = self._get('sas', parent_id=str(teacher.id))
        self.assertNotContains(resp, 'Already linked')
