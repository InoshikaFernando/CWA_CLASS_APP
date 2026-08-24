"""CPP-389 — "Preview as student" on the homework PDF review screen.

The review screen is an editing form; it cannot show what the student meets.
These tests cover the promise the preview makes: the real student template, the
real grader, the teacher's unsaved edits, and — the one that matters most — that
looking at a question never puts anything in the question bank.
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import Level, School, SchoolTeacher, Subject, Topic
from maths.models import Answer, Question

from .models import HomeworkUploadSession

_PNG_B64 = (
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9'
    'awAAAABJRU5ErkJggg=='
)


class HomeworkStudentPreviewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        role, _ = Role.objects.get_or_create(
            name='teacher', defaults={'display_name': 'Teacher'})
        cls.teacher = CustomUser.objects.create_user('t1', 't1@x.com', 'pw')
        cls.teacher.roles.add(role)
        cls.other = CustomUser.objects.create_user('t2', 't2@x.com', 'pw')
        cls.other.roles.add(role)
        admin = CustomUser.objects.create_user('a', 'a@x.com', 'pw')
        cls.school = School.objects.create(name='S', slug='s', admin=admin)
        SchoolTeacher.objects.create(school=cls.school, teacher=cls.teacher, role='teacher')
        cls.level = Level.objects.create(level_number=5, display_name='Year 5')
        subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        Topic.objects.create(subject=subject, name='Decimals', slug='decimals')

    def _session(self, questions=None, images=None):
        return HomeworkUploadSession.objects.create(
            user=self.teacher, school=self.school, pdf_filename='t.pdf',
            status=HomeworkUploadSession.STATUS_DONE, page_count=1, is_confirmed=False,
            extracted_data={
                'year_level': 5,
                'topic': 'Decimals',
                'questions': questions or [{
                    'question_text': '20¢ is ______ of a dollar.',
                    'question_type': 'short_answer',
                    'validation_type': 'auto',
                    'answers': [{'text': 'twenty hundredths', 'is_correct': True}],
                    'explanation': '20 out of 100 cents.',
                    'include': True,
                }],
            },
            extracted_images=images or {},
        )

    def _post(self, session, idx=0, extra=None, user=None):
        self.client.force_login(user or self.teacher)
        data = {
            'preview_index': idx,
            f'q_{idx}_text': '20¢ is ______ of a dollar.',
            f'q_{idx}_type': 'short_answer',
            f'q_{idx}_validation_type': 'auto',
            f'q_{idx}_difficulty': '1',
            f'q_{idx}_points': '1',
            f'q_{idx}_answer_0_text': 'twenty hundredths',
            f'q_{idx}_answer_0_correct': 'on',
            f'q_{idx}_explanation': '20 out of 100 cents.',
        }
        data.update(extra or {})
        return self.client.post(
            reverse('homework:pdf_question_preview', args=[session.pk]), data)

    # --- rendering ---------------------------------------------------------
    def test_preview_renders_the_real_student_template(self):
        response = self._post(self._session())
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'homework/partials/_maths_take_item.html',
            [t.name for t in response.templates],
        )

    def test_preview_uses_unsaved_edits_from_the_form(self):
        session = self._session()
        response = self._post(session, extra={'q_0_text': 'Edited in the browser'})
        self.assertContains(response, 'Edited in the browser')
        # The session itself is untouched — previewing is not saving.
        session.refresh_from_db()
        self.assertEqual(
            session.extracted_data['questions'][0]['question_text'],
            '20¢ is ______ of a dollar.',
        )

    def test_preview_shows_the_draft_image_without_storing_it(self):
        session = self._session(
            questions=[{
                'question_text': 'Name this shape.',
                'question_type': 'short_answer',
                'image_ref': 'fig.png',
                'answers': [{'text': 'triangle', 'is_correct': True}],
            }],
            images={'fig.png': _PNG_B64},
        )
        response = self._post(session, extra={
            'q_0_text': 'Name this shape.',
            'q_0_image_ref': 'fig.png',
            'q_0_answer_0_text': 'triangle',
        })
        self.assertContains(response, 'data:image/png;base64,')

    # --- marking -----------------------------------------------------------
    def test_a_right_answer_is_marked_right(self):
        response = self._post(
            self._session(), extra={'preview_answer': 'Twenty Hundredths'})
        self.assertContains(response, 'Marked correct')

    def test_a_wrong_answer_is_marked_wrong_and_shows_what_is_accepted(self):
        response = self._post(self._session(), extra={'preview_answer': '0.20'})
        self.assertContains(response, 'Marked wrong')
        self.assertContains(response, 'twenty hundredths')

    def test_no_answer_typed_means_no_mark(self):
        response = self._post(self._session())
        self.assertNotContains(response, 'Marked correct')
        self.assertNotContains(response, 'Marked wrong')

    # --- the promise that nothing is written -------------------------------
    def test_preview_writes_nothing_to_the_question_bank(self):
        session = self._session()
        before_q = Question.objects.count()
        before_a = Answer.objects.count()
        self._post(session, extra={'preview_answer': 'twenty hundredths'})
        self.assertEqual(Question.objects.count(), before_q)
        self.assertEqual(Answer.objects.count(), before_a)

    # --- access ------------------------------------------------------------
    def test_another_teachers_session_cannot_be_previewed(self):
        session = self._session()
        response = self._post(session, user=self.other)
        self.assertEqual(response.status_code, 404)

    def test_a_missing_index_is_refused_rather_than_guessed(self):
        session = self._session()
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('homework:pdf_question_preview', args=[session.pk]), {})
        self.assertEqual(response.status_code, 400)

    # --- this flow's own truth about gaps ----------------------------------
    def test_a_gapped_sentence_is_shown_as_the_single_box_this_flow_imports(self):
        """The homework saver does not promote "___" to gaps — say so.

        ``ai_import.services.save_questions_from_session`` calls
        ``apply_blank_format`` and this flow's saver does not, so the same
        sentence imports differently depending on which screen the teacher
        used. The preview must report what THIS flow does rather than a
        flattering guess.
        """
        response = self._post(self._session())
        self.assertContains(response, 'keeps it as ONE answer box')

    # --- the review page is wired to it ------------------------------------
    def test_the_review_page_offers_the_preview(self):
        session = self._session()
        self.client.force_login(self.teacher)
        html = self.client.get(
            reverse('homework:pdf_preview', args=[session.pk])).content.decode()
        self.assertIn('data-preview-open="0"', html)
        self.assertIn('data-preview-all', html)
        self.assertIn('question-preview/', html)
