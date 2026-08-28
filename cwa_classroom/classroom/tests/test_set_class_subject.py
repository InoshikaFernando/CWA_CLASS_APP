"""set_class_subject_from_content — filling ClassRoom.subject from real evidence.

Migration 0120 repaired what it could infer from LEVELS and skipped the rest.
Its department fallback is only reached by a class with no levels at all, and
any level it cannot resolve skips the class outright — so a coding class with
coding levels never reached its department, however unambiguously that
department was mapped. Those are the classes this command exists for.
"""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from classroom.models import ClassRoom, Department, School, Subject


def _subject(slug, name):
    row, _ = Subject.objects.get_or_create(
        slug=slug, school=None, defaults={'name': name},
    )
    return row


class SetClassSubjectTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='S', slug='s')
        cls.coding = _subject('coding', 'Coding')
        cls.maths = _subject('mathematics', 'Mathematics')

    def _room(self, name, code, department=None):
        return ClassRoom.objects.create(
            name=name, code=code, school=self.school, department=department,
        )

    def _dept(self, name, subjects):
        dept = Department.objects.create(
            name=name, slug=name.lower(), school=self.school,
        )
        dept.subjects.set(subjects)
        return dept

    def _run(self, *args):
        out = StringIO()
        call_command('set_class_subject_from_content', *args, stdout=out)
        return out.getvalue()

    def test_a_department_mapped_to_one_subject_decides(self):
        room = self._room('Scratch 06', 'SC000001',
                          self._dept('Coding Dept', [self.coding]))

        output = self._run('--apply')

        room.refresh_from_db()
        self.assertEqual(room.subject, self.coding)
        self.assertIn('Coding Dept', output)

    def test_a_department_mapped_to_several_decides_nothing(self):
        """Department.subjects is many-to-many because a department can teach
        several. Two is not evidence, so it is named rather than guessed."""
        room = self._room('Mixed 01', 'SC000002',
                          self._dept('STEM', [self.coding, self.maths]))

        output = self._run('--apply')

        room.refresh_from_db()
        self.assertIsNone(room.subject)
        self.assertIn('several subjects', output)
        self.assertIn('Coding, Mathematics', output)

    def test_a_class_with_no_department_is_named(self):
        room = self._room('Orphan 01', 'SC000003')

        output = self._run('--apply')

        room.refresh_from_db()
        self.assertIsNone(room.subject)
        self.assertIn('no department', output)

    def test_a_department_mapped_to_nothing_is_named(self):
        room = self._room('Empty 01', 'SC000004', self._dept('Blank', []))

        output = self._run('--apply')

        room.refresh_from_db()
        self.assertIsNone(room.subject)
        self.assertIn('maps to no subject', output)

    def test_without_apply_nothing_is_written(self):
        room = self._room('Scratch 07', 'SC000005',
                          self._dept('Coding Dept', [self.coding]))

        output = self._run()

        room.refresh_from_db()
        self.assertIsNone(room.subject)
        self.assertIn('nothing written', output.lower())

    def test_a_class_that_already_has_a_subject_is_left_alone(self):
        room = self._room('Set 01', 'SC000006',
                          self._dept('Coding Dept', [self.coding]))
        room.subject = self.maths
        room.save(update_fields=['subject'])

        self._run('--apply')

        room.refresh_from_db()
        self.assertEqual(room.subject, self.maths)
