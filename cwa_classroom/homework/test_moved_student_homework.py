"""
A student *moved* to a different class keeps access to the old class's homework,
unlike a plain removal (which revokes it). This locks in the move flow end to
end: visibility in the student list, the ability to open the take page, the
contrast with a plain removal, and revocation once the student leaves the
school.
"""
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription, Package, Subscription
from classroom.models import School, ClassRoom, ClassStudent, SchoolStudent
from homework.models import Homework


def _role(name):
    r, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()})
    return r


class MovedStudentKeepsHomeworkTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = CustomUser.objects.create_user(
            username='mv_admin', password='password1!', email='wlhtestmails+mvadmin@gmail.com')
        UserRole.objects.get_or_create(user=self.admin, role=_role(Role.HEAD_OF_INSTITUTE))
        self.school = School.objects.create(name='MV School', slug='mv-school', admin=self.admin)
        plan = InstitutePlan.objects.create(
            name='Basic', slug='basic-mv', price=Decimal('89.00'), stripe_price_id='price_mv',
            class_limit=50, student_limit=500, invoice_limit_yearly=500,
            extra_invoice_rate=Decimal('0.30'))
        SchoolSubscription.objects.create(school=self.school, plan=plan, status='active')

        self.year4 = ClassRoom.objects.create(name='Year 4', school=self.school)
        self.junior = ClassRoom.objects.create(name='Junior Scholarship', school=self.school)

        self.student = CustomUser.objects.create_user(
            username='mv_student', password='password1!',
            email='wlhtestmails+mvstudent@gmail.com', profile_completed=True)
        UserRole.objects.get_or_create(user=self.student, role=_role(Role.STUDENT))
        SchoolStudent.objects.create(school=self.school, student=self.student, is_active=True)
        # Active subscription so the individual-student subscription check never
        # walls the page after they leave the school.
        pkg = Package.objects.create(name='Ind', price=Decimal('19.90'), stripe_price_id='price_mvind')
        Subscription.objects.create(
            user=self.student, package=pkg, status=Subscription.STATUS_ACTIVE,
            discount_percent_snapshot=100)

        self.cs = ClassStudent.objects.create(
            classroom=self.year4, student=self.student, is_active=True)

        self.homework = Homework.objects.create(
            classroom=self.year4, title='Year 4 fractions',
            due_date=timezone.now() + timezone.timedelta(days=7),
            published_at=timezone.now(),
        )

    def _move_to_junior(self):
        self.client.login(username='mv_admin', password='password1!')
        self.client.post(
            reverse('class_student_move', kwargs={
                'class_id': self.year4.id, 'student_id': self.student.id}),
            {'target_class_id': self.junior.id})
        self.client.logout()

    def _visible_titles(self):
        self.client.login(username='mv_student', password='password1!')
        resp = self.client.get(reverse('homework:student_list'))
        self.client.logout()
        self.assertEqual(resp.status_code, 200)
        return [row['homework'].title for row in resp.context['rows']]

    def test_move_marks_source_retained_and_target_active(self):
        self._move_to_junior()
        self.cs.refresh_from_db()
        self.assertFalse(self.cs.is_active)
        self.assertIsNotNone(self.cs.moved_at)
        self.assertTrue(self.cs.has_homework_access)
        target = ClassStudent.objects.get(classroom=self.junior, student=self.student)
        self.assertTrue(target.is_active)
        self.assertIsNone(target.moved_at)

    def test_moved_student_still_sees_old_homework(self):
        self._move_to_junior()
        self.assertIn('Year 4 fractions', self._visible_titles())

    def test_moved_student_can_open_take_page(self):
        self._move_to_junior()
        self.client.login(username='mv_student', password='password1!')
        resp = self.client.get(
            reverse('homework:student_take', kwargs={'homework_id': self.homework.id}))
        # Access is granted (not bounced back to the list as "not enrolled").
        self.assertEqual(resp.status_code, 200)

    def test_single_class_removal_retains_homework(self):
        # Removing a student from a single class (while they stay in the school)
        # is a class change, not a revocation: moved_at is stamped and the old
        # class's homework stays visible.
        self.client.login(username='mv_admin', password='password1!')
        self.client.post(reverse('class_student_remove', kwargs={
            'class_id': self.year4.id, 'student_id': self.student.id}))
        self.client.logout()
        self.cs.refresh_from_db()
        self.assertFalse(self.cs.is_active)
        self.assertIsNotNone(self.cs.moved_at)
        self.assertIn('Year 4 fractions', self._visible_titles())

    def test_leaving_school_revokes_moved_access(self):
        self._move_to_junior()
        # The student then leaves the school entirely — retained access clears.
        self.client.login(username='mv_admin', password='password1!')
        self.client.post(reverse('admin_school_student_remove', kwargs={
            'school_id': self.school.id, 'student_id': self.student.id}))
        self.client.logout()
        self.cs.refresh_from_db()
        self.assertFalse(self.cs.is_active)
        self.assertIsNone(self.cs.moved_at)
        self.assertNotIn('Year 4 fractions', self._visible_titles())
