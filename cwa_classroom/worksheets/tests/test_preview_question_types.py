"""One question-type list behind the extractor and every review dropdown.

Three review pages (worksheet upload, homework upload, AI import) each kept
their own hand-written list of types for the "Question Type" ``<select>``, and
they had drifted from what the extractor actually emits: the worksheet page
offered 7 of 15 types, and none of the three offered ``table_of_values``.

That drift is invisible until a student gets the question. A ``<select>`` with
no ``<option>`` matching the value it was given renders showing its FIRST option
— "Multiple Choice" — and the preview POST reads that back, so a table question
became a multiple choice with nothing to tick and its ``table_spec`` was
stranded. So the schema enum is built from the shared list, and the dropdown
helper widens it with anything the session actually holds.
"""
from django.test import SimpleTestCase, TestCase

from worksheets.services import (
    EXTRACTED_QUESTION_TYPE_CHOICES,
    EXTRACTED_QUESTION_TYPES,
    NAME_THE_SHAPE_TYPE,
    WORKSHEET_CLASSIFICATION_TOOL,
    _normalise_name_the_shape,
    accepted_question_type,
    answer_review_warning,
    preview_question_type_choices,
)


def _enum():
    return (WORKSHEET_CLASSIFICATION_TOOL['input_schema']['properties']
            ['questions']['items']['properties']['question_type']['enum'])


class SharedListTests(SimpleTestCase):

    def test_the_extractor_enum_is_the_shared_list_plus_the_one_normalised_type(self):
        # name_the_shape is the one value the model may emit that never reaches
        # a dropdown: _normalise_name_the_shape turns it into multiple_choice
        # inside _classify_page_chunk, before any preview exists.
        self.assertEqual(list(_enum()), EXTRACTED_QUESTION_TYPES + [NAME_THE_SHAPE_TYPE])

    def test_every_emittable_type_has_a_dropdown_option_or_is_normalised_away(self):
        offered = {value for value, _ in preview_question_type_choices()}
        for q_type in _enum():
            with self.subTest(q_type):
                if q_type == NAME_THE_SHAPE_TYPE:
                    q = {'question_type': q_type, 'answers': [], 'image_bbox': None}
                    _normalise_name_the_shape([q])
                    self.assertIn(q['question_type'], offered)
                else:
                    self.assertIn(q_type, offered)

    def test_every_type_is_a_real_maths_question_type(self):
        # A type the model doesn't know maps to short_answer on import, which is
        # the same silent downgrade one step later.
        from maths.models import Question
        model_types = {value for value, _ in Question.QUESTION_TYPES}
        for q_type in EXTRACTED_QUESTION_TYPES:
            with self.subTest(q_type):
                self.assertIn(q_type, model_types)

    def test_labels_are_human_readable(self):
        for value, label in EXTRACTED_QUESTION_TYPE_CHOICES:
            with self.subTest(value):
                self.assertTrue(label and label[0].isupper(), label)


class DropdownCoversTheSessionTests(SimpleTestCase):

    def test_an_unknown_type_is_appended_rather_than_dropped(self):
        # draw_on_grid is the example because it is the type the extractor still
        # cannot emit (shape_select could not either, until its scenes started
        # being traced from the crop). A session holding one — from the question
        # builder, an older extractor, a hand-authored import — must still get an
        # <option>, or the browser shows the first one instead and the POST
        # silently rewrites the question to it.
        choices = preview_question_type_choices([
            {'question_type': 'draw_on_grid'},
            {'question_type': 'multiple_choice'},
        ])
        self.assertIn(('draw_on_grid', 'Draw On Grid'), choices)
        # Known types are not duplicated by the widening.
        self.assertEqual([v for v, _ in choices].count('multiple_choice'), 1)

    def test_blank_and_missing_types_add_nothing(self):
        self.assertEqual(
            preview_question_type_choices([{'question_type': ''}, {}]),
            EXTRACTED_QUESTION_TYPE_CHOICES,
        )

    def test_the_known_order_is_preserved(self):
        choices = preview_question_type_choices([{'question_type': 'draw_on_grid'}])
        self.assertEqual(choices[:len(EXTRACTED_QUESTION_TYPE_CHOICES)],
                         EXTRACTED_QUESTION_TYPE_CHOICES)


class AcceptedTypeTests(TestCase):
    """A posted type is taken only when it means something; otherwise the type
    the extractor worked out is kept, rather than overwritten with nothing."""

    def test_a_real_type_is_taken(self):
        self.assertEqual(
            accepted_question_type('table_of_values', 'multiple_choice'), 'table_of_values')

    def test_an_unknown_type_keeps_the_extracted_one(self):
        self.assertEqual(
            accepted_question_type('sudoku', 'table_of_values'), 'table_of_values')

    def test_a_missing_field_keeps_the_extracted_one(self):
        self.assertEqual(accepted_question_type(None, 'number_line'), 'number_line')
        self.assertEqual(accepted_question_type('   ', 'number_line'), 'number_line')

    def test_a_model_only_type_is_still_accepted(self):
        # The question builder can author types the extractor never emits; a
        # teacher picking one in the review page must not be ignored.
        self.assertEqual(
            accepted_question_type('shape_select', 'short_answer'), 'shape_select')


class ChoiceQuestionWithNoOptionsTests(SimpleTestCase):
    """The symptom the teacher actually sees: nothing to tick."""

    def test_a_multiple_choice_with_no_answers_is_flagged(self):
        warning = answer_review_warning({
            'question_type': 'multiple_choice', 'answers': [],
            'explanation': 'Cents are hundredths of a dollar.',
        })
        self.assertIsNotNone(warning)
        self.assertIn('no options', warning)

    def test_blank_option_text_does_not_count_as_an_option(self):
        warning = answer_review_warning({
            'question_type': 'true_false', 'answers': [{'text': '  ', 'is_correct': True}],
        })
        self.assertIsNotNone(warning)

    def test_a_real_multiple_choice_is_not_flagged_for_this(self):
        self.assertIsNone(answer_review_warning({
            'question_type': 'multiple_choice',
            'answers': [{'text': 'True', 'is_correct': True}, {'text': 'False'}],
        }))

    def test_types_that_are_graded_by_a_spec_are_not_flagged(self):
        self.assertIsNone(answer_review_warning({
            'question_type': 'table_of_values', 'answers': [],
            'explanation': 'Cents are hundredths of a dollar.',
        }))
