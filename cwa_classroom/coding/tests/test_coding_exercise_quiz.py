"""
test_coding_exercise_quiz.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for CodingExercise quiz-type fields and validation.

Covers:
  - Migration defaults (question_type='write_code', correct_short_answer=None)
  - Model.clean() for every question_type path
  - Admin: CodingAnswerInline present; JS file referenced in response
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, Client

from coding.models import (
    CodingAnswer,
    CodingExercise,
    CodingLanguage,
    CodingTopic,
    TopicLevel,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

def _make_lang():
    lang, _ = CodingLanguage.objects.get_or_create(
        slug='py-quiz',
        defaults={'name': 'Python Quiz', 'color': '#3b82f6', 'order': 99, 'is_active': True},
    )
    return lang


def _make_topic(lang):
    topic, _ = CodingTopic.objects.get_or_create(
        language=lang, slug='quiz-basics',
        defaults={'name': 'Quiz Basics', 'order': 1, 'is_active': True},
    )
    return topic


def _make_exercise(topic, question_type=CodingExercise.WRITE_CODE, **kwargs):
    tl, _ = TopicLevel.get_or_create_for(topic, CodingExercise.BEGINNER)
    defaults = {
        'title': f'Quiz exercise ({question_type})',
        'description': 'A test question.',
        'order': 1,
        'is_active': True,
    }
    if question_type == CodingExercise.WRITE_CODE:
        defaults['starter_code'] = '# start'
        defaults['expected_output'] = 'hello'
    defaults.update(kwargs)
    return CodingExercise.objects.create(
        topic_level=tl,
        question_type=question_type,
        **defaults,
    )


def _add_answers(exercise, specs):
    """specs: list of (text, is_correct) tuples, order assigned automatically."""
    for i, (text, correct) in enumerate(specs):
        CodingAnswer.objects.create(
            exercise=exercise, answer_text=text, is_correct=correct, order=i,
        )


# ---------------------------------------------------------------------------
# Migration / field-default tests
# ---------------------------------------------------------------------------

class TestMigrationDefaults(TestCase):
    """Verify that 0013/0014 migrations leave existing data untouched."""

    @classmethod
    def setUpTestData(cls):
        lang  = _make_lang()
        topic = _make_topic(lang)
        tl, _ = TopicLevel.get_or_create_for(topic, CodingExercise.BEGINNER)
        cls.exercise = CodingExercise.objects.create(
            topic_level=tl,
            title='Legacy write_code',
            description='Old-style exercise.',
            starter_code='print("hi")',
            expected_output='hi',
            order=1,
        )

    def test_question_type_defaults_to_write_code(self):
        ex = CodingExercise.objects.get(pk=self.exercise.pk)
        self.assertEqual(ex.question_type, CodingExercise.WRITE_CODE)

    def test_correct_short_answer_defaults_to_none(self):
        ex = CodingExercise.objects.get(pk=self.exercise.pk)
        self.assertIsNone(ex.correct_short_answer)

    def test_existing_fields_unchanged(self):
        ex = CodingExercise.objects.get(pk=self.exercise.pk)
        self.assertEqual(ex.starter_code, 'print("hi")')
        self.assertEqual(ex.expected_output, 'hi')
        self.assertEqual(ex.title, 'Legacy write_code')


# ---------------------------------------------------------------------------
# write_code validation
# ---------------------------------------------------------------------------

class TestWriteCodeValidation(TestCase):

    @classmethod
    def setUpTestData(cls):
        lang  = _make_lang()
        cls.topic = _make_topic(lang)

    def test_valid_with_starter_code_and_expected_output(self):
        ex = _make_exercise(self.topic, starter_code='x=1', expected_output='1')
        ex.full_clean()  # must not raise

    def test_valid_with_only_starter_code(self):
        ex = _make_exercise(self.topic, starter_code='x=1', expected_output='')
        ex.full_clean()

    def test_valid_with_uses_browser_sandbox(self):
        ex = _make_exercise(
            self.topic, starter_code='', expected_output='',
            uses_browser_sandbox=True,
        )
        ex.full_clean()

    def test_invalid_when_all_code_fields_empty(self):
        ex = _make_exercise(self.topic, starter_code='', expected_output='')
        with self.assertRaises(ValidationError) as cm:
            ex.full_clean()
        self.assertIn('starter_code', cm.exception.message_dict)

    def test_invalid_if_has_codinganswer_rows(self):
        ex = _make_exercise(self.topic)
        _add_answers(ex, [('A', True), ('B', False)])
        with self.assertRaises(ValidationError) as cm:
            ex.full_clean()
        self.assertIn('question_type', cm.exception.message_dict)

    def test_correct_short_answer_not_allowed(self):
        ex = _make_exercise(self.topic, correct_short_answer='should not be here')
        with self.assertRaises(ValidationError) as cm:
            ex.full_clean()
        self.assertIn('correct_short_answer', cm.exception.message_dict)


# ---------------------------------------------------------------------------
# multiple_choice validation
# ---------------------------------------------------------------------------

class TestMultipleChoiceValidation(TestCase):

    @classmethod
    def setUpTestData(cls):
        lang  = _make_lang()
        cls.topic = _make_topic(lang)

    def test_valid_with_four_answers_one_correct(self):
        ex = _make_exercise(self.topic, question_type=CodingExercise.MULTIPLE_CHOICE)
        _add_answers(ex, [('A', True), ('B', False), ('C', False), ('D', False)])
        ex.full_clean()

    def test_invalid_with_zero_correct(self):
        ex = _make_exercise(self.topic, question_type=CodingExercise.MULTIPLE_CHOICE)
        _add_answers(ex, [('A', False), ('B', False), ('C', False)])
        with self.assertRaises(ValidationError) as cm:
            ex.full_clean()
        self.assertIn('question_type', cm.exception.message_dict)

    def test_invalid_with_multiple_correct(self):
        ex = _make_exercise(self.topic, question_type=CodingExercise.MULTIPLE_CHOICE)
        _add_answers(ex, [('A', True), ('B', True), ('C', False)])
        with self.assertRaises(ValidationError) as cm:
            ex.full_clean()
        self.assertIn('question_type', cm.exception.message_dict)

    def test_invalid_with_fewer_than_two_answers(self):
        ex = _make_exercise(self.topic, question_type=CodingExercise.MULTIPLE_CHOICE)
        _add_answers(ex, [('A', True)])
        with self.assertRaises(ValidationError) as cm:
            ex.full_clean()
        self.assertIn('question_type', cm.exception.message_dict)

    def test_invalid_with_zero_answers(self):
        ex = _make_exercise(self.topic, question_type=CodingExercise.MULTIPLE_CHOICE)
        with self.assertRaises(ValidationError) as cm:
            ex.full_clean()
        self.assertIn('question_type', cm.exception.message_dict)


# ---------------------------------------------------------------------------
# true_false validation
# ---------------------------------------------------------------------------

class TestTrueFalseValidation(TestCase):

    @classmethod
    def setUpTestData(cls):
        lang  = _make_lang()
        cls.topic = _make_topic(lang)

    def test_valid_with_exactly_two_answers_one_correct(self):
        ex = _make_exercise(self.topic, question_type=CodingExercise.TRUE_FALSE)
        _add_answers(ex, [('True', True), ('False', False)])
        ex.full_clean()

    def test_invalid_with_one_answer(self):
        ex = _make_exercise(self.topic, question_type=CodingExercise.TRUE_FALSE)
        _add_answers(ex, [('True', True)])
        with self.assertRaises(ValidationError) as cm:
            ex.full_clean()
        self.assertIn('question_type', cm.exception.message_dict)

    def test_invalid_with_three_answers(self):
        ex = _make_exercise(self.topic, question_type=CodingExercise.TRUE_FALSE)
        _add_answers(ex, [('True', True), ('False', False), ('Maybe', False)])
        with self.assertRaises(ValidationError) as cm:
            ex.full_clean()
        self.assertIn('question_type', cm.exception.message_dict)

    def test_invalid_with_two_correct(self):
        ex = _make_exercise(self.topic, question_type=CodingExercise.TRUE_FALSE)
        _add_answers(ex, [('True', True), ('False', True)])
        with self.assertRaises(ValidationError) as cm:
            ex.full_clean()
        self.assertIn('question_type', cm.exception.message_dict)

    def test_invalid_with_zero_correct(self):
        ex = _make_exercise(self.topic, question_type=CodingExercise.TRUE_FALSE)
        _add_answers(ex, [('True', False), ('False', False)])
        with self.assertRaises(ValidationError) as cm:
            ex.full_clean()
        self.assertIn('question_type', cm.exception.message_dict)


# ---------------------------------------------------------------------------
# short_answer validation
# ---------------------------------------------------------------------------

class TestShortAnswerValidation(TestCase):

    @classmethod
    def setUpTestData(cls):
        lang  = _make_lang()
        cls.topic = _make_topic(lang)

    def test_valid_when_correct_short_answer_set(self):
        ex = _make_exercise(
            self.topic,
            question_type=CodingExercise.SHORT_ANSWER,
            correct_short_answer='42',
        )
        ex.full_clean()

    def test_invalid_when_correct_short_answer_missing(self):
        ex = _make_exercise(self.topic, question_type=CodingExercise.SHORT_ANSWER)
        with self.assertRaises(ValidationError) as cm:
            ex.full_clean()
        self.assertIn('correct_short_answer', cm.exception.message_dict)

    def test_invalid_when_correct_short_answer_blank(self):
        ex = _make_exercise(
            self.topic,
            question_type=CodingExercise.SHORT_ANSWER,
            correct_short_answer='   ',
        )
        with self.assertRaises(ValidationError) as cm:
            ex.full_clean()
        self.assertIn('correct_short_answer', cm.exception.message_dict)

    def test_invalid_if_codinganswer_rows_exist(self):
        ex = _make_exercise(
            self.topic,
            question_type=CodingExercise.SHORT_ANSWER,
            correct_short_answer='42',
        )
        _add_answers(ex, [('A', True)])
        with self.assertRaises(ValidationError) as cm:
            ex.full_clean()
        self.assertIn('question_type', cm.exception.message_dict)


# ---------------------------------------------------------------------------
# fill_blank validation — mirrors short_answer rules
# ---------------------------------------------------------------------------

class TestFillBlankValidation(TestCase):

    @classmethod
    def setUpTestData(cls):
        lang  = _make_lang()
        cls.topic = _make_topic(lang)

    def test_valid_when_correct_short_answer_set(self):
        ex = _make_exercise(
            self.topic,
            question_type=CodingExercise.FILL_BLANK,
            correct_short_answer='for loop',
        )
        ex.full_clean()

    def test_invalid_when_correct_short_answer_missing(self):
        ex = _make_exercise(self.topic, question_type=CodingExercise.FILL_BLANK)
        with self.assertRaises(ValidationError) as cm:
            ex.full_clean()
        self.assertIn('correct_short_answer', cm.exception.message_dict)

    def test_invalid_if_codinganswer_rows_exist(self):
        ex = _make_exercise(
            self.topic,
            question_type=CodingExercise.FILL_BLANK,
            correct_short_answer='for loop',
        )
        _add_answers(ex, [('for loop', True)])
        with self.assertRaises(ValidationError) as cm:
            ex.full_clean()
        self.assertIn('question_type', cm.exception.message_dict)


# ---------------------------------------------------------------------------
# CodingAnswer model
# ---------------------------------------------------------------------------

class TestCodingAnswerModel(TestCase):

    @classmethod
    def setUpTestData(cls):
        lang  = _make_lang()
        topic = _make_topic(lang)
        cls.ex = _make_exercise(topic, question_type=CodingExercise.MULTIPLE_CHOICE)

    def test_answer_text_is_text_field(self):
        from coding.models import CodingAnswer as CA
        field = CA._meta.get_field('answer_text')
        self.assertEqual(field.get_internal_type(), 'TextField')

    def test_answer_has_timestamps(self):
        from coding.models import CodingAnswer as CA
        self.assertTrue(hasattr(CA, 'created_at'))
        self.assertTrue(hasattr(CA, 'updated_at'))

    def test_create_answer(self):
        ans = CodingAnswer.objects.create(
            exercise=self.ex, answer_text='A long answer text', is_correct=True, order=0,
        )
        self.assertIsNotNone(ans.created_at)
        self.assertIsNotNone(ans.updated_at)

    def test_str_includes_tick_for_correct(self):
        ans = CodingAnswer(exercise=self.ex, answer_text='Option A', is_correct=True)
        self.assertIn('✓', str(ans))

    def test_str_no_tick_for_incorrect(self):
        ans = CodingAnswer(exercise=self.ex, answer_text='Option B', is_correct=False)
        self.assertNotIn('✓', str(ans))


# ---------------------------------------------------------------------------
# Admin tests
# ---------------------------------------------------------------------------

class TestCodingExerciseAdmin(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            username='adminquiz', password='adminpass', email='admin@quiz.test',
        )
        lang  = _make_lang()
        topic = _make_topic(lang)
        cls.ex = _make_exercise(topic)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.superuser)

    def test_change_page_loads(self):
        url = f'/admin/coding/codingexercise/{self.ex.pk}/change/'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_js_file_referenced_in_response(self):
        url = f'/admin/coding/codingexercise/{self.ex.pk}/change/'
        resp = self.client.get(url)
        self.assertContains(resp, 'coding_exercise_type_toggle.js')

    def test_codinganswer_inline_present_in_response(self):
        url = f'/admin/coding/codingexercise/{self.ex.pk}/change/'
        resp = self.client.get(url)
        # Inline group id uses the FK related_name 'answers' as prefix
        self.assertContains(resp, 'answers-group')

    def test_code_fieldset_present(self):
        url = f'/admin/coding/codingexercise/{self.ex.pk}/change/'
        resp = self.client.get(url)
        self.assertContains(resp, 'code-exercise-fields')

    def test_short_answer_fieldset_present(self):
        url = f'/admin/coding/codingexercise/{self.ex.pk}/change/'
        resp = self.client.get(url)
        self.assertContains(resp, 'short-answer-fields')

    def test_list_page_includes_question_type_column(self):
        resp = self.client.get('/admin/coding/codingexercise/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'question_type')
