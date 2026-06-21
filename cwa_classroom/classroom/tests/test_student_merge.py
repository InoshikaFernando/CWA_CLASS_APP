"""Tests for the student account merge service (classroom/student_merge.py)."""
from datetime import date
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role
from classroom.models import (
    School, SchoolStudent, ClassRoom, ClassStudent, ParentStudent, Invoice,
)
from classroom.student_merge import (
    find_duplicate_groups, validate_merge, merge_students, parent_ids,
)


class StudentMergeTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = CustomUser.objects.create_user('owner', 'owner@x.nz', 'pw')
        cls.school = School.objects.create(name='S', slug='s', admin=cls.owner)
        cls.parent = CustomUser.objects.create_user('par', 'par@x.nz', 'pw',
                                                     first_name='Pat', last_name='Roe')

    def _student(self, username, first='Sam', last='Roe', parent=None, login=False):
        u = CustomUser.objects.create_user(username, f'{username}@x.nz', 'pw',
                                            first_name=first, last_name=last)
        SchoolStudent.objects.create(school=self.school, student=u)
        if parent is None:
            parent = self.parent
        if parent is not False:
            ParentStudent.objects.create(parent=parent, student=u, school=self.school,
                                         is_active=True)
        if login:
            u.last_login = timezone.now()
            u.save(update_fields=['last_login'])
        return u

    def _invoice(self, student, number, amount='100.00'):
        return Invoice.objects.create(
            invoice_number=number, school=self.school, student=student,
            billing_period_start=date(2026, 5, 1), billing_period_end=date(2026, 5, 31),
            attendance_mode='all_class_days',
            calculated_amount=Decimal(amount), amount=Decimal(amount), status='issued',
        )

    def _class(self, name):
        return ClassRoom.objects.create(name=name, school=self.school)


class DetectionTests(StudentMergeTestBase):
    def test_detects_same_name_same_parent(self):
        a = self._student('sam1')
        b = self._student('sam2')
        groups = find_duplicate_groups(self.school)
        self.assertEqual(len(groups), 1)
        self.assertEqual({u.id for u in groups[0]}, {a.id, b.id})

    def test_ignores_different_last_name(self):
        self._student('sam1', last='Roe')
        self._student('sam2', last='Doe')
        self.assertEqual(find_duplicate_groups(self.school), [])

    def test_ignores_different_parent(self):
        other = CustomUser.objects.create_user('par2', 'par2@x.nz', 'pw')
        self._student('sam1', parent=self.parent)
        self._student('sam2', parent=other)
        self.assertEqual(find_duplicate_groups(self.school), [])

    def test_ignores_parentless_students(self):
        self._student('sam1', parent=False)
        self._student('sam2', parent=False)
        self.assertEqual(find_duplicate_groups(self.school), [])

    def test_suggested_keep_is_logged_in_account(self):
        self._student('sam1', login=False)
        b = self._student('sam2', login=True)
        groups = find_duplicate_groups(self.school)
        self.assertEqual(groups[0][0].id, b.id)  # survivor suggested first

    def test_subscription_account_wins_over_login(self):
        from billing.models import Subscription
        a = self._student('sam1', login=True)   # logged in + would otherwise win
        b = self._student('sam2', login=False)
        Subscription.objects.create(user=b, status=Subscription.STATUS_ACTIVE)
        groups = find_duplicate_groups(self.school)
        self.assertEqual(groups[0][0].id, b.id)  # subscription is top priority
        self.assertNotEqual(groups[0][0].id, a.id)


class ValidationTests(StudentMergeTestBase):
    def test_rejects_self(self):
        a = self._student('sam1')
        ok, err = validate_merge(a, a, self.school)
        self.assertFalse(ok)

    def test_rejects_different_name(self):
        a = self._student('sam1', first='Sam')
        b = self._student('sam2', first='Pam')
        ok, err = validate_merge(a, b, self.school)
        self.assertFalse(ok)
        self.assertIn('First names', err)

    def test_rejects_different_parent(self):
        other = CustomUser.objects.create_user('par2', 'par2@x.nz', 'pw')
        a = self._student('sam1', parent=self.parent)
        b = self._student('sam2', parent=other)
        ok, err = validate_merge(a, b, self.school)
        self.assertFalse(ok)
        self.assertIn('different parents', err)

    def test_accepts_valid_pair(self):
        a = self._student('sam1')
        b = self._student('sam2')
        ok, err = validate_merge(a, b, self.school)
        self.assertTrue(ok)
        self.assertIsNone(err)


