"""Unit tests for _strip_question_label — dropping leading question-number /
section labels ("Question 5 e)", "Q154", "PART C:", "5)", "a)") that the model
sometimes copies verbatim from a worksheet into question_text.
"""
from django.test import SimpleTestCase

from ai_import.services import _strip_question_label


class StripQuestionLabelTests(SimpleTestCase):
    def test_word_number_subpart_label(self):
        # Reported case: "Question 5 e)" prefix must go, the maths stays.
        self.assertEqual(
            _strip_question_label('Question 5 e) (+48) ÷ (+12) ='),
            '(+48) ÷ (+12) =',
        )

    def test_section_part_label(self):
        # Reported case: "PART C:" prefix must go, the stem stays intact.
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
            'b) 4xy': '4xy',
            '(iii) Solve for x': 'Solve for x',
            'Section B: Read the passage': 'Read the passage',
            'Exercise 3: Solve': 'Solve',
            'No. 5 Add the numbers': 'Add the numbers',
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(_strip_question_label(raw), expected)

    def test_real_text_is_not_clobbered(self):
        # Sentences that merely start like a label must be left untouched.
        keep = [
            'No cars are red in the picture.',
            'Problems arise when you divide by zero.',
            'A cat sat on the mat. How many legs?',
            '5 × y equals?',            # no delimiter after the number
            '3.5 is a decimal number.',  # "3." is not a label here
            '(x + 2)(x - 3) = ?',       # algebra, not a "(a)" label
            '12 apples cost $6. Find the unit price.',
            'Part time work: how many hours?',  # "Part" is a real word here
            # "A"/"I" articles after a word+colon must NOT be eaten as a sub-label.
            'Problem: A train leaves the station at 9am. When does it arrive?',
            'Question: A number is doubled. What is it?',
        ]
        for text in keep:
            with self.subTest(text=text):
                self.assertEqual(_strip_question_label(text), text)

    def test_stacked_labels(self):
        self.assertEqual(_strip_question_label('5. a) Simplify 2p'), 'Simplify 2p')

    def test_label_only_text_is_kept(self):
        # Stripping would empty the text — keep the original rather than blank it.
        self.assertEqual(_strip_question_label('Question 5'), 'Question 5')
        self.assertEqual(_strip_question_label('a)'), 'a)')

    def test_idempotent(self):
        once = _strip_question_label('Question 5 e) (+48) ÷ (+12) =')
        self.assertEqual(_strip_question_label(once), once)

    def test_empty_and_none(self):
        self.assertEqual(_strip_question_label(''), '')
        self.assertIsNone(_strip_question_label(None))
