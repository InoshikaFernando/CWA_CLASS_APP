"""
Tests for the HoD "Manage Classes" page UI update (CPP-372).

The Classes page must:
  • default to Grid view (not list);
  • lay out up to 40 tiles per page (4 columns × 10 rows) in grid view;
  • show each class's location (school) and level(s) on the tile, on top of the
    details already shown;
  • render icon-only action buttons in grid view (the Edit / Assign Staff /
    Delete captions are wrapped so page-scoped CSS can hide them in grid);
  • offer an ordering control to sort by name, level, and date/time.
"""
from datetime import time
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription
from classroom.models import (
    School, Department, ClassRoom, Level, Location, SchoolTeacher,
    Subject, DepartmentSubject, DepartmentTeacher,
)


def _create_role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()}
    )
    return role


def _assign_role(user, role_name):
    role = _create_role(role_name)
    UserRole.objects.get_or_create(user=user, role=role)
    return role


class ManageClassesUITests(TestCase):
    def setUp(self):
        self.client = Client()
        self.hoi = CustomUser.objects.create_user(
            username='mc_hoi', password='password1!',
            email='wlhtestmails+mc_hoi@gmail.com',
        )
        _assign_role(self.hoi, Role.HEAD_OF_INSTITUTE)
        self.school = School.objects.create(
            name='Riverside Academy', slug='riverside', admin=self.hoi,
        )
        plan = InstitutePlan.objects.create(
            name='Basic', slug='basic-mc', price=Decimal('89.00'),
            stripe_price_id='price_mc', class_limit=50, student_limit=500,
            invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
        )
        SchoolSubscription.objects.create(school=self.school, plan=plan, status='active')

        self.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', defaults={'name': 'Mathematics', 'is_active': True},
        )
        self.dept = Department.objects.create(
            school=self.school, name='Mathematics', slug='maths', head=self.hoi,
        )
        DepartmentSubject.objects.create(department=self.dept, subject=self.subject)
        DepartmentTeacher.objects.create(department=self.dept, teacher=self.hoi)
        SchoolTeacher.objects.update_or_create(
            school=self.school, teacher=self.hoi,
            defaults={'role': 'head_of_department'},
        )

        # Levels used for the "level" ordering + tile display.
        self.lvl2 = Level.objects.create(level_number=2, display_name='Year 2')
        self.lvl5 = Level.objects.create(level_number=5, display_name='Year 5')
        self.lvl8 = Level.objects.create(level_number=8, display_name='Year 8')

        # Venues (the "location" shown on each tile).
        self.main_campus = Location.objects.create(
            school=self.school, name='Main Campus',
        )
        self.north_branch = Location.objects.create(
            school=self.school, name='North Branch',
        )

        # Three classes with deliberately mismatched name / level / schedule
        # orderings so each sort mode produces a distinct sequence.
        self.alpha = ClassRoom.objects.create(
            name='Alpha', school=self.school, department=self.dept,
            subject=self.subject, day='wednesday', start_time=time(10, 0),
            location=self.main_campus,
        )
        self.alpha.levels.add(self.lvl5)
        self.beta = ClassRoom.objects.create(
            name='Beta', school=self.school, department=self.dept,
            subject=self.subject, day='monday', start_time=time(9, 0),
            location=self.north_branch,
        )
        self.beta.levels.add(self.lvl2)
        self.gamma = ClassRoom.objects.create(
            name='Gamma', school=self.school, department=self.dept,
            subject=self.subject, day='friday', start_time=time(14, 0),
            is_online=True,
        )
        self.gamma.levels.add(self.lvl8)

        self.client.login(username='mc_hoi', password='password1!')

    def _order(self, html, *names):
        """Return the names sorted by where they first appear in the HTML."""
        return sorted(names, key=lambda n: html.index('>%s<' % n))

    # -- Default grid view -------------------------------------------------
    def test_defaults_to_grid_view(self):
        resp = self.client.get(reverse('hod_manage_classes'))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        # Container starts in grid, and the toggle defaults to grid too.
        self.assertIn('id="hod-classes" data-cwa-container class="cwa-grid"', html)
        self.assertIn('data-default-view="grid"', html)

    def test_grid_shows_forty_per_page(self):
        resp = self.client.get(reverse('hod_manage_classes'))
        self.assertIn('perPage: 40', resp.content.decode())

    def test_grid_has_four_column_rule(self):
        resp = self.client.get(reverse('hod_manage_classes'))
        html = resp.content.decode()
        self.assertIn('#hod-classes.cwa-grid { grid-template-columns: repeat(4', html)

    # -- Tile shows location + level --------------------------------------
    def test_tile_shows_location_and_level(self):
        resp = self.client.get(reverse('hod_manage_classes'))
        html = resp.content.decode()
        # Location = the class venue (not the school).
        self.assertIn('Main Campus', html)
        self.assertIn('North Branch', html)
        # An online-only class shows "Online" as its location.
        self.assertIn('Online', html)
        self.assertIn('Year 5', html)              # level display name
        self.assertIn('Year 2', html)
        self.assertIn('Year 8', html)

    # -- Icon-only action buttons in grid ---------------------------------
    def test_action_captions_are_wrapped_for_icon_only_grid(self):
        resp = self.client.get(reverse('hod_manage_classes'))
        html = resp.content.decode()
        # Captions are wrapped so the page-scoped grid CSS can hide them.
        self.assertIn('<span class="cwa-btn-label">Edit</span>', html)
        self.assertIn('<span class="cwa-btn-label">Assign Staff</span>', html)
        self.assertIn('<span class="cwa-btn-label">Delete</span>', html)
        self.assertIn('#hod-classes.cwa-grid .cwa-btn-label { display: none; }', html)

    # -- Ordering control -------------------------------------------------
    def test_sort_control_present(self):
        resp = self.client.get(reverse('hod_manage_classes'))
        html = resp.content.decode()
        self.assertIn('id="sort-select"', html)
        self.assertIn('value="name"', html)
        self.assertIn('value="level"', html)
        self.assertIn('value="schedule"', html)

    def test_sort_by_name(self):
        resp = self.client.get(reverse('hod_manage_classes'), {'sort': 'name'})
        html = resp.content.decode()
        self.assertEqual(
            self._order(html, 'Alpha', 'Beta', 'Gamma'),
            ['Alpha', 'Beta', 'Gamma'],
        )
        self.assertIn('value="name" selected', html)

    def test_sort_by_level(self):
        resp = self.client.get(reverse('hod_manage_classes'), {'sort': 'level'})
        html = resp.content.decode()
        # Beta (Year 2) < Alpha (Year 5) < Gamma (Year 8)
        self.assertEqual(
            self._order(html, 'Alpha', 'Beta', 'Gamma'),
            ['Beta', 'Alpha', 'Gamma'],
        )
        self.assertIn('value="level" selected', html)

    def test_sort_by_schedule(self):
        resp = self.client.get(reverse('hod_manage_classes'), {'sort': 'schedule'})
        html = resp.content.decode()
        # Beta (Mon) < Alpha (Wed) < Gamma (Fri)
        self.assertEqual(
            self._order(html, 'Alpha', 'Beta', 'Gamma'),
            ['Beta', 'Alpha', 'Gamma'],
        )
        self.assertIn('value="schedule" selected', html)
