"""The Student Progress Report must not mix schools (CPP-388 follow-up bug).

A child enrolled at two schools has progress records at both. The report page
resolved its per-student counts from ``ProgressRecord.objects.filter(student=…)``
with no school scope at all, so one school's Head of Institute saw counts made
up of another school's assessments — and, owning both schools, saw both rosters
merged into one list with no way to tell them apart.
"""

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from billing.models import InstitutePlan, ModuleSubscription, SchoolSubscription
from classroom.models import (
    ClassRoom, ClassStudent, Department, ProgressCriteria, ProgressRecord,
    School, Subject,
)

URL = '/progress/report/'


def _role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.title()},
    )
    return role


def _user(username, role_name):
    user = CustomUser.objects.create_user(
        username, f'{username}@example.test', 'pass1234',
    )
    user.roles.add(_role(role_name))
    return user


def _school_with_module(name, slug, admin):
    school = School.objects.create(name=name, slug=slug, admin=admin)
    plan, _ = InstitutePlan.objects.get_or_create(
        slug='scope-plan',
        defaults={
            'name': 'Scope', 'price': 0, 'class_limit': 50,
            'student_limit': 500, 'invoice_limit_yearly': 500,
            'extra_invoice_rate': 0,
        },
    )
    sub = SchoolSubscription.objects.create(
        school=school, plan=plan, status='active',
    )
    ModuleSubscription.objects.create(
        school_subscription=sub,
        module=ModuleSubscription.MODULE_PROGRESS_REPORTS,
        is_active=True,
    )
    return school


class ProgressReportSchoolScopeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi = _user('scope_hoi', Role.HEAD_OF_INSTITUTE)

        cls.cwa = _school_with_module('CWA', 'cwa-scope', cls.hoi)
        cls.mhm = _school_with_module('MHM', 'mhm-scope', cls.hoi)

        subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None, defaults={'name': 'Mathematics'},
        )
        cls.cwa_dept = Department.objects.create(
            school=cls.cwa, name='CWA Maths', slug='cwa-maths',
        )
        cls.mhm_dept = Department.objects.create(
            school=cls.mhm, name='MHM Maths', slug='mhm-maths',
        )
        cls.cwa_class = ClassRoom.objects.create(
            name='CWA Year 5', code='SCOPE001', school=cls.cwa,
            department=cls.cwa_dept, subject=subject,
        )
        cls.mhm_class = ClassRoom.objects.create(
            name='MHM Year 5', code='SCOPE002', school=cls.mhm,
            department=cls.mhm_dept, subject=subject,
        )

        # One child at both schools — the case that exposes the leak.
        cls.child = _user('scope_child', Role.STUDENT)
        ClassStudent.objects.create(
            classroom=cls.cwa_class, student=cls.child, is_active=True,
        )
        ClassStudent.objects.create(
            classroom=cls.mhm_class, student=cls.child, is_active=True,
        )

        # Three assessed criteria at CWA, none at MHM.
        for index in range(3):
            criteria = ProgressCriteria.objects.create(
                school=cls.cwa, name=f'CWA criterion {index}', status='approved',
            )
            ProgressRecord.objects.create(
                student=cls.child, criteria=criteria,
                classroom=cls.cwa_class, status='confident',
            )

    def setUp(self):
        self.client.force_login(self.hoi)

    def rows_for(self, **params):
        response = self.client.get(URL, params)
        self.assertEqual(response.status_code, 200)
        return response.context['student_data']

    def row_for(self, student, **params):
        return next(
            row for row in self.rows_for(**params) if row['student'] == student
        )

    def test_cwa_counts_do_not_appear_under_mhm(self):
        """The reported bug: the child's CWA assessments counted at MHM."""
        row = self.row_for(self.child, school=self.mhm.id)

        self.assertEqual(row['total'], 0)
        self.assertEqual(row['achieved'], 0)

    def test_the_counts_are_right_at_the_school_they_belong_to(self):
        row = self.row_for(self.child, school=self.cwa.id)

        self.assertEqual(row['total'], 3)
        self.assertEqual(row['achieved'], 3)

    def test_only_the_selected_schools_students_are_listed(self):
        mhm_only = _user('scope_mhm_child', Role.STUDENT)
        ClassStudent.objects.create(
            classroom=self.mhm_class, student=mhm_only, is_active=True,
        )

        listed = [row['student'] for row in self.rows_for(school=self.cwa.id)]
        self.assertIn(self.child, listed)
        self.assertNotIn(mhm_only, listed)

    def test_the_page_offers_a_school_filter_when_there_is_more_than_one(self):
        response = self.client.get(URL)
        self.assertEqual(
            {s.id for s in response.context['schools']},
            {self.cwa.id, self.mhm.id},
        )
