"""
The dedicated "move student to another class" flow transfers the enrolment but,
unlike a plain removal, retains the student's homework access to the old class
(``moved_at`` set on the source row). Guards covered here: you can't move to the
same class or to a class outside your scope, and moving the student back clears
the retained-access marker.
"""
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription
from classroom.models import School, ClassRoom, ClassStudent, SchoolStudent


def _role(name):
    r, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()})
    return r


class ClassStudentMoveTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = CustomUser.objects.create_user(
            username='mvv_admin', password='password1!', email='wlhtestmails+mvvadmin@gmail.com')
        UserRole.objects.get_or_create(user=self.admin, role=_role(Role.HEAD_OF_INSTITUTE))
        self.school = School.objects.create(name='MVV School', slug='mvv-school', admin=self.admin)
        plan = InstitutePlan.objects.create(
            name='Basic', slug='basic-mvv', price=Decimal('89.00'), stripe_price_id='price_mvv',
            class_limit=50, student_limit=500, invoice_limit_yearly=500,
            extra_invoice_rate=Decimal('0.30'))
        SchoolSubscription.objects.create(school=self.school, plan=plan, status='active')

        self.year4 = ClassRoom.objects.create(name='Year 4', school=self.school)
        self.junior = ClassRoom.objects.create(name='Junior Scholarship', school=self.school)

        self.student = CustomUser.objects.create_user(
            username='mvv_student', password='password1!',
            email='wlhtestmails+mvvstudent@gmail.com', profile_completed=True)
        UserRole.objects.get_or_create(user=self.student, role=_role(Role.STUDENT))
        SchoolStudent.objects.create(school=self.school, student=self.student, is_active=True)
        ClassStudent.objects.create(classroom=self.year4, student=self.student, is_active=True)

        self.client.login(username='mvv_admin', password='password1!')

    def _move(self, source, target):
        return self.client.post(
            reverse('class_student_move', kwargs={
                'class_id': source.id, 'student_id': self.student.id}),
            {'target_class_id': target.id})

    def _cs(self, classroom):
        return ClassStudent.objects.get(classroom=classroom, student=self.student)

    def test_move_transfers_and_retains_source(self):
        self._move(self.year4, self.junior)
        src = self._cs(self.year4)
        self.assertFalse(src.is_active)
        self.assertIsNotNone(src.moved_at)
        tgt = self._cs(self.junior)
        self.assertTrue(tgt.is_active)
        self.assertIsNone(tgt.moved_at)

    def test_cannot_move_to_same_class(self):
        self.client.post(
            reverse('class_student_move', kwargs={
                'class_id': self.year4.id, 'student_id': self.student.id}),
            {'target_class_id': self.year4.id})
        src = self._cs(self.year4)
        self.assertTrue(src.is_active)
        self.assertIsNone(src.moved_at)

    def test_cannot_move_to_out_of_scope_class(self):
        other_admin = CustomUser.objects.create_user(
            username='mvv_admin2', password='password1!',
            email='wlhtestmails+mvvadmin2@gmail.com')
        UserRole.objects.get_or_create(user=other_admin, role=_role(Role.HEAD_OF_INSTITUTE))
        other_school = School.objects.create(name='Other School', slug='other-mvv', admin=other_admin)
        other_class = ClassRoom.objects.create(name='Other Class', school=other_school)

        resp = self._move(self.year4, other_class)
        self.assertEqual(resp.status_code, 404)
        # Source enrolment untouched — no partial move.
        src = self._cs(self.year4)
        self.assertTrue(src.is_active)
        self.assertIsNone(src.moved_at)
        self.assertFalse(
            ClassStudent.objects.filter(classroom=other_class, student=self.student).exists())

    def test_moving_back_clears_retained_marker(self):
        self._move(self.year4, self.junior)
        self._move(self.junior, self.year4)
        year4 = self._cs(self.year4)
        self.assertTrue(year4.is_active)
        self.assertIsNone(year4.moved_at)
        junior = self._cs(self.junior)
        self.assertFalse(junior.is_active)
        self.assertIsNotNone(junior.moved_at)
