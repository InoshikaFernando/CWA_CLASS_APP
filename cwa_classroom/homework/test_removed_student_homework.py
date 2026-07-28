"""
After a student is removed from a school (their ClassStudent rows are
deactivated) they must see NO further homework — the student list view filters
by active enrolment. This locks that in through the real removal flow.
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


class RemovedStudentSeesNoHomeworkTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = CustomUser.objects.create_user(
            username='hw_admin', password='password1!', email='wlhtestmails+hwadmin@gmail.com')
        UserRole.objects.get_or_create(user=self.admin, role=_role(Role.HEAD_OF_INSTITUTE))
        self.school = School.objects.create(name='HW School', slug='hw-school', admin=self.admin)
        plan = InstitutePlan.objects.create(
            name='Basic', slug='basic-hw', price=Decimal('89.00'), stripe_price_id='price_hw',
            class_limit=50, student_limit=500, invoice_limit_yearly=500,
            extra_invoice_rate=Decimal('0.30'))
        SchoolSubscription.objects.create(school=self.school, plan=plan, status='active')

        self.classroom = ClassRoom.objects.create(name='Year 5', school=self.school)
        self.student = CustomUser.objects.create_user(
            username='hw_student', password='password1!',
            email='wlhtestmails+hwstudent@gmail.com', profile_completed=True)
        UserRole.objects.get_or_create(user=self.student, role=_role(Role.STUDENT))
        SchoolStudent.objects.create(school=self.school, student=self.student, is_active=True)
        # Active subscription so the student can still log in and reach pages
        # after removal (individual student with an active sub is not walled).
        pkg = Package.objects.create(name='Ind', price=Decimal('19.90'), stripe_price_id='price_hwind')
        Subscription.objects.create(
            user=self.student, package=pkg, status=Subscription.STATUS_ACTIVE,
            discount_percent_snapshot=100)
        self.cs = ClassStudent.objects.create(
            classroom=self.classroom, student=self.student, is_active=True)

        self.homework = Homework.objects.create(
            classroom=self.classroom, title='Fractions worksheet',
            due_date=timezone.now() + timezone.timedelta(days=7),
            published_at=timezone.now(),
        )

    def test_homework_visible_while_enrolled(self):
        self.client.login(username='hw_student', password='password1!')
        resp = self.client.get(reverse('homework:student_list'))
        self.assertEqual(resp.status_code, 200)
        titles = [row['homework'].title for row in resp.context['rows']]
        self.assertIn('Fractions worksheet', titles)

    def test_no_homework_after_removal_from_school(self):
        # Remove from the school via the real admin flow (deactivates ClassStudent).
        self.client.login(username='hw_admin', password='password1!')
        self.client.post(reverse('admin_school_student_remove', kwargs={
            'school_id': self.school.id, 'student_id': self.student.id}))
        self.cs.refresh_from_db()
        self.assertFalse(self.cs.is_active)

        # Now the student sees nothing.
        self.client.logout()
        self.client.login(username='hw_student', password='password1!')
        resp = self.client.get(reverse('homework:student_list'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(list(resp.context['rows']), [])
