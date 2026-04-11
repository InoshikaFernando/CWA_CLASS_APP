"""
Unit tests for the parent link request approval workflow.

Covers:
- ParentSelfJoinView now creates ParentLinkRequest (not immediate ParentStudent)
- Teacher receives notification on new request
- ParentLinkRequestsView lists pending requests
- ParentLinkApproveView creates ParentStudent + notifies parent
- ParentLinkRejectView rejects request + notifies parent
- Parent dashboard shows pending requests
- Parent dashboard shows approved children (after approval)
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    School, SchoolStudent, SchoolTeacher,
    ParentLinkRequest, ParentStudent, Notification,
)


class ParentLinkRequestTestBase(TestCase):
    """Shared fixtures."""

    @classmethod
    def setUpTestData(cls):
        # Roles
        cls.teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'},
        )
        cls.parent_role, _ = Role.objects.get_or_create(
            name=Role.PARENT, defaults={'display_name': 'Parent'},
        )
        cls.student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )
        cls.hoi_role, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE, defaults={'display_name': 'Head of Institute'},
        )

        # School admin / teacher
        cls.teacher = CustomUser.objects.create_user(
            'teacher1', 'wlhtestmails+teacher@gmail.com', 'password1!',
            first_name='Tom', last_name='Teacher',
        )
        cls.teacher.roles.add(cls.teacher_role)

        # School
        cls.school = School.objects.create(
            name='Test School', slug='test-school-lr', admin=cls.teacher,
        )
        SchoolTeacher.objects.get_or_create(
            school=cls.school, teacher=cls.teacher,
            defaults={'role': 'teacher', 'is_active': True},
        )

        # Student
        cls.student = CustomUser.objects.create_user(
            'student_lr', 'wlhtestmails+student_lr@gmail.com', 'password1!',
            first_name='Zara', last_name='Smith',
        )
        cls.student.roles.add(cls.student_role)
        cls.school_student = SchoolStudent.objects.create(
            school=cls.school, student=cls.student,
        )

    def _make_parent(self, username='parent_lr', email='wlhtestmails+parent_lr@gmail.com'):
        """Create a parent user with a pending link request."""
        parent = CustomUser.objects.create_user(
            username, email, 'password1!',
            first_name='Jane', last_name='Doe',
        )
        parent.roles.add(self.parent_role)
        req = ParentLinkRequest.objects.create(
            parent=parent,
            school_student=self.school_student,
            relationship='mother',
            status=ParentLinkRequest.STATUS_PENDING,
        )
        return parent, req


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class ParentLinkRequestModelTest(ParentLinkRequestTestBase):

    def test_str(self):
        parent, req = self._make_parent('plm_parent', 'wlhtestmails+plm@gmail.com')
        self.assertIn('plm_parent', str(req))
        self.assertIn('pending', str(req))

    def test_unique_together_parent_school_student(self):
        from django.db import IntegrityError
        parent, req = self._make_parent('plm2_parent', 'wlhtestmails+plm2@gmail.com')
        with self.assertRaises(IntegrityError):
            ParentLinkRequest.objects.create(
                parent=parent,
                school_student=self.school_student,
                relationship='father',
            )

    def test_default_status_is_pending(self):
        parent, req = self._make_parent('plm3_parent', 'wlhtestmails+plm3@gmail.com')
        self.assertEqual(req.status, ParentLinkRequest.STATUS_PENDING)

    def test_status_constants(self):
        self.assertEqual(ParentLinkRequest.STATUS_PENDING, 'pending')
        self.assertEqual(ParentLinkRequest.STATUS_APPROVED, 'approved')
        self.assertEqual(ParentLinkRequest.STATUS_REJECTED, 'rejected')


# ---------------------------------------------------------------------------
# ParentSelfJoinView — now creates pending requests
# ---------------------------------------------------------------------------

class ParentSelfJoinViewTest(ParentLinkRequestTestBase):

    def setUp(self):
        self.client = Client()

    def _post_signup(self, student_id_code=None, **overrides):
        data = {
            'first_name': 'Jane',
            'last_name': 'Doe',
            'email': 'wlhtestmails+newjoin@gmail.com',
            'password': 'securepass123',
            'confirm_password': 'securepass123',
            'student_id_0': student_id_code or self.school_student.student_id_code,
            'relationship_0': 'mother',
            'accept_terms': 'on',
        }
        data.update(overrides)
        return self.client.post(reverse('register_parent_join'), data)

    def test_get_renders_form(self):
        resp = self.client.get(reverse('register_parent_join'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Register as Parent')

    def test_signup_creates_user_with_parent_role(self):
        self._post_signup()
        user = CustomUser.objects.get(email='wlhtestmails+newjoin@gmail.com')
        self.assertTrue(user.is_parent)

    def test_signup_creates_pending_link_request_not_parent_student(self):
        """Must create a pending ParentLinkRequest, NOT an immediate ParentStudent."""
        self._post_signup()
        user = CustomUser.objects.get(email='wlhtestmails+newjoin@gmail.com')
        # Link request created
        self.assertTrue(
            ParentLinkRequest.objects.filter(
                parent=user,
                school_student=self.school_student,
                status=ParentLinkRequest.STATUS_PENDING,
            ).exists()
        )
        # No direct ParentStudent link yet
        self.assertFalse(
            ParentStudent.objects.filter(
                parent=user, student=self.student,
            ).exists()
        )

    def test_signup_notifies_teacher(self):
        self._post_signup()
        self.assertTrue(
            Notification.objects.filter(
                user=self.teacher,
                notification_type='parent_link_request',
            ).exists()
        )

    def test_signup_redirects_to_parent_dashboard(self):
        resp = self._post_signup()
        self.assertRedirects(resp, reverse('parent_dashboard'), fetch_redirect_response=False)

    def test_signup_invalid_student_id_shows_error(self):
        resp = self._post_signup(student_id_code='BAD-000-0000')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'was not found')

    def test_signup_missing_name_shows_error(self):
        resp = self._post_signup(first_name='')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'First name is required')

    def test_signup_password_mismatch_shows_error(self):
        resp = self._post_signup(confirm_password='different')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'do not match')

    def test_duplicate_email_shows_error(self):
        CustomUser.objects.create_user('existing2', 'wlhtestmails+newjoin@gmail.com', 'pass')
        resp = self._post_signup()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'already exists')


# ---------------------------------------------------------------------------
# ParentLinkRequestsView
# ---------------------------------------------------------------------------

class ParentLinkRequestsViewTest(ParentLinkRequestTestBase):

    def setUp(self):
        self.client = Client()

    def test_requires_login(self):
        resp = self.client.get(reverse('parent_link_requests'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)

    def test_teacher_sees_pending_requests(self):
        parent, req = self._make_parent('view_parent', 'wlhtestmails+view_p@gmail.com')
        self.client.login(username='teacher1', password='password1!')
        resp = self.client.get(reverse('parent_link_requests'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Jane Doe')
        self.assertContains(resp, 'Zara Smith')

    def test_approved_requests_shown_in_history(self):
        # Approved requests no longer appear in pending but do appear in history
        parent, req = self._make_parent('view2_parent', 'wlhtestmails+view2_p@gmail.com')
        req.status = ParentLinkRequest.STATUS_APPROVED
        req.save()
        self.client.login(username='teacher1', password='password1!')
        resp = self.client.get(reverse('parent_link_requests'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'wlhtestmails+view2_p@gmail.com')
        # Should not appear in pending context
        self.assertNotIn(req, resp.context['pending_requests'])


# ---------------------------------------------------------------------------
# ParentLinkApproveView
# ---------------------------------------------------------------------------

class ParentLinkApproveViewTest(ParentLinkRequestTestBase):

    def setUp(self):
        self.client = Client()
        self.parent, self.req = self._make_parent('approve_parent', 'wlhtestmails+approve_p@gmail.com')

    def test_approve_creates_parent_student_link(self):
        self.client.login(username='teacher1', password='password1!')
        self.client.post(reverse('parent_link_approve', args=[self.req.id]))
        self.assertTrue(
            ParentStudent.objects.filter(
                parent=self.parent, student=self.student, school=self.school,
            ).exists()
        )

    def test_approve_sets_request_status_approved(self):
        self.client.login(username='teacher1', password='password1!')
        self.client.post(reverse('parent_link_approve', args=[self.req.id]))
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, ParentLinkRequest.STATUS_APPROVED)

    def test_approve_sets_reviewed_by(self):
        self.client.login(username='teacher1', password='password1!')
        self.client.post(reverse('parent_link_approve', args=[self.req.id]))
        self.req.refresh_from_db()
        self.assertEqual(self.req.reviewed_by, self.teacher)

    def test_approve_notifies_parent(self):
        self.client.login(username='teacher1', password='password1!')
        self.client.post(reverse('parent_link_approve', args=[self.req.id]))
        self.assertTrue(
            Notification.objects.filter(
                user=self.parent,
                notification_type='parent_link_approved',
            ).exists()
        )

    def test_approve_redirects_to_request_list(self):
        self.client.login(username='teacher1', password='password1!')
        resp = self.client.post(reverse('parent_link_approve', args=[self.req.id]))
        self.assertRedirects(resp, reverse('parent_link_requests'), fetch_redirect_response=False)

    def test_cannot_approve_already_approved_request(self):
        """get_object_or_404 requires status=pending, so approved returns 404."""
        self.req.status = ParentLinkRequest.STATUS_APPROVED
        self.req.save()
        self.client.login(username='teacher1', password='password1!')
        resp = self.client.post(reverse('parent_link_approve', args=[self.req.id]))
        self.assertEqual(resp.status_code, 404)

    def test_requires_login(self):
        resp = self.client.post(reverse('parent_link_approve', args=[self.req.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)


# ---------------------------------------------------------------------------
# ParentLinkRejectView
# ---------------------------------------------------------------------------

class ParentLinkRejectViewTest(ParentLinkRequestTestBase):

    def setUp(self):
        self.client = Client()
        self.parent, self.req = self._make_parent('reject_parent', 'wlhtestmails+reject_p@gmail.com')

    def test_reject_sets_status_rejected(self):
        self.client.login(username='teacher1', password='password1!')
        self.client.post(reverse('parent_link_reject', args=[self.req.id]), {
            'rejection_reason': 'Unknown parent',
        })
        self.req.refresh_from_db()
        self.assertEqual(self.req.status, ParentLinkRequest.STATUS_REJECTED)

    def test_reject_stores_reason(self):
        self.client.login(username='teacher1', password='password1!')
        self.client.post(reverse('parent_link_reject', args=[self.req.id]), {
            'rejection_reason': 'Cannot verify identity',
        })
        self.req.refresh_from_db()
        self.assertEqual(self.req.rejection_reason, 'Cannot verify identity')

    def test_reject_does_not_create_parent_student(self):
        self.client.login(username='teacher1', password='password1!')
        self.client.post(reverse('parent_link_reject', args=[self.req.id]), {
            'rejection_reason': 'Rejected',
        })
        self.assertFalse(
            ParentStudent.objects.filter(
                parent=self.parent, student=self.student,
            ).exists()
        )

    def test_reject_notifies_parent(self):
        self.client.login(username='teacher1', password='password1!')
        self.client.post(reverse('parent_link_reject', args=[self.req.id]), {
            'rejection_reason': 'Cannot verify identity',
        })
        notif = Notification.objects.get(
            user=self.parent, notification_type='parent_link_rejected',
        )
        self.assertIn('Cannot verify identity', notif.message)

    def test_reject_redirects_to_request_list(self):
        self.client.login(username='teacher1', password='password1!')
        resp = self.client.post(reverse('parent_link_reject', args=[self.req.id]), {})
        self.assertRedirects(resp, reverse('parent_link_requests'), fetch_redirect_response=False)

    def test_requires_login(self):
        resp = self.client.post(reverse('parent_link_reject', args=[self.req.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)


# ---------------------------------------------------------------------------
# Parent Dashboard — pending requests + approved children visibility
# ---------------------------------------------------------------------------

class ParentDashboardVisibilityTest(ParentLinkRequestTestBase):

    def setUp(self):
        self.client = Client()
        self.parent, self.req = self._make_parent('dash_parent', 'wlhtestmails+dash_p@gmail.com')

    def test_dashboard_shows_pending_request(self):
        self.client.login(username='dash_parent', password='password1!')
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Pending')
        self.assertContains(resp, 'Zara Smith')

    def test_dashboard_no_child_cards_before_approval(self):
        self.client.login(username='dash_parent', password='password1!')
        resp = self.client.get(reverse('parent_dashboard'))
        # No child-card data-testid rendered (no approved ParentStudent)
        self.assertNotContains(resp, 'data-testid="child-card"')

    def test_dashboard_shows_child_card_after_approval(self):
        """Once teacher approves, parent sees their student card."""
        ParentStudent.objects.create(
            parent=self.parent,
            student=self.student,
            school=self.school,
            relationship='mother',
            is_primary_contact=True,
            created_by=self.teacher,
        )
        self.req.status = ParentLinkRequest.STATUS_APPROVED
        self.req.save()

        self.client.login(username='dash_parent', password='password1!')
        resp = self.client.get(reverse('parent_dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-testid="child-card"')
        self.assertContains(resp, 'Zara')


# ---------------------------------------------------------------------------
# Individual student parent linking (STU-{pk} account ID)
# ---------------------------------------------------------------------------

class IndividualStudentParentLinkTest(TestCase):
    """
    Parents can link to individual students (no school) using STU-{pk} IDs.
    The link is created directly (no approval flow) with school=None.
    """

    @classmethod
    def setUpTestData(cls):
        cls.individual_role, _ = Role.objects.get_or_create(
            name=Role.INDIVIDUAL_STUDENT,
            defaults={'display_name': 'Individual Student'},
        )
        cls.parent_role, _ = Role.objects.get_or_create(
            name=Role.PARENT, defaults={'display_name': 'Parent'},
        )

        cls.indiv_student = CustomUser.objects.create_user(
            'indiv_stu1', 'wlhtestmails+indiv_stu1@gmail.com', 'pass1234!',
            first_name='Indie', last_name='Kid',
        )
        cls.indiv_student.roles.add(cls.individual_role)

    def _post_join(self, **overrides):
        data = {
            'first_name': 'Pat',
            'last_name': 'Parent',
            'email': 'wlhtestmails+indivparent@gmail.com',
            'username': 'indivparent',
            'password': 'testpass123',
            'confirm_password': 'testpass123',
            'student_id_0': f'STU-{self.indiv_student.pk:04d}',
            'relationship_0': 'guardian',
            'accept_terms': '1',
        }
        data.update(overrides)
        return Client().post(reverse('register_parent_join'), data)

    def test_stu_pk_id_creates_direct_parent_student_link(self):
        """STU-{pk} resolves to individual student and creates ParentStudent(school=None)."""
        resp = self._post_join()
        self.assertRedirects(resp, reverse('parent_dashboard'), fetch_redirect_response=False)
        self.assertTrue(
            ParentStudent.objects.filter(
                student=self.indiv_student, school__isnull=True,
            ).exists()
        )

    def test_stu_pk_id_does_not_create_link_request(self):
        """Individual student linking skips the approval flow entirely."""
        self._post_join(
            email='wlhtestmails+indivparent2@gmail.com',
            username='indivparent2',
        )
        self.assertEqual(
            ParentLinkRequest.objects.filter(parent__username='indivparent2').count(), 0
        )

    def test_invalid_stu_id_shows_error(self):
        """A non-existent STU-9999 returns a validation error."""
        resp = self._post_join(
            email='wlhtestmails+indivparent3@gmail.com',
            username='indivparent3',
            student_id_0='STU-9999',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'was not found')

    def test_school_student_id_still_works(self):
        """STU-001-0001 format (school student) still creates a ParentLinkRequest."""
        student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )
        school = School.objects.create(name='Link Test School', slug='link-test-sch')
        stu = CustomUser.objects.create_user(
            'sch_stu_lnk', 'wlhtestmails+schs@gmail.com', 'pass1234!',
            first_name='School', last_name='Kid',
        )
        stu.roles.add(student_role)
        ss = SchoolStudent.objects.create(school=school, student=stu)

        resp = Client().post(reverse('register_parent_join'), {
            'first_name': 'Par', 'last_name': 'Ent',
            'email': 'wlhtestmails+schparent@gmail.com',
            'username': 'schparent99',
            'password': 'testpass123', 'confirm_password': 'testpass123',
            'student_id_0': ss.student_id_code,
            'relationship_0': 'mother',
            'accept_terms': '1',
        })
        self.assertRedirects(resp, reverse('parent_dashboard'), fetch_redirect_response=False)
        self.assertEqual(
            ParentLinkRequest.objects.filter(
                school_student=ss, status=ParentLinkRequest.STATUS_PENDING,
            ).count(), 1
        )

    def test_parent_student_school_is_null_for_individual_link(self):
        """The created ParentStudent has school=None (not a school-based link)."""
        self._post_join(
            email='wlhtestmails+indivparent4@gmail.com',
            username='indivparent4',
        )
        link = ParentStudent.objects.filter(student=self.indiv_student).first()
        self.assertIsNotNone(link)
        self.assertIsNone(link.school)
