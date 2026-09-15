"""Tests for the "What to check" strip on the PDF preview screens.

A question an import guard flags carries a prose ``review_reason``, and the
three preview screens used to hide it in the ``title=`` tooltip of a small
"⚠ Review" badge. Finding out what the verifier disliked therefore meant
hovering exactly the right 10px badge — or, in practice, re-reading the whole
question. ``ai_import.review_points`` splits that reason into one point per
field, and the strip shows them on the card with a chip that jumps to the field.

These pin the split itself (which is where the reasoning lives) against the
wording the guards actually write, and then that the strip reaches the page.
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from classroom.models import School

from ai_import.models import AIImportSession
from ai_import.review_points import (
    DEFAULT_REASON, classify_reason, review_points, unreviewed_questions,
)


def _points(reason, **extra):
    q = {'needs_review': True, 'review_reason': reason}
    q.update(extra)
    return review_points(q)


class ReviewPointFieldTests(TestCase):
    """Every guard's wording lands on the field a teacher would go and check."""

    def test_an_image_guard_points_at_the_image(self):
        points = _points(
            'Image check: the crop cuts off part of the figure (a label, axis '
            'number or edge is missing) — re-crop so it holds the whole figure '
            'and only the figure.')
        self.assertEqual([p['field'] for p in points], ['image'])
        self.assertEqual(points[0]['label'], 'Image')

    def test_a_disagreeing_second_opinion_points_at_the_answer(self):
        points = _points('Second-opinion check disagreed: verifier answered '
                         '"4" vs "5".')
        self.assertEqual([p['field'] for p in points], ['answer'])

    def test_a_contradictory_explanation_points_at_the_explanation(self):
        points = _points('The explanation says there are 5 but lists 4 '
                         '(1, 2, 3, 4) — recount, and check the answer that '
                         'depends on it.')
        self.assertEqual([p['field'] for p in points], ['explanation'])

    def test_a_reclassification_points_at_the_question_type(self):
        points = _points('Second-opinion classified this as "calculation", '
                         'not "short_answer".')
        self.assertEqual([p['field'] for p in points], ['type'])

    def test_an_answer_key_clash_sends_the_teacher_to_the_option_text(self):
        """The key's letter is only right if the options are in the order the
        AI read them — which is the thing to check, not the letter."""
        points = _points(
            "The paper's answer key says B. The AI had chosen option A — the "
            'key has been applied, please check it matches the option text.')
        self.assertEqual([p['field'] for p in points], ['answer', 'options'])

    def test_a_disputed_count_is_about_the_answer_not_the_picture(self):
        """Its reason opens "Image check:", but what is in doubt is the count
        the answer states — the picture itself is fine."""
        points = _points(
            'Image check: a second AI counted the squares and got 12 (3/3 '
            'agreed), but the imported answer is 10 — please confirm the count.')
        self.assertEqual([p['field'] for p in points], ['answer'])

    def test_wording_that_names_no_field_still_yields_a_point(self):
        points = _points('Second-opinion (vision) flagged a possible '
                         'extraction error: the units were dropped')
        self.assertEqual([p['field'] for p in points], ['question'])
        self.assertEqual(points[0]['label'], 'Question')

    def test_an_unclassifiable_sentence_is_not_a_point_of_its_own(self):
        """"Check it before importing." is an instruction about the finding
        before it, not a second thing to check."""
        self.assertIsNone(classify_reason('Check it before importing.'))
        points = _points(
            'The shapes could not be traced from the page, so this cannot be a '
            'colour-the-shapes question. Check it before importing.')
        self.assertEqual([p['field'] for p in points], ['image'])
        self.assertIn('Check it before importing.', points[0]['text'])