class MergeTests(StudentMergeTestBase):
    def test_repoints_invoices_to_keep(self):
        keep = self._student('sam1')
        absorbed = self._student('sam2')
        self._invoice(keep, 'INV-1')
        self._invoice(absorbed, 'INV-2')
        merge_students(keep, [absorbed], self.school, actor=self.owner)
        self.assertEqual(Invoice.objects.filter(student=keep).count(), 2)
        self.assertEqual(Invoice.objects.filter(student=absorbed).count(), 0)

    def test_soft_deactivates_absorbed_not_deleted(self):
        keep = self._student('sam1')
        absorbed = self._student('sam2')
        merge_students(keep, [absorbed], self.school, actor=self.owner)
        absorbed.refresh_from_db()
        self.assertFalse(absorbed.is_active)                # account kept, deactivated
        self.assertTrue(CustomUser.objects.filter(id=absorbed.id).exists())
        self.assertFalse(ParentStudent.objects.filter(
            student=absorbed, is_active=True).exists())     # link deactivated
        self.assertFalse(SchoolStudent.objects.filter(
            student=absorbed, is_active=True).exists())

    def test_distinct_class_repointed_duplicate_left_behind(self):
        keep = self._student('sam1')
        absorbed = self._student('sam2')
        shared = self._class('Year 4')
        only_absorbed = self._class('Year 5')
        ClassStudent.objects.create(classroom=shared, student=keep)
        ClassStudent.objects.create(classroom=shared, student=absorbed)      # collision
        ClassStudent.objects.create(classroom=only_absorbed, student=absorbed)  # unique
        merge_students(keep, [absorbed], self.school, actor=self.owner)
        keep_classes = set(
            ClassStudent.objects.filter(student=keep).values_list('classroom_id', flat=True)
        )
        self.assertEqual(keep_classes, {shared.id, only_absorbed.id})  # both, once each
        # The colliding duplicate row stays on the deactivated account (not deleted).
        self.assertTrue(
            ClassStudent.objects.filter(student=absorbed, classroom=shared).exists()
        )

    def test_merge_after_resolves_detection(self):
        keep = self._student('sam1')
        absorbed = self._student('sam2')
        self.assertEqual(len(find_duplicate_groups(self.school)), 1)
        merge_students(keep, [absorbed], self.school, actor=self.owner)
        self.assertEqual(find_duplicate_groups(self.school), [])  # no longer flagged

    def test_refuses_invalid_pair(self):
        keep = self._student('sam1', first='Sam')
        other = self._student('sam2', first='Pam')
        with self.assertRaises(ValueError):
            merge_students(keep, [other], self.school, actor=self.owner)


class MergeViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi_role, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE, defaults={'display_name': 'Head of Institute'})
        cls.student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'})
        cls.hoi = CustomUser.objects.create_user('hoi', 'hoi@x.nz', 'pw')
        cls.hoi.roles.add(cls.hoi_role)
        cls.school = School.objects.create(name='S', slug='s', admin=cls.hoi)
        cls.parent = CustomUser.objects.create_user('par', 'par@x.nz', 'pw',
                                                    first_name='Pat', last_name='Roe')

    def _student(self, username, first='Sam', last='Roe', parent=None):
        u = CustomUser.objects.create_user(username, f'{username}@x.nz', 'pw',
                                            first_name=first, last_name=last)
        u.roles.add(self.student_role)
        SchoolStudent.objects.create(school=self.school, student=u)
        ParentStudent.objects.create(parent=parent or self.parent, student=u,
                                     school=self.school, is_active=True)
        return u

    def setUp(self):
        self.client = Client()
        self.client.login(username='hoi', password='pw')

    def test_students_page_renders_duplicates_banner(self):
        self._student('sam1')
        self._student('sam2')
        resp = self.client.get(reverse('admin_school_students', args=[self.school.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'possible duplicate')
        self.assertContains(resp, 'Review')

    def test_modal_lists_both_accounts(self):
        a = self._student('sam1')
        b = self._student('sam2')
        url = reverse('admin_student_merge_modal', args=[self.school.id])
        resp = self.client.get(url, {'ids': f'{a.id},{b.id}'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'sam1')
        self.assertContains(resp, 'sam2')

    def test_merge_post_soft_merges_and_redirects(self):
        a = self._student('sam1')
        b = self._student('sam2')
        url = reverse('admin_student_merge', args=[self.school.id])
        resp = self.client.post(url, {'ids': f'{a.id},{b.id}', 'keep_id': a.id})
        self.assertEqual(resp.status_code, 302)
        a.refresh_from_db(); b.refresh_from_db()
        self.assertTrue(a.is_active)
        self.assertFalse(b.is_active)  # absorbed, soft-deactivated

    def test_merge_post_rejects_mismatched_names(self):
        a = self._student('sam1', first='Sam')
        b = self._student('pam1', first='Pam')
        url = reverse('admin_student_merge', args=[self.school.id])
        self.client.post(url, {'ids': f'{a.id},{b.id}', 'keep_id': a.id})
        b.refresh_from_db()
        self.assertTrue(b.is_active)  # not merged — guardrail held

    def test_non_leadership_cannot_merge(self):
        a = self._student('sam1')
        b = self._student('sam2')
        intruder = CustomUser.objects.create_user('kid', 'kid@x.nz', 'pw')
        intruder.roles.add(self.student_role)
        c = Client(); c.login(username='kid', password='pw')
        c.post(reverse('admin_student_merge', args=[self.school.id]),
               {'ids': f'{a.id},{b.id}', 'keep_id': a.id})
        b.refresh_from_db()
        self.assertTrue(b.is_active)  # blocked
