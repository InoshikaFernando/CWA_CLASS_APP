"""The "reading a PDF with AI needs an AI module" explanation page.

The PDF control on all three upload screens points here when the school has no
AI page allowance. It used to point straight at the tier comparison, which
answered "how do I buy one?" without ever answering "what just happened?" — the
teacher clicked a button labelled "Extract Questions with AI" and landed on a
price list. These tests pin the three things that made it worth its own page:

* it says what happened and what still works, not just what to buy;
* it is role-aware — a teacher cannot add a module to the school's plan, so
  they are told who can rather than sent to a checkout they cannot complete;
* it reads the live quota, so a school that HAS an allowance is never told it
  hasn't (a stale tab, or someone who bought a module in the meantime).
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.testing import grant_ai_pages
from classroom.models import School, SchoolTeacher


def _user(username, role_name):
    user = CustomUser.objects.create_user(
        username=username, email=f'{username}@test.internal', password='pw1!',
    )
    role, _ = Role.objects.get_or_create(
        name=role_name,
        defaults={'display_name': role_name.replace('_', ' ').title()},
    )
    UserRole.objects.create(user=user, role=role)
    return user


class AIPagesRequiredViewTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.url = reverse('ai_pages_required')
        cls.owner = _user('owner', Role.INSTITUTE_OWNER)
        cls.school = School.objects.create(
            name='Wizards Academy', slug='wizards', admin=cls.owner, is_active=True,
        )
        cls.teacher = _user('teacher', Role.TEACHER)
        # get_or_create: creating the School already links its admin.
        for user in (cls.owner, cls.teacher):
            SchoolTeacher.objects.get_or_create(
                school=cls.school, teacher=user,
                defaults={'role': 'teacher', 'is_active': True},
            )

    def test_login_is_required(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response['Location'])

    def test_it_explains_what_happened_and_what_still_works(self):
        self.client.force_login(self.teacher)
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn('Reading a PDF with AI needs an AI module', body)
        # The half a bare pricing page never carried: the teacher is not locked
        # out of the product, only out of AI PDF reading.
        self.assertIn('What still works without it', body)
        self.assertIn('JSON or ZIP', body)
        # Named, so it is clear WHOSE plan is missing the module.
        self.assertIn('Wizards Academy', body)

    def test_a_teacher_is_told_who_can_turn_it_on(self):
        """Sending a teacher to a checkout they cannot complete is a dead end."""
        self.client.force_login(self.teacher)
        body = self.client.get(self.url).content.decode()

        self.assertIn('Who can turn this on', body)
        self.assertNotIn('Manage modules', body)

    def test_an_owner_is_offered_the_plans_and_the_module_screen(self):
        self.client.force_login(self.owner)
        body = self.client.get(self.url).content.decode()

        self.assertIn('Add an AI module', body)
        self.assertIn(reverse('ai_import:tier_select'), body)
        self.assertIn(reverse('institute_subscription_dashboard'), body)

    def test_the_screen_it_came_from_is_named_and_linked_back(self):
        self.client.force_login(self.teacher)
        body = self.client.get(self.url, {'from': 'worksheet'}).content.decode()

        self.assertIn('Upload Worksheet', body)
        self.assertIn('/worksheets/upload/', body)

    def test_an_unknown_from_value_is_not_echoed(self):
        """``from`` is rendered into the page, so it is looked up, not trusted."""
        self.client.force_login(self.teacher)
        response = self.client.get(
            self.url, {'from': '"><script>alert(1)</script>'},
        )
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('<script>alert(1)</script>', body)
        self.assertNotIn('alert(1)', body)
        # An unrecognised screen simply gets no back link, rather than one
        # pointing wherever the query string said.
        self.assertNotIn('ai-pages-required-back', body)

    def test_no_school_gets_the_reason_that_actually_applies(self):
        """"Buy a module" is the wrong answer when there is no school to buy it."""
        loner = _user('loner', Role.TEACHER)
        self.client.force_login(loner)
        body = self.client.get(self.url).content.decode()

        self.assertIn("isn't linked to a school", body)
        # Nothing to buy and nobody to ask for it here.
        self.assertNotIn('What still works without it', body)
        self.assertNotIn(reverse('ai_import:tier_select'), body)

    def test_a_school_with_an_allowance_is_not_told_it_has_none(self):
        """Reached from a stale tab, or after someone bought a module."""
        grant_ai_pages(self.school)
        self.client.force_login(self.teacher)
        body = self.client.get(self.url, {'from': 'homework'}).content.decode()

        self.assertIn('You can read PDFs with AI', body)
        self.assertNotIn('Reading a PDF with AI needs an AI module', body)
        # And it still offers the way back to where they were.
        self.assertIn('/homework/pdf/upload/', body)