class ReviewPointSplitTests(TestCase):
    """Several guards can flag one question and join their reasons into one
    string — the teacher gets them back as separate points."""

    def test_reasons_about_different_fields_are_separate_points(self):
        points = _points(
            'Second-opinion check disagreed: verifier answered "4" vs "5". '
            'The explanation says there are 5 but lists 4 (1, 2, 3, 4) — '
            'recount, and check the answer that depends on it.')
        self.assertEqual([p['field'] for p in points], ['answer', 'explanation'])
        self.assertTrue(points[0]['text'].startswith('Second-opinion check'))
        self.assertTrue(points[1]['text'].startswith('The explanation says'))

    def test_a_finding_and_its_instruction_stay_one_point(self):
        points = _points(
            'Image check: this question refers to a figure but no image was '
            'attached — the figure may have been skipped on import. Crop or '
            'add the correct image, or confirm none is needed.')
        self.assertEqual(len(points), 1)
        self.assertIn('Crop or add the correct image', points[0]['text'])

    def test_an_abbreviation_does_not_split_a_reason(self):
        """`e.g.` ends in a full stop but not a sentence."""
        points = _points(
            'Image check: this question refers to a figure (e.g. "this shape" '
            '/ "the diagram") but no image was attached.')
        self.assertEqual(len(points), 1)
        self.assertIn('"this shape"', points[0]['text'])


class ReviewPointGuardTests(TestCase):
    def test_a_question_nobody_flagged_has_nothing_to_check(self):
        self.assertEqual(review_points({'question_text': 'Fine?'}), [])

    def test_a_flag_with_no_recorded_reason_keeps_the_badge_wording(self):
        points = _points('')
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]['text'], DEFAULT_REASON)

    def test_a_non_question_is_not_an_error(self):
        self.assertEqual(review_points(None), [])
        self.assertEqual(review_points('not a question'), [])


class AIImportReviewStripTests(TestCase):
    """The strip reaches the AI-import preview page."""

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser('airp', 'airp@x.com', 'pw')
        cls.school = School.objects.create(name='S', slug='airps', admin=cls.user)

    def _preview_html(self, **q0):
        q = {'question_text': 'Suspect?', 'question_type': 'short_answer',
             'needs_review': True, 'difficulty': 1, 'points': 1, 'include': True,
             'review_reason': 'Second-opinion check disagreed: verifier '
                              'answered "4" vs "5". The explanation says there '
                              'are 5 but lists 4 (1, 2, 3, 4) — recount.'}
        q.update(q0)
        session = AIImportSession.objects.create(
            user=self.user, school=self.school, pdf_filename='a.pdf',
            status=AIImportSession.STATUS_READY, page_count=1, is_confirmed=False,
            extracted_data={
                'year_level': 5, 'subject': 'Mathematics', 'strand': '', 'topic': '',
                'questions': [q, {'question_text': 'Fine?',
                                  'question_type': 'short_answer',
                                  'difficulty': 1, 'points': 1, 'include': True}],
            })
        self.client.force_login(self.user)
        return self.client.get(
            reverse('ai_import:preview', args=[session.pk])).content.decode()

    def test_the_reason_is_on_the_page_not_only_in_a_tooltip(self):
        html = self._preview_html()
        self.assertIn('data-testid="review-point-0-0"', html)
        self.assertIn('data-testid="review-point-0-1"', html)
        self.assertIn('verifier answered', html.replace('&quot;', '"'))
        self.assertIn('What to check', html)

    def test_each_point_offers_a_chip_to_its_own_field(self):
        html = self._preview_html()
        self.assertIn('data-review-jump="answer"', html)
        self.assertIn('data-review-jump="explanation"', html)
        # ...and the fields those chips scroll to are on the card.
        self.assertIn('data-review-field="answer"', html)
        self.assertIn('data-review-field="explanation"', html)

    def test_an_unflagged_question_gets_no_strip(self):
        html = self._preview_html()
        self.assertNotIn('data-testid="review-point-1-0"', html)

    def test_an_acknowledged_question_keeps_the_strip_but_hidden(self):
        """Ticking "Reviewed" clears the advice with the red highlight;
        un-ticking brings it back, so the markup stays."""
        html = self._preview_html(review_ack=True)
        self.assertIn('data-testid="review-point-0-0"', html)
        strip = html.split('id="review-points-0"')[0].rsplit('<div', 1)[1]
        self.assertIn('hidden', strip)


