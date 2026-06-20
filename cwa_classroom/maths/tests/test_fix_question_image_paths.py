"""Tests for the ``fix_question_image_paths`` management command.

Storage is overridden to Django's InMemoryStorage so the test never touches
the real DO Spaces bucket and spends no tokens — it exercises the copy +
repoint logic against an in-memory object store.
"""
from io import StringIO

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage, storages
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils.functional import empty

from classroom.models import Level, School
from maths.models import QUESTION_IMAGE_PATH_RE, Question
from maths.management.commands.fix_question_image_paths import (
    proposed_path,
    sanitize_topic_segment,
)


MEMORY_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


class PureLogicTests(TestCase):
    def test_sanitize_drops_apostrophe(self):
        self.assertEqual(sanitize_topic_segment("pythagoras'_theorem"), 'pythagoras_theorem')

    def test_proposed_path_fixes_apostrophe_topic(self):
        old = "questions/year8/pythagoras'_theorem/pyth_name_hyp.png"
        new = proposed_path(old)
        self.assertEqual(new, 'questions/year8/pythagoras_theorem/pyth_name_hyp.png')
        self.assertTrue(QUESTION_IMAGE_PATH_RE.match(new))

    def test_proposed_path_none_for_structurally_broken(self):
        # Missing topic folder / missing year — can't be fixed by cleaning topic.
        self.assertIsNone(proposed_path('questions/year1/foo.png'))
        self.assertIsNone(proposed_path('questions/march.png'))
        self.assertIsNone(proposed_path('year8/algebra/foo.png'))

    def test_proposed_path_none_when_already_valid(self):
        self.assertIsNone(proposed_path('questions/year8/algebra/foo.png'))


@override_settings(STORAGES=MEMORY_STORAGES)
class CommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=994, defaults={'display_name': 'fix-path fixture'},
        )
        cls.school = School.objects.create(name='Fix School', slug='fix-school')

    def setUp(self):
        # Class-level override_settings keeps ONE InMemoryStorage instance for
        # the whole class, so objects would leak between methods. Force a fresh
        # in-memory store per test for proper isolation.
        storages._storages = {}
        default_storage._wrapped = empty

    def _make_question(self, image_path, school=None):
        # Bypass full_clean (the apostrophe path would be rejected) — we are
        # simulating legacy rows that predate the validator.
        q = Question.objects.create(
            level=self.level, school=school, question_text='?',
            question_type=Question.MULTIPLE_CHOICE, difficulty=1, points=1,
        )
        Question.objects.filter(pk=q.pk).update(image=image_path)
        q.refresh_from_db()
        return q

    def _put_object(self, name, data=b'PNGDATA'):
        default_storage.save(name, ContentFile(data))

    def test_dry_run_changes_nothing(self):
        old = "questions/year8/pythagoras'_theorem/pyth_name_hyp.png"
        self._put_object(old)
        q = self._make_question(old)

        out = StringIO()
        call_command('fix_question_image_paths', stdout=out, stderr=StringIO())

        q.refresh_from_db()
        self.assertEqual(str(q.image), old)                 # unchanged
        self.assertTrue(default_storage.exists(old))        # object untouched
        self.assertIn('DRY RUN', out.getvalue())

    def test_apply_copies_object_and_repoints_row(self):
        old = "questions/year8/pythagoras'_theorem/pyth_name_hyp.png"
        new = 'questions/year8/pythagoras_theorem/pyth_name_hyp.png'
        self._put_object(old, b'HYPDATA')
        q = self._make_question(old)

        call_command('fix_question_image_paths', '--apply', stdout=StringIO(), stderr=StringIO())

        q.refresh_from_db()
        self.assertEqual(str(q.image), new)
        self.assertTrue(default_storage.exists(new))
        # default keeps the source object (reversible)
        self.assertTrue(default_storage.exists(old))
        with default_storage.open(new) as fh:
            self.assertEqual(fh.read(), b'HYPDATA')

    def test_apply_delete_old_removes_source(self):
        old = "questions/year8/pythagoras'_theorem/pyth_name_hyp.png"
        new = 'questions/year8/pythagoras_theorem/pyth_name_hyp.png'
        self._put_object(old)
        self._make_question(old)

        call_command('fix_question_image_paths', '--apply', '--delete-old',
                     stdout=StringIO(), stderr=StringIO())

        self.assertTrue(default_storage.exists(new))
        self.assertFalse(default_storage.exists(old))

    def test_idempotent_second_run_is_noop(self):
        old = "questions/year8/pythagoras'_theorem/pyth_name_hyp.png"
        self._put_object(old)
        self._make_question(old)

        call_command('fix_question_image_paths', '--apply', stdout=StringIO(), stderr=StringIO())
        out = StringIO()
        call_command('fix_question_image_paths', '--apply', stdout=out, stderr=StringIO())
        self.assertIn('nothing to do', out.getvalue())

    def test_school_scoped_rows_are_left_alone(self):
        old = "questions/year8/pythagoras'_theorem/pyth_name_hyp.png"
        self._put_object(old)
        q = self._make_question(old, school=self.school)

        out = StringIO()
        call_command('fix_question_image_paths', '--apply', stdout=out, stderr=StringIO())

        q.refresh_from_db()
        self.assertEqual(str(q.image), old)  # untouched — school media is exempt
        self.assertIn('nothing to do', out.getvalue())

    def test_resume_after_copy_without_db_update(self):
        # Simulate a half-finished run: object already at new key, DB still old.
        old = "questions/year8/pythagoras'_theorem/pyth_name_hyp.png"
        new = 'questions/year8/pythagoras_theorem/pyth_name_hyp.png'
        self._put_object(new, b'ALREADY')
        q = self._make_question(old)

        call_command('fix_question_image_paths', '--apply', stdout=StringIO(), stderr=StringIO())

        q.refresh_from_db()
        self.assertEqual(str(q.image), new)
        with default_storage.open(new) as fh:
            self.assertEqual(fh.read(), b'ALREADY')  # not overwritten
