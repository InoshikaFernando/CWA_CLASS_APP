"""A class's subject is the one the user picked, not one inferred from levels.

``Level.Meta.ordering`` is ``level_number`` and ``level_number`` is globally
unique: Maths owns 1-10, every other subject starts at 300. So the old
``levels.first().subject`` inference returned a maths level whenever one was
ticked, and a Coding class in a STEM department was labelled Mathematics no
matter what the teacher chose. The Edit Class page even had a Subject dropdown
— it just had no ``name`` attribute, so the browser never sent it.

That matters beyond the label: ``fee_utils.get_effective_fee_for_class`` keys
its subject tier on ``classroom.subject_id``, and the progress pages filter
criteria by it.
"""

from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription
from classroom.models import (
    ClassRoom, ClassTeacher, Department, DepartmentLevel, DepartmentSubject,
    DepartmentTeacher, Level, School, SchoolTeacher, Subject,
)


def _role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()})
    return role


class ClassSubjectStorageTests(TestCase):
    def setUp(self):
        self.owner = CustomUser.objects.create_user(
            username='subjowner', password='pw1!',
            email='wlhtestmails+subjowner@gmail.com')
        UserRole.objects.get_or_create(
            user=self.owner, role=_role(Role.INSTITUTE_OWNER))
        UserRole.objects.get_or_create(
            user=self.owner, role=_role(Role.HEAD_OF_DEPARTMENT))

        self.school = School.objects.create(
            name='Subject School', slug='subject-school', admin=self.owner)
        plan = InstitutePlan.objects.create(
            name='Plan', slug='plan-subj', price=Decimal('1'),
            stripe_price_id='price_subj', class_limit=50, student_limit=500,
            invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'))
        SchoolSubscription.objects.create(
            school=self.school, plan=plan, status='active')

        self.dept = Department.objects.create(
            school=self.school, name='STEM', slug='stem', head=self.owner)
        DepartmentTeacher.objects.create(department=self.dept, teacher=self.owner)
        SchoolTeacher.objects.update_or_create(
            school=self.school, teacher=self.owner,
            defaults={'role': 'head_of_department'})

        self.maths, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})
        self.coding, _ = Subject.objects.get_or_create(
            slug='coding', school=None,
            defaults={'name': 'Coding', 'is_active': True})
        DepartmentSubject.objects.create(
            department=self.dept, subject=self.maths, order=0)
        DepartmentSubject.objects.create(
            department=self.dept, subject=self.coding, order=1)

        # Maths owns the low numbers; coding starts at 300 as seed_subject_levels
        # and the department admin both allocate it.
        self.maths_lv = Level.objects.create(
            level_number=5, display_name='Year 5', subject=self.maths)
        self.coding_lv = Level.objects.create(
            level_number=300, display_name='Beginner', subject=self.coding)
        for level in (self.maths_lv, self.coding_lv):
            DepartmentLevel.objects.create(
                department=self.dept, level=level, order=level.level_number)

        self.client = Client()
        self.client.login(username='subjowner', password='pw1!')

    def _existing_class(self, name='Existing', subject=None, levels=()):
        classroom = ClassRoom.objects.create(
            name=name, school=self.school, department=self.dept,
            subject=subject or self.maths)
        for level in levels:
            classroom.levels.add(level)
        ClassTeacher.objects.create(classroom=classroom, teacher=self.owner)
        return classroom

    # -- create --------------------------------------------------------

    def test_create_stores_the_posted_subject(self):
        self.client.post(reverse('create_class'), {
            'name': 'Coding 101',
            'department': self.dept.id,
            'subject': str(self.coding.id),
            'levels': [str(self.coding_lv.id)],
        })
        self.assertEqual(
            ClassRoom.objects.get(name='Coding 101').subject, self.coding)

    def test_posted_subject_beats_a_maths_level_in_the_post(self):
        """The old inference always returned maths here — this is the bug."""
        self.client.post(reverse('create_class'), {
            'name': 'Coding Despite Maths Level',
            'department': self.dept.id,
            'subject': str(self.coding.id),
            'levels': [str(self.maths_lv.id), str(self.coding_lv.id)],
        })
        self.assertEqual(
            ClassRoom.objects.get(name='Coding Despite Maths Level').subject,
            self.coding)

    def test_hod_create_stores_the_posted_subject(self):
        self.client.post(reverse('hod_create_class'), {
            'name': 'HoD Coding',
            'department': self.dept.id,
            'subject': str(self.coding.id),
            'levels': [str(self.coding_lv.id)],
        })
        self.assertEqual(
            ClassRoom.objects.get(name='HoD Coding').subject, self.coding)

    def test_subject_outside_the_department_is_rejected(self):
        other = Subject.objects.create(
            name='Astronomy', slug='astronomy', is_active=True)
        self.client.post(reverse('create_class'), {
            'name': 'Not Ours',
            'department': self.dept.id,
            'subject': str(other.id),
            'levels': [str(self.coding_lv.id)],
        })
        self.assertFalse(ClassRoom.objects.filter(name='Not Ours').exists())

    def test_non_numeric_subject_is_rejected(self):
        self.client.post(reverse('create_class'), {
            'name': 'Junk Subject',
            'department': self.dept.id,
            'subject': 'not-a-number',
            'levels': [str(self.coding_lv.id)],
        })
        self.assertFalse(ClassRoom.objects.filter(name='Junk Subject').exists())

    # -- edit ----------------------------------------------------------

    def test_edit_stores_the_posted_subject(self):
        classroom = self._existing_class(
            'Was Maths', subject=self.maths, levels=[self.maths_lv])

        self.client.post(reverse('edit_class', args=[classroom.id]), {
            'name': 'Was Maths',
            'subject': str(self.coding.id),
            'levels': [str(self.coding_lv.id)],
        })

        classroom.refresh_from_db()
        self.assertEqual(classroom.subject, self.coding)

    def test_edit_can_switch_subject_even_with_no_levels_available(self):
        """A subject with no levels yet must still be selectable.

        Previously the subject only moved when a level moved, so a subject
        with nothing mapped could never be chosen.
        """
        classroom = self._existing_class(
            'No Levels Yet', subject=self.maths, levels=[self.maths_lv])

        self.client.post(reverse('edit_class', args=[classroom.id]), {
            'name': 'No Levels Yet',
            'subject': str(self.coding.id),
            'levels': [],
        })

        classroom.refresh_from_db()
        self.assertEqual(classroom.subject, self.coding)

    def test_edit_without_the_field_keeps_the_current_subject(self):
        """An old page left open must not silently relabel the class."""
        classroom = self._existing_class(
            'Legacy Form', subject=self.coding, levels=[self.coding_lv])

        self.client.post(reverse('edit_class', args=[classroom.id]), {
            'name': 'Legacy Form',
            'levels': [str(self.coding_lv.id)],
        })

        classroom.refresh_from_db()
        self.assertEqual(classroom.subject, self.coding)

    # -- the no-field fallback -----------------------------------------

    def test_fallback_refuses_to_guess_across_two_subjects(self):
        """With no posted subject and mixed levels, reject rather than pick."""
        self.client.post(reverse('create_class'), {
            'name': 'Ambiguous',
            'department': self.dept.id,
            'levels': [str(self.maths_lv.id), str(self.coding_lv.id)],
        })
        self.assertFalse(ClassRoom.objects.filter(name='Ambiguous').exists())

    def test_fallback_uses_a_single_subjects_levels(self):
        self.client.post(reverse('create_class'), {
            'name': 'Inferred Coding',
            'department': self.dept.id,
            'levels': [str(self.coding_lv.id)],
        })
        self.assertEqual(
            ClassRoom.objects.get(name='Inferred Coding').subject, self.coding)

    # -- the template that carries it ----------------------------------

    def test_edit_page_subject_select_is_submittable(self):
        """A select with no name attribute is never sent by the browser."""
        classroom = self._existing_class(
            'Render Check', subject=self.maths, levels=[self.maths_lv])

        html = self.client.get(
            reverse('edit_class', args=[classroom.id])).content.decode()

        self.assertIn('id="subject_select" name="subject"', html)
