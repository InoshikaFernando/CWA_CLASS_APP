"""
Tests for parent child switcher — multi-child scenario.

Covers:
- Parent with two linked children can switch between them
- After switching, dashboard/homework/progress/attendance show the selected child's data
- Switching back works correctly
- Default selection is the first child when no session key set
- Switching to an unlinked child is silently ignored
- Inactive links are not selectable
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role
from classroom.models import (
    School, SchoolStudent, Subject, ClassRoom, ClassStudent,
    ParentStudent,
)


class MultiChildSwitcherBase(TestCase):
    """Two children linked to the same parent."""

    @classmethod
    def setUpTestData(cls):
        parent_role, _ = Role.objects.get_or_create(
            name=Role.PARENT, defaults={'display_name': 'Parent'},
        )
        student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )

        cls.admin = CustomUser.objects.create_user(
            'sw_admin', 'wlhtestmails+sw_admin@gmail.com', 'password1!',
        )
        cls.admin.roles.add(admin_role)

        cls.school = School.objects.create(
            name='Switcher School', slug='switcher-school', admin=cls.admin,
        )

        # Parent
        cls.parent = CustomUser.objects.create_user(
            'sw_parent', 'wlhtestmails+sw_parent@gmail.com', 'password1!',
            first_name='Pat', last_name='Parent',
        )
        cls.parent.roles.add(parent_role)

        # Child A
        cls.child_a = CustomUser.objects.create_user(
            'sw_child_a', 'wlhtestmails+sw_child_a@gmail.com', 'password1!',
            first_name='Alice', last_name='Child',
        )
        cls.child_a.roles.add(student_role)
        SchoolStudent.objects.create(school=cls.school, student=cls.child_a)

        # Child B
        cls.child_b = CustomUser.objects.create_user(
            'sw_child_b', 'wlhtestmails+sw_child_b@gmail.com', 'password1!',
            first_name='Bob', last_name='Child',
        )
        cls.child_b.roles.add(student_role)
        SchoolStudent.objects.create(school=cls.school, student=cls.child_b)

        # Link both to parent
        cls.link_a = ParentStudent.objects.create(
            parent=cls.parent, student=cls.child_a,
            school=cls.school, relationship='mother', is_active=True,
        )
        cls.link_b = ParentStudent.objects.create(
            parent=cls.parent, student=cls.child_b,
            school=cls.school, relationship='mother', is_active=True,
        )

        # Unlinked student (security check)
        cls.stranger = CustomUser.objects.create_user(
            'sw_stranger', 'wlhtestmails+sw_stranger@gmail.com', 'password1!',
        )
        cls.stranger.roles.add(student_role)

        # Inactive link (should not be selectable)
        cls.child_c = CustomUser.objects.create_user(
            'sw_child_c', 'wlhtestmails+sw_child_c@gmail.com', 'password1!',
            first_name='Carol', last_name='Child',
        )
        cls.child_c.roles.add(student_role)
        SchoolStudent.objects.create(school=cls.school, student=cls.child_c)
        cls.link_c = ParentStudent.objects.create(
            parent=cls.parent, student=cls.child_c,
            school=cls.school, relationship='mother', is_active=False,
        )

        # Classrooms for each child
        maths, _ = Subject.objects.get_or_create(
            slug='maths-sw', defaults={'name': 'Maths SW'},
        )
        cls.class_a = ClassRoom.objects.create(
            name='Alice Class', school=cls.school, subject=maths,
        )
        cls.class_b = ClassRoom.objects.create(
            name='Bob Class', school=cls.school, subject=maths,
        )
        ClassStudent.objects.create(classroom=cls.class_a, student=cls.child_a)
        ClassStudent.objects.create(classroom=cls.class_b, student=cls.child_b)

    def _login(self):
        c = Client()
        c.login(username='sw_parent', password='password1!')
        return c

    def _switch(self, client, child):
        return client.post(reverse('parent_switch_child', args=[child.id]))


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

class ChildSwitcherSessionTest(MultiChildSwitcherBase):

    def test_switch_to_child_a_sets_session(self):
        c = self._login()
        self._switch(c, self.child_a)
        self.assertEqual(c.session['active_child_id'], self.child_a.id)

    def test_switch_to_child_b_sets_session(self):
        c = self._login()
        self._switch(c, self.child_b)
        self.assertEqual(c.session['active_child_id'], self.child_b.id)

    def test_switch_back_to_child_a_updates_session(self):
        c = self._login()
        self._switch(c, self.child_b)
        self._switch(c, self.child_a)
        self.assertEqual(c.session['active_child_id'], self.child_a.id)

    def test_unlinked_child_not_set_in_session(self):
        c = self._login()
        self._switch(c, self.stranger)
        self.assertNotEqual(c.session.get('active_child_id'), self.stranger.id)

    def test_inactive_link_child_not_set_in_session(self):
        c = self._login()
        self._switch(c, self.child_c)
        self.assertNotEqual(c.session.get('active_child_id'), self.child_c.id)

    def test_switch_redirects_to_dashboard(self):
        c = self._login()
        resp = self._switch(c, self.child_a)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('parent', resp.url)

    def test_switch_respects_next_param(self):
        c = self._login()
        resp = c.post(
            reverse('parent_switch_child', args=[self.child_a.id]),
            data={'next': '/parent/homework/'},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, '/parent/homework/')


# ---------------------------------------------------------------------------
# Default child (no session)
# ---------------------------------------------------------------------------

class ChildSwitcherDefaultTest(MultiChildSwitcherBase):

    def test_first_child_is_default_when_no_session(self):
        """With no active_child_id in session, the first linked child is used."""
        c = self._login()
        resp = c.get(reverse('parent_dashboard'))
        self.assertEqual(resp.status_code, 200)
        # The first child returned by _get_parent_children — order is by pk
        first_child = ParentStudent.objects.filter(
            parent=self.parent, is_active=True,
        ).first().student
        # Session should now be set to the first child
        self.assertEqual(c.session.get('active_child_id'), first_child.id)

    def test_dashboard_shows_correct_child_after_switch_to_b(self):
        c = self._login()
        self._switch(c, self.child_b)
        resp = c.get(reverse('parent_dashboard'))
        self.assertContains(resp, 'Bob')

    def test_dashboard_shows_correct_child_after_switch_to_a(self):
        c = self._login()
        self._switch(c, self.child_a)
        resp = c.get(reverse('parent_dashboard'))
        self.assertContains(resp, 'Alice')


# ---------------------------------------------------------------------------
# Context isolation — each page uses active child
# ---------------------------------------------------------------------------

class ChildSwitcherContextIsolationTest(MultiChildSwitcherBase):

    def test_homework_page_shows_active_childs_name(self):
        from homework.models import Homework
        hw = Homework.objects.create(
            classroom=self.class_b,
            title='Bob Only HW',
            due_date=timezone.now() + timezone.timedelta(days=5),
            num_questions=5,
        )
        c = self._login()
        self._switch(c, self.child_b)
        resp = c.get(reverse('parent_homework'))
        self.assertContains(resp, 'Bob')
        self.assertContains(resp, 'Bob Only HW')

    def test_homework_page_does_not_show_other_childs_homework(self):
        from homework.models import Homework
        hw = Homework.objects.create(
            classroom=self.class_a,
            title='Alice Only HW',
            due_date=timezone.now() + timezone.timedelta(days=5),
            num_questions=5,
        )
        c = self._login()
        self._switch(c, self.child_b)  # switched to Bob
        resp = c.get(reverse('parent_homework'))
        self.assertNotContains(resp, 'Alice Only HW')

    def test_attendance_page_shows_active_child(self):
        c = self._login()
        self._switch(c, self.child_a)
        resp = c.get(reverse('parent_attendance'))
        self.assertContains(resp, 'Alice')

    def test_progress_page_shows_active_child(self):
        c = self._login()
        self._switch(c, self.child_b)
        resp = c.get(reverse('parent_progress'))
        self.assertContains(resp, 'Bob')

    def test_children_list_in_context_shows_all_active_children(self):
        """The children context var (for the switcher dropdown) always shows ALL active children."""
        c = self._login()
        self._switch(c, self.child_a)
        resp = c.get(reverse('parent_homework'))
        children = list(resp.context['children'])
        child_ids = [link.student_id for link in children]
        self.assertIn(self.child_a.id, child_ids)
        self.assertIn(self.child_b.id, child_ids)
        # Inactive child must not appear
        self.assertNotIn(self.child_c.id, child_ids)
