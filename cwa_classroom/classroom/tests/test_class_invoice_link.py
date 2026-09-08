"""
Tests for the "Generate Invoices" deep link from a class page.

The class page links into the existing invoice generator pre-scoped to that
class (?classroom_id=&department_id=), and GenerateInvoicesView.get() honours
those params so the Class dropdown lands pre-selected. No generation logic is
duplicated — these tests only cover the link visibility and the pre-selection.

Covers:
  1. Class page shows the link for invoicing roles, hides it for teachers.
  2. GET /invoicing/generate/?classroom_id=X pre-selects that class.
  3. A foreign/invalid classroom_id falls back to no selection (no leak).
"""
from accounts.models import Role

from .test_invoice_scope import InvoiceScopeTestCase, _user
from django.test import Client
from django.urls import reverse

from classroom.models import ClassRoom, School, SchoolStudent
from billing.models import InstitutePlan, SchoolSubscription
from decimal import Decimal


class ClassPageInvoiceLinkVisibilityTests(InvoiceScopeTestCase):
    """The link appears only for users who can actually use the generator."""

    def test_owner_sees_generate_invoices_link(self):
        c = self._client()  # logged in as INSTITUTE_OWNER (school.admin)
        resp = c.get(reverse('class_detail', args=[self.class_a.id]))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn('Generate Invoices', content)
        # Link is pre-scoped to this class (and its department).
        self.assertIn(f'classroom_id={self.class_a.id}', content)
        self.assertIn(f'department_id={self.dept_a.id}', content)

    def test_teacher_does_not_see_generate_invoices_link(self):
        """A plain teacher can view the class page but must not see the link
        (INVOICING_ROLES would 403 them on the generator)."""
        teacher = _user('inv_link_teacher', Role.TEACHER)
        self.class_a.teachers.add(teacher)

        c = Client()
        c.login(username='inv_link_teacher', password='password1!')
        resp = c.get(reverse('class_detail', args=[self.class_a.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn('Generate Invoices', resp.content.decode())


class GenerateInvoicesPreselectTests(InvoiceScopeTestCase):
    """GET query params pre-select the scope dropdowns."""

    def test_classroom_id_preselects_class_option(self):
        c = self._client()
        resp = c.get(reverse('generate_invoices'), {'classroom_id': self.class_a.id})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        # The matching option is marked selected; the other class is not.
        self.assertIn(f'value="{self.class_a.id}" selected', content)
        self.assertNotIn(f'value="{self.class_b.id}" selected', content)

    def test_department_id_preselects_department_option(self):
        c = self._client()
        resp = c.get(reverse('generate_invoices'), {'department_id': self.dept_a.id})
        content = resp.content.decode()
        self.assertIn(f'value="{self.dept_a.id}" selected', content)

    def test_no_params_selects_nothing(self):
        c = self._client()
        resp = c.get(reverse('generate_invoices'))
        content = resp.content.decode()
        self.assertNotIn(f'value="{self.class_a.id}" selected', content)
        self.assertNotIn(f'value="{self.class_b.id}" selected', content)

    def test_foreign_classroom_id_falls_back_to_no_selection(self):
        """A classroom from another school must not be pre-selected (nor leak
        into this school's dropdown)."""
        other_owner = _user('other_owner_link', Role.INSTITUTE_OWNER)
        other_school = School.objects.create(
            name='Other School', slug='other-school-link', admin=other_owner,
            is_active=True,
        )
        plan = InstitutePlan.objects.create(
            name='Other Plan', slug='other-plan-link', price=Decimal('89.00'),
            stripe_price_id='price_other_link', class_limit=50, student_limit=500,
            invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
        )
        SchoolSubscription.objects.create(school=other_school, plan=plan, status='active')
        foreign_class = ClassRoom.objects.create(
            name='Foreign Class', school=other_school, subject=self.subject,
            fee_override=Decimal('10.00'),
        )

        c = self._client()
        resp = c.get(reverse('generate_invoices'), {'classroom_id': foreign_class.id})
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertNotIn(f'value="{foreign_class.id}" selected', content)
        self.assertNotIn('Foreign Class', content)
