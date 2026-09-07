"""One grading decision, shared by every import path.

The worksheet PDF upload, the homework PDF upload and the AI PDF import all
save through ``resolve_grading``. Before that they each had their own rules and
they disagreed: ai_import never wrote ``validation_type`` at all (so everything
landed on the model default, ``auto``), and the homework saver coerced anything
non-extended back to ``auto`` — which silently undid a teacher-graded drawing
question whenever the extractor typed it ``short_answer``.
"""
from django.test import SimpleTestCase

from worksheets.services import CONSTRUCTION_RUBRIC, resolve_grading


class ResolveGradingTests(SimpleTestCase):

    def test_a_drawing_is_the_teachers_whatever_its_type(self):
        # The rule that has to win: an extractor typing this short_answer must
        # not hand a child a text box for a tree diagram.
        for q_type in ('short_answer', 'extended_answer', 'calculation'):
            with self.subTest(q_type):
                vt, rubric = resolve_grading({
                    'question_text': 'Draw a tree diagram to illustrate this situation.',
                    'question_type': q_type, 'validation_type': 'auto',
                })
                self.assertEqual(vt, 'human_graded')
                self.assertEqual(rubric, CONSTRUCTION_RUBRIC)

    def test_a_drawing_wrongly_set_ai_graded_is_corrected(self):
        vt, _ = resolve_grading({
            'question_text': 'Illustrate on a Venn diagram the sets A and B.',
            'question_type': 'extended_answer', 'validation_type': 'ai_graded',
        })
        self.assertEqual(vt, 'human_graded')

    def test_an_existing_rubric_survives(self):
        vt, rubric = resolve_grading({
            'question_text': 'Show this information on a Venn diagram.',
            'question_type': 'extended_answer', 'validation_type': 'ai_graded',
            'grading_rubric': 'Two overlapping circles, 8 in the intersection.',
        })
        self.assertEqual(vt, 'human_graded')
        self.assertEqual(rubric, 'Two overlapping circles, 8 in the intersection.')

    def test_human_graded_is_never_downgraded(self):
        # The old homework rule turned this into 'auto' — a person's standing
        # decision, undone by a type check.
        vt, _ = resolve_grading({
            'question_text': 'Write a short poem about triangles.',
            'question_type': 'short_answer', 'validation_type': 'human_graded',
        })
        self.assertEqual(vt, 'human_graded')

    def test_extended_answer_on_auto_becomes_ai_graded(self):
        # There is no stored answer to match against, so leaving it auto marks
        # every child wrong by exact match.
        vt, _ = resolve_grading({
            'question_text': 'Explain why Stefan cannot be correct.',
            'question_type': 'extended_answer', 'validation_type': 'auto',
        })
        self.assertEqual(vt, 'ai_graded')

    def test_ai_graded_on_a_choice_question_drops_to_auto(self):
        vt, _ = resolve_grading({
            'question_text': 'What is 24 divided by 6?',
            'question_type': 'multiple_choice', 'validation_type': 'ai_graded',
        })
        self.assertEqual(vt, 'auto')

    def test_a_table_stays_auto_because_the_app_draws_it(self):
        vt, _ = resolve_grading({
            'question_text': 'Complete the table of values for y = 3x.',
            'question_type': 'table_of_values', 'validation_type': 'auto',
        })
        self.assertEqual(vt, 'auto')

    def test_ordinary_questions_are_unchanged(self):
        vt, rubric = resolve_grading({
            'question_text': 'What is 4 + 4?',
            'question_type': 'short_answer', 'validation_type': 'auto',
        })
        self.assertEqual((vt, rubric), ('auto', ''))

    def test_missing_fields_are_survivable(self):
        self.assertEqual(resolve_grading({}), ('auto', ''))


class ExtractorEmitsTablesAsQuestionsTests(SimpleTestCase):
    """A table to fill in is answerable, so it must not go to the teacher."""

    def test_table_of_values_is_in_the_extractor_enum(self):
        from worksheets.services import WORKSHEET_CLASSIFICATION_TOOL
        props = (WORKSHEET_CLASSIFICATION_TOOL['input_schema']['properties']
                 ['questions']['items']['properties'])
        self.assertIn('table_of_values', props['question_type']['enum'])
        self.assertIn('table_spec', props)

    def test_the_prompt_prefers_a_table_question_over_teacher_marking(self):
        from worksheets.services import WORKSHEET_SYSTEM_PROMPT
        self.assertIn('TABLE TO COMPLETE', WORKSHEET_SYSTEM_PROMPT)
        self.assertIn('table_spec', WORKSHEET_SYSTEM_PROMPT)
        self.assertIn('prefer it over sending the table to the teacher',
                      WORKSHEET_SYSTEM_PROMPT)


class AIImportSharesTheRuleTests(SimpleTestCase):
    """The AI PDF import had no validation_type at all — a drawing question
    became an auto-graded typed answer with an invented correct value."""

    def test_ai_import_schema_carries_validation_type(self):
        from ai_import.services import CLASSIFICATION_TOOL
        props = (CLASSIFICATION_TOOL['input_schema']['properties']
                 ['questions']['items']['properties'])
        self.assertIn('validation_type', props)
        self.assertIn('human_graded', props['validation_type']['enum'])
        self.assertIn('grading_rubric', props)
