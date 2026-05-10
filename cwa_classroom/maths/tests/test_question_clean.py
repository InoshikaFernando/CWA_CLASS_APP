"""Tests for ``Question.clean()`` — image-path validation logic.

This is a *logic* test of the validator method itself, not a data audit:
it constructs Question instances in memory and asserts that
``full_clean()`` raises (or does not raise) ``ValidationError`` based on
the path and the school scope.

For an audit of the *current state of production data* run

    python manage.py audit_question_image_paths

against the prod DB instead. Fixture-based tests prove the regex works,
not that prod data is clean — see feedback_data_quality_tests.md.
"""
from django.core.exceptions import ValidationError
from django.test import TestCase

from classroom.models import Level, School
from maths.models import Question


class GlobalQuestionImagePathValidationTests(TestCase):
    """``Question.clean()`` enforces the path convention only for global
    questions (``school IS NULL``). School-scoped questions are exempt.
    """

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=995,
            defaults={'display_name': 'clean() validation fixture'},
        )
        cls.school = School.objects.create(
            name='Path-Test School', slug='path-test-school',
        )

    def _build(self, image, school=None):
        # Constructed in-memory only — no .save() — so we exercise
        # clean() in isolation without persisting fixture rows.
        return Question(
            level=self.level,
            school=school,
            question_text='?',
            question_type=Question.MULTIPLE_CHOICE,
            difficulty=1,
            points=1,
            image=image,
        )

    # ── Global questions (school IS NULL) ────────────────────────────────

    def test_global_question_with_conformant_path_passes(self):
        for path in [
            'questions/year3/dateTime/march.png',
            'questions/year6/angles/image6.png',
            'questions/year12/algebra/foo_bar.jpg',
        ]:
            with self.subTest(path=path):
                q = self._build(path)
                q.full_clean()  # must not raise

    def test_global_question_with_legacy_path_is_rejected(self):
        for bad in [
            'questions/december_aTk3DM9.png',   # missing year + topic
            'questions/march.png',              # missing year + topic
            'questions/image6.png',             # generic dump
            'questions/year1/foo.png',          # missing topic folder
            'year1/addition/foo.png',           # missing 'questions/' prefix
        ]:
            with self.subTest(path=bad):
                q = self._build(bad)
                with self.assertRaises(ValidationError) as ctx:
                    q.full_clean()
                self.assertIn('image', ctx.exception.error_dict)

    def test_global_question_without_image_passes(self):
        # Blank image is fine — the validator only fires when an image
        # is actually attached.
        q = self._build('')
        q.full_clean()
        q = self._build(None)
        q.full_clean()

    # ── School-scoped questions are exempt ───────────────────────────────

    def test_school_question_with_any_path_passes(self):
        for path in [
            'questions/literally_anything.png',
            'questions/legacy/old_layout.png',
            'questions/year6/angles/image6.png',  # also fine, just not required
        ]:
            with self.subTest(path=path):
                q = self._build(path, school=self.school)
                q.full_clean()  # must not raise — schools control their own media