class UnreviewedQuestionTests(TestCase):
    """Which flagged questions are still outstanding when the teacher submits.

    The preview warns from the live checkboxes (the teacher may have just
    ticked one); this is what the confirm screen reads back from what was saved.
    """

    @staticmethod
    def _q(**extra):
        q = {'question_text': 'Q', 'question_type': 'short_answer'}
        q.update(extra)
        return q

    def test_a_flagged_question_nobody_ticked_is_outstanding(self):
        out = unreviewed_questions([
            self._q(needs_review=True, review_reason='Image check: re-crop the figure.')])
        self.assertEqual([u['number'] for u in out], [1])
        self.assertEqual(out[0]['labels'], ['Image'])

    def test_a_ticked_question_is_not_outstanding(self):
        self.assertEqual(
            unreviewed_questions([self._q(needs_review=True, review_ack=True)]), [])

    def test_an_unflagged_question_is_not_outstanding(self):
        self.assertEqual(unreviewed_questions([self._q()]), [])

    def test_an_excluded_question_is_not_held_against_the_import(self):
        """It is not being imported, so nobody has to check it."""
        self.assertEqual(
            unreviewed_questions([self._q(needs_review=True, include=False)]), [])

    def test_the_number_is_the_one_printed_on_the_preview(self):
        """Counting only the flagged ones would name "Q1" for the question the
        teacher sees as Q3."""
        out = unreviewed_questions([
            self._q(), self._q(), self._q(needs_review=True), self._q(),
            self._q(needs_review=True)])
        self.assertEqual([u['number'] for u in out], [3, 5])

    def test_an_excluded_question_still_does_not_shift_the_numbers(self):
        out = unreviewed_questions([
            self._q(include=False), self._q(needs_review=True)])
        self.assertEqual([u['number'] for u in out], [2])

    def test_no_questions_is_not_an_error(self):
        self.assertEqual(unreviewed_questions([]), [])
        self.assertEqual(unreviewed_questions(None), [])


class AIImportSubmitGateTests(AIImportReviewStripTests):
    """The preview offers the warning the submit needs, and the confirm screen
    says so again for anything that came through unticked."""

    def test_the_preview_carries_the_warning_and_the_question_numbers(self):
        html = self._preview_html()
        self.assertIn('data-testid="review-gate"', html)
        self.assertIn('data-testid="review-gate-continue"', html)
        # The warning names questions, so each card has to know its number.
        self.assertIn('data-review-number="1"', html)

    def test_the_confirm_screen_names_what_came_through_unchecked(self):
        session = AIImportSession.objects.create(
            user=self.user, school=self.school, pdf_filename='a.pdf',
            status=AIImportSession.STATUS_READY, page_count=1, is_confirmed=False,
            extracted_data={
                'year_level': 5, 'subject': 'Mathematics', 'strand': '', 'topic': '',
                'questions': [
                    {'question_text': 'Fine?', 'question_type': 'short_answer',
                     'difficulty': 1, 'points': 1, 'include': True},
                    {'question_text': 'Suspect?', 'question_type': 'short_answer',
                     'difficulty': 1, 'points': 1, 'include': True,
                     'needs_review': True, 'review_reason': 'answers disagree'},
                ],
            })
        self.client.force_login(self.user)
        html = self.client.get(
            reverse('ai_import:confirm', args=[session.pk])).content.decode()
        self.assertIn('data-testid="unreviewed-notice"', html)
        self.assertIn('Q2', html)
        self.assertIn('still need', html.replace('needs review', 'need review'))

    def test_the_confirm_screen_says_nothing_when_everything_was_checked(self):
        session = AIImportSession.objects.create(
            user=self.user, school=self.school, pdf_filename='b.pdf',
            status=AIImportSession.STATUS_READY, page_count=1, is_confirmed=False,
            extracted_data={
                'year_level': 5, 'subject': 'Mathematics', 'strand': '', 'topic': '',
                'questions': [
                    {'question_text': 'Suspect?', 'question_type': 'short_answer',
                     'difficulty': 1, 'points': 1, 'include': True,
                     'needs_review': True, 'review_reason': 'answers disagree',
                     'review_ack': True},
                ],
            })
        self.client.force_login(self.user)
        html = self.client.get(
            reverse('ai_import:confirm', args=[session.pk])).content.decode()
        self.assertNotIn('data-testid="unreviewed-notice"', html)
