"""Unit tests for _strip_question_label — dropping leading question-number /
section labels ("Question 5 e)", "Q154", "PART C:", "5)", "a)") that the model
sometimes copies verbatim from a worksheet into question_text.
"""
from django.test import SimpleTestCase

from worksheets.services import _strip_question_label


class StripQuestionLabelTests(SimpleTestCase):
    def test_word_number_subpart_label(self):
        self.assertEqual(
            _strip_question_label('Question 5 e) (+48) ÷ (+12) ='),
            '(+48) ÷ (+12) =',
        )

    def test_section_part_label(self):
        self.assertEqual(
            _strip_question_label(
                'PART C: Sharing a Profit and Loss. A loss of $48 is shared '
                'equally among 8 workers. What is each worker\'s final amount?'
            ),
            'Sharing a Profit and Loss. A loss of $48 is shared equally among '
            '8 workers. What is each worker\'s final amount?',
        )

    def test_various_labels_stripped(self):
        cases = {
            'Q154 Simplify 3x + 2x': 'Simplify 3x + 2x',
            'Q7. What is 3 + 4?': 'What is 3 + 4?',
            '5) 3 + 4 =': '3 + 4 =',
            '12. Find the sum.': 'Find the sum.',
            'a) x × y': 'x × y',
            '(iii) Solve for x': 'Solve for x',
            'Section B: Read the passage': 'Read the passage',
            'Exercise 3: Solve': 'Solve',
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(_strip_question_label(raw), expected)

    def test_real_text_is_not_clobbered(self):
        keep = [
            'No cars are red in the picture.',
            'Problems arise when you divide by zero.',
            'A cat sat on the mat. How many legs?',
            '5 × y equals?',
            '3.5 is a decimal number.',
            '(x + 2)(x - 3) = ?',
            '12 apples cost $6. Find the unit price.',
        ]
        for text in keep:
            with self.subTest(text=text):
                self.assertEqual(_strip_question_label(text), text)

    def test_label_only_text_is_kept(self):
        self.assertEqual(_strip_question_label('Question 5'), 'Question 5')

    def test_idempotent(self):
        once = _strip_question_label('PART C: Find the total.')
        self.assertEqual(_strip_question_label(once), once)

    def test_empty_and_none(self):
        self.assertEqual(_strip_question_label(''), '')
        self.assertIsNone(_strip_question_label(None))
