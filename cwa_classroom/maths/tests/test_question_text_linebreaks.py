"""Question text with line breaks must render with those breaks (CPP-406 follow-up).

135 of the bank's 20,745 questions contain a newline, and they are not stray:
they carry structure the author put there —

    'Which is the shortest?\\n\\nA) Your finger\\nB) A spoon\\nC) A book'

Every surface rendered that text inside a plain <p>, and HTML collapses
whitespace, so all 135 displayed as one run-on line. The fix is one Tailwind
class, ``whitespace-pre-line``, which honours newlines while still collapsing
runs of spaces (``pre-wrap`` would also preserve PDF indentation, which is not
wanted).

This test pins the class on every surface where a person reads a whole
question — answering it, reviewing a mark, or grading one. Truncated list
views are deliberately excluded: they are ``line-clamp``-ed summaries, and
honouring newlines there would break the row layout.
"""
from django.test import TestCase

# Only the surfaces that show a question IN FULL.
FULL_QUESTION_TEMPLATES = [
    'templates/homework/partials/_maths_take_item.html',
    'templates/homework/partials/_maths_result_item.html',
    'templates/homework/student/quiz.html',
    'templates/homework/pending_review.html',
    'templates/homework/grade_answer.html',
    'templates/quiz/partials/topic_question.html',
    'templates/quiz/mixed_quiz.html',
    'templates/worksheets/session.html',
    'templates/worksheets/detail.html',
    'templates/worksheets/assignment_detail.html',
]


def _question_text_lines(path):
    """Lines that print question_text into the page (not into a textarea)."""
    from pathlib import Path
    from django.conf import settings

    text = (Path(settings.BASE_DIR) / path).read_text()
    return [
        line for line in text.split('\n')
        if 'question_text' in line
        and '{{' in line
        and 'textarea' not in line
        and 'data-speak' not in line
        and 'id_for_label' not in line
    ]


class QuestionTextLineBreakTests(TestCase):

    def test_every_full_question_surface_honours_line_breaks(self):
        for path in FULL_QUESTION_TEMPLATES:
            with self.subTest(path):
                lines = _question_text_lines(path)
                self.assertTrue(lines, f'{path} no longer prints question_text')
                for line in lines:
                    self.assertIn(
                        'whitespace-pre-line', line,
                        f'{path} prints question_text without '
                        f'whitespace-pre-line, so a multi-line question '
                        f'renders as one run-on line:\n    {line.strip()}')


class MultiLineQuestionRenderTests(TestCase):
    """The take partial, rendered, keeps the newlines in its output."""

    @classmethod
    def setUpTestData(cls):
        from classroom.models import Level
        cls.level, _ = Level.objects.get_or_create(
            level_number=963, defaults={'display_name': 'linebreak fixture'})

    def test_the_take_page_emits_the_newlines_and_the_class(self):
        from django.template.loader import render_to_string
        from maths.models import Answer, Question

        q = Question.objects.create(
            level=self.level,
            question_text='Which is the shortest?\n\nA) Your finger\nB) A spoon',
            question_type=Question.MULTIPLE_CHOICE, difficulty=1, points=1)
        Answer.objects.create(question=q, answer_text='A', is_correct=True, order=0)
        Answer.objects.create(question=q, answer_text='B', is_correct=False, order=1)

        html = render_to_string(
            'homework/partials/_maths_take_item.html',
            {'ctx': {'question': q, 'shuffled_answers': list(q.answers.all())}})

        self.assertIn('whitespace-pre-line', html)
        # The newlines survive into the markup; the class is what makes the
        # browser honour them rather than collapsing them to a space.
        self.assertIn('A) Your finger\nB) A spoon', html)
