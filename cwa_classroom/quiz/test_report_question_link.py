"""The "Report a problem with this question" link on the quiz card (CPP-398).

The card is swapped in by innerHTML, which HTMX never gets to process, so the
button carries a data attribute and the persistent extra_js block delegates the
click. A regression here is quiet by nature — the link would work on the first
question of a quiz and do nothing on every one after it — so it is pinned.
"""
from django.template.loader import render_to_string
from django.test import TestCase

from classroom.models import Level, Subject, Topic
from maths.models import Answer, Question


class ReportLinkOnTheQuestionCardTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.subject = Subject.objects.create(name='Maths', slug='rl-maths')
        cls.level = Level.objects.create(level_number=7, display_name='Year 7')
        cls.topic = Topic.objects.create(
            name='Fractions', slug='rl-fractions', subject=cls.subject)
        cls.question = Question.objects.create(
            question_text='What is 1/2 + 1/4?', question_type='multiple_choice',
            topic=cls.topic, level=cls.level)
        Answer.objects.create(question=cls.question, answer_text='3/4',
                              is_correct=True, order=0)

    def _render_card(self):
        return render_to_string('quiz/partials/topic_question.html', {
            'question': self.question,
            'answers': list(self.question.answers.all()),
            'question_number': 2,
            'total_questions': 3,
            'session_id': 'report-session',
        })

    def test_the_card_offers_a_way_to_report_the_question(self):
        html = self._render_card()
        self.assertIn('data-report-question', html)
        self.assertIn('Report a problem with this question', html)

    def test_the_link_names_the_question_it_is_about(self):
        """Without the id the report is untraceable — the CPP-398 defect."""
        html = self._render_card()
        self.assertIn(f'data-report-question="{self.question.id}"', html)

    def test_the_card_still_carries_no_inline_script(self):
        """A script tag here would be dead after the first innerHTML swap."""
        html = self._render_card()
        self.assertNotIn('<' + 'script', html.lower())

    def test_the_link_carries_no_htmx_attributes(self):
        """HTMX never processes this card, so hx-get here would silently no-op."""
        card = self._render_card()
        marker = card[card.index('data-report-question'):]
        button = marker[:marker.index('</button>')]
        self.assertNotIn('hx-get', button)

    def test_the_quiz_page_delegates_the_click(self):
        """Delegation is what makes the link work after a question swap."""
        page = render_to_string('quiz/topic_quiz.html', {
            'topic': self.topic,
            'level': self.level,
            'question': self.question,
            'answers': list(self.question.answers.all()),
            'question_number': 1,
            'total_questions': 3,
            'session_id': 'report-session',
        })
        self.assertIn("closest('[data-report-question]')", page)
        self.assertIn('report-question', page)
        self.assertIn('htmx.ajax', page)
