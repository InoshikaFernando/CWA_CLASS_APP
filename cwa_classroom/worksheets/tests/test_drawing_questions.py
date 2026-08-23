"""Questions whose answer is a DRAWING must be teacher-graded, never AI-graded.

"Draw a tree diagram to illustrate this situation." A student has no way to draw
anything in this app, so importing that as ai_graded hands them a text box and
marks them wrong however well they drew it on paper. These are routed to
human_graded, which the rest of the app already handles: quizzes hide them
(``quiz.views.gradable_for``) and the upload preview leaves them unticked.

Zero-token: no Anthropic client is built and no API call is made.
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from worksheets import services
from worksheets.services import (
    is_unanswerable_construction,
    route_constructions_to_teacher,
)


class IsUnanswerableConstructionTests(SimpleTestCase):
    """A construction VERB plus the visual it produces — both halves required."""

    DRAWING_QUESTIONS = [
        'Draw a tree diagram to illustrate this situation.',
        'Draw a Venn diagram to show the two sets.',
        'Sketch the graph of y = 2x + 1.',
        'Construct a triangle with sides 5 cm, 6 cm and 7 cm using compasses.',
        'Shade 1/4 of the shape below.',
        'Colour the region that satisfies both inequalities.',
        'Complete the table of values for y = 3x.',
        'Draw a bar chart to display this data.',
        'Draw the net of the cube.',
        'Join the points to form a quadrilateral.',
        'Label the angle marked with a letter x.',
        'Copy the diagram and mark the line of symmetry.',
        'On the grid, draw an accurate scale drawing of the field.',
    ]

    # The same drawing, asked for without the word "draw". A worksheet says
    # "illustrate on", "represent in", "record in", "use a" just as often, and
    # every one of these leaves the student with a picture to produce.
    DRAWING_QUESTIONS_WITHOUT_A_DRAW_VERB = [
        'Suppose we are rolling a die, so the universal set U = {1, 2, 3, 4, 5, 6}. '
        'Illustrate on a Venn diagram the sets A = {1, 3, 5} and B = {2, 4, 6}.',
        'Show the information on a bar graph.',
        'Show this set on a number line.',
        'Represent this data in a pie chart.',
        'Display the results using a pictograph.',
        'Summarise the results in a frequency table.',
        'Group the animals in a Venn diagram.',
        'Sort these numbers into the Venn diagram.',
        'Record your results in a tally chart.',
        'Put the numbers in the correct place on the Venn diagram.',
        'Add the following elements to the Venn diagram.',
        'Use a tree diagram to work out the probability of two heads.',
        'Use a scatter graph to display the relationship.',
    ]

    # Each of these either mentions a figure without asking for one to be made,
    # or uses a construction verb on something that is not a visual. Marking any
    # of them teacher-graded would hide a perfectly gradable question from every
    # student, so the false-positive side matters as much as the catch rate.
    ANSWERABLE_QUESTIONS = [
        'What is 24 divided by 6?',
        'Use the diagram to find the missing angle.',
        'The graph shows the temperature over 5 days. What was the highest?',
        'Explain why Stefan cannot be correct.',
        'Draw a conclusion from the results and explain your reasoning.',
        'Circle the largest number.',
        'Complete the sentence: a triangle has ___ sides.',
        'Complete the pattern: 2, 4, 6, __, __',
        'Complete the calculation to find the angle x.',
        'Calculate the area of the shape shown below.',
        'From the table, which city had the largest range?',
        'Write down the coordinates of the point marked A.',
        # "Show that" is a proof to AI-grade, not a drawing.
        'Show that the angle x = 40 degrees.',
        'Show that the two triangles are congruent.',
        'Show your working.',
        # A figure that already exists is read, not built.
        'Use the Venn diagram below to find n(A and B).',
        'The bar graph shows how many students chose each colour. How many chose blue?',
        'The results are shown in the table below. How many students were absent?',
        'The data is recorded in the table. What is the mode?',
        'Which number is represented on the number line?',
        'Explain, using the graph, why the trend is increasing.',
        # Ordinary instructions that happen to use a placement verb.
        'Add the numbers in the table.',
        'Put the numbers in order from smallest to largest.',
        'Write your answer in the box.',
        'Use a square number greater than 20.',
        'Use a protractor to measure the angle.',
        'Use a calculator to find the answer.',
    ]

    def test_drawing_instructions_are_unanswerable(self):
        for text in self.DRAWING_QUESTIONS:
            with self.subTest(text):
                self.assertTrue(is_unanswerable_construction({'question_text': text}))

    def test_drawings_asked_for_without_a_draw_verb(self):
        for text in self.DRAWING_QUESTIONS_WITHOUT_A_DRAW_VERB:
            with self.subTest(text):
                self.assertTrue(is_unanswerable_construction({'question_text': text}))

    def test_answerable_questions_are_left_alone(self):
        for text in self.ANSWERABLE_QUESTIONS:
            with self.subTest(text):
                self.assertFalse(is_unanswerable_construction({'question_text': text}))

    def test_types_the_app_draws_are_exempt(self):
        # The app renders these answer surfaces itself and grades them, so
        # "draw"/"plot" IS answerable there.
        exempt = [
            ('Draw a number line from -3 to 7 and show 2.', 'number_line'),
            ('Plot the point (3, -2) on the grid.', 'plot_points'),
            ('Plot and join the points to draw the line.', 'plot_line'),
            ('Draw the angle and measure it.', 'measure'),
        ]
        for text, q_type in exempt:
            with self.subTest(q_type):
                self.assertFalse(is_unanswerable_construction(
                    {'question_text': text, 'question_type': q_type}))

    def test_multiple_choice_with_options_is_exempt(self):
        # The student picks an option; nobody has to draw anything.
        self.assertFalse(is_unanswerable_construction({
            'question_text': 'Which diagram shows the line drawn correctly?',
            'question_type': 'multiple_choice',
            'answers': [{'text': 'A'}, {'text': 'B'}],
        }))

    def test_multiple_choice_without_options_is_not_exempt(self):
        # The type label alone is not an answer surface — with no options the
        # student is still being asked to draw.
        self.assertTrue(is_unanswerable_construction({
            'question_text': 'Draw a tree diagram to illustrate this situation.',
            'question_type': 'multiple_choice',
            'answers': [],
        }))

    def test_missing_question_text_is_not_a_construction(self):
        self.assertFalse(is_unanswerable_construction({}))


class RouteConstructionsToTeacherTests(SimpleTestCase):

    def test_venn_diagram_illustration_becomes_human_graded(self):
        # The reported case: extracted as an ai_graded extended answer with a
        # rubric describing the picture the student was supposed to draw.
        questions = [{
            'question_text': 'Suppose we are rolling a die, so the universal set '
                             'U = {1, 2, 3, 4, 5, 6}. Illustrate on a Venn diagram '
                             'the sets A = {1, 3, 5} and B = {2, 4, 6}.',
            'question_type': 'extended_answer',
            'validation_type': 'ai_graded',
            'grading_rubric': 'Full marks: A and B are disjoint so the circles do '
                              'not overlap; 1, 3, 5 in A; 2, 4, 6 in B.',
        }]
        self.assertEqual(route_constructions_to_teacher(questions), 1)
        self.assertEqual(questions[0]['validation_type'], 'human_graded')
        # The rubric the model wrote is what the teacher marks against, so it stays.
        self.assertIn('circles do not overlap', questions[0]['grading_rubric'])

    def test_ai_graded_drawing_becomes_human_graded(self):
        questions = [{
            'question_text': 'Draw a tree diagram to illustrate this situation.',
            'question_type': 'extended_answer',
            'validation_type': 'ai_graded',
        }]
        self.assertEqual(route_constructions_to_teacher(questions), 1)
        self.assertEqual(questions[0]['validation_type'], 'human_graded')
        self.assertIn('draw', questions[0]['grading_rubric'].lower())

    def test_auto_graded_drawing_becomes_human_graded(self):
        questions = [{
            'question_text': 'Shade 1/4 of the shape below.',
            'question_type': 'short_answer',
            'validation_type': 'auto',
        }]
        self.assertEqual(route_constructions_to_teacher(questions), 1)
        self.assertEqual(questions[0]['validation_type'], 'human_graded')

    def test_existing_rubric_is_kept(self):
        questions = [{
            'question_text': 'Draw a Venn diagram to show the two sets.',
            'validation_type': 'ai_graded',
            'grading_rubric': 'Both circles overlap; 3 in the intersection.',
        }]
        route_constructions_to_teacher(questions)
        self.assertEqual(questions[0]['grading_rubric'],
                         'Both circles overlap; 3 in the intersection.')

    def test_already_human_graded_is_not_recounted(self):
        questions = [{
            'question_text': 'Draw a tree diagram to illustrate this situation.',
            'validation_type': 'human_graded',
        }]
        self.assertEqual(route_constructions_to_teacher(questions), 0)

    def test_ordinary_questions_are_untouched(self):
        questions = [
            {'question_text': 'What is 3 + 4?', 'validation_type': 'auto'},
            {'question_text': 'Explain why Stefan cannot be correct.',
             'validation_type': 'ai_graded'},
        ]
        self.assertEqual(route_constructions_to_teacher(questions), 0)
        self.assertEqual([q['validation_type'] for q in questions],
                         ['auto', 'ai_graded'])

    def test_empty_input(self):
        self.assertEqual(route_constructions_to_teacher(None), 0)
        self.assertEqual(route_constructions_to_teacher([]), 0)


class DrawingQuestionsReachThePreviewUntickedTests(SimpleTestCase):
    """End-to-end through the shared pipeline both upload paths use.

    ``extract_and_classify_worksheet`` backs the worksheet AND the homework PDF
    upload, so re-routing there covers both previews.
    """

    def _run(self, classified_questions):
        with patch.dict('sys.modules', {'fitz': MagicMock()}), \
             patch('worksheets.services.extract_worksheet_pages',
                   return_value={'pages': [], 'page_count': 1}), \
             patch('worksheets.services.classify_worksheet_questions',
                   return_value={'questions': classified_questions,
                                 'usage': {'total_tokens': 0}}), \
             patch('worksheets.services.render_question_images',
                   side_effect=lambda doc, pages, result, progress=None: (result, {})), \
             patch('worksheets.services._second_opinion', return_value=None):
            output = services.extract_and_classify_worksheet(
                MagicMock(read=lambda: b'%PDF-1.4'), [], [])
        return output['result']['questions']

    def test_ai_graded_drawing_arrives_teacher_graded_and_deselected(self):
        questions = self._run([
            {'question_text': 'Draw a tree diagram to illustrate this situation.',
             'question_type': 'extended_answer', 'validation_type': 'ai_graded'},
            {'question_text': 'What is 24 divided by 6?',
             'question_type': 'short_answer', 'validation_type': 'auto'},
        ])
        drawing, arithmetic = questions
        self.assertEqual(drawing['validation_type'], 'human_graded')
        self.assertFalse(drawing['include'])
        # The rest of the worksheet imports exactly as before.
        self.assertEqual(arithmetic['validation_type'], 'auto')
        self.assertTrue(arithmetic['include'])

    def test_number_line_question_still_imports_auto_graded(self):
        questions = self._run([
            {'question_text': 'Draw a number line from -3 to 7 and show 2.',
             'question_type': 'number_line', 'validation_type': 'auto'},
        ])
        self.assertEqual(questions[0]['validation_type'], 'auto')
        self.assertTrue(questions[0]['include'])


class PromptTellsTheModelToUseHumanGradedTests(SimpleTestCase):
    """The deterministic guard is a safety net, not the primary mechanism — the
    model is told the rule up front so the rubric it writes is the teacher's."""

    def test_system_prompt_carries_the_drawing_rule(self):
        prompt = services.WORKSHEET_SYSTEM_PROMPT
        self.assertIn('DRAWING / CONSTRUCTION', prompt)
        self.assertIn('Draw a tree diagram', prompt)
        self.assertIn('NOT ai_graded', prompt)
        # The app's own drawing surfaces must stay auto-graded.
        self.assertIn('EXCEPTIONS', prompt)

    def test_tool_schema_says_human_graded_covers_drawings(self):
        properties = (services.WORKSHEET_CLASSIFICATION_TOOL['input_schema']
                      ['properties']['questions']['items']['properties'])
        description = properties['validation_type']['description']
        self.assertIn('DRAWING', description)
