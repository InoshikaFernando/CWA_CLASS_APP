"""Tests for the seed_code_wizards_criteria management command."""

from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from classroom.models import ProgressCriteria, School


class SeedCodeWizardsCriteriaTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(
            name='Code Wizards Aotearoa', slug='code-wizards-aotearoa', is_active=True,
        )

    def _run(self, **kwargs):
        out = StringIO()
        call_command('seed_code_wizards_criteria', stdout=out, **kwargs)
        return out.getvalue()

    def test_seeds_seven_parents_and_28_children(self):
        self._run(school=str(self.school.id))

        qs = ProgressCriteria.objects.filter(school=self.school)
        parents = qs.filter(parent__isnull=True)
        children = qs.filter(parent__isnull=False)
        self.assertEqual(parents.count(), 7)
        self.assertEqual(children.count(), 28)

        # All rows are All-Subjects / All-Levels and approved.
        self.assertEqual(qs.count(), 35)
        self.assertFalse(qs.filter(subject__isnull=False).exists())
        self.assertFalse(qs.filter(level__isnull=False).exists())
        self.assertFalse(qs.exclude(status='approved').exists())

        # Every parent has exactly 4 children.
        for parent in parents:
            self.assertEqual(parent.children.count(), 4)

    def test_idempotent(self):
        self._run(school=str(self.school.id))
        self._run(school='code-wizards-aotearoa')  # resolve by slug, second pass
        self.assertEqual(
            ProgressCriteria.objects.filter(school=self.school).count(), 35,
            'Re-running must not create duplicates',
        )

    def test_dry_run_creates_nothing(self):
        self._run(school=str(self.school.id), dry_run=True)
        self.assertEqual(
            ProgressCriteria.objects.filter(school=self.school).count(), 0,
        )

    def test_unknown_school_errors(self):
        with self.assertRaises(CommandError):
            self._run(school='no-such-school-xyz')
