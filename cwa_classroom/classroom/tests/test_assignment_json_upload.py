"""
Tests for authored JSON/ZIP question upload when creating a homework or
worksheet (as opposed to the global question-bank upload).

Covers:
  1. upload_services helpers — detect_assignment_subject + import_assignment_questions
     (maths school-scoping, coding global, coding_problem rejection, saved-ref dedup).
  2. Homework JSON upload flow — upload → json_confirm → Homework + HomeworkQuestion.
  3. Worksheet JSON upload flow — upload → json_confirm → Worksheet + WorksheetQuestion
     (maths and coding).

These paths skip AI extraction entirely, so the tests spend zero API tokens.
Run with: pytest classroom/tests/test_assignment_json_upload.py -v
"""
from __future__ import annotations

import io
import json

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import (
    ClassRoom, Level, School, SchoolTeacher, Subject,
)
from coding.models import CodingExercise, CodingLanguage, CodingTopic


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------

def _maths_payload(year_level=4, topic='Fractions', questions=None) -> bytes:
    if questions is None:
        questions = [
            {
                'question_text': 'What is 1/2 + 1/4?',
                'question_type': 'multiple_choice',
                'difficulty': 1,
                'points': 1,
                'answers': [
                    {'text': '3/4', 'is_correct': True, 'order': 1},
                    {'text': '1/2', 'is_correct': False, 'order': 2},
                ],
            },
        ]
    return json.dumps({
        'topic': topic,
        'year_level': year_level,
        'questions': questions,
    }).encode()


def _coding_payload(language='python', topic='loops', level='beginner',
                    exercises=None) -> bytes:
    if exercises is None:
        exercises = [{
            'title': 'Print 1-5',
            'instructions': 'Use a for loop to print 1 through 5.',
            'expected_output': '1\n2\n3\n4\n5',
            'display_order': 1,
        }]
    return json.dumps({
        'subject': 'coding',
        'language': language,
        'topic': topic,
        'level': level,
        'exercises': exercises,
    }).encode()


def _bytesfile(payload: bytes, name='questions.json'):
    f = io.BytesIO(payload)
    f.name = name
    return f


# ---------------------------------------------------------------------------
# 1. upload_services helpers
# ---------------------------------------------------------------------------

class DetectAssignmentSubjectTests(TestCase):

    def test_maths_is_default_when_subject_absent(self):
        from classroom.upload_services import detect_assignment_subject
        self.assertEqual(
            detect_assignment_subject(_bytesfile(_maths_payload())),
            'mathematics',
        )

    def test_coding_detected_from_subject_field(self):
        from classroom.upload_services import detect_assignment_subject
        self.assertEqual(
            detect_assignment_subject(_bytesfile(_coding_payload())),
            'coding',
        )

    def test_coding_problem_detected(self):
        from classroom.upload_services import detect_assignment_subject
        payload = json.dumps({'subject': 'coding_problem', 'problems': []}).encode()
        self.assertEqual(
            detect_assignment_subject(_bytesfile(payload)),
            'coding_problem',
        )

    def test_unreadable_file_falls_back_to_maths(self):
        from classroom.upload_services import detect_assignment_subject
        self.assertEqual(
            detect_assignment_subject(_bytesfile(b'not json {{{')),
            'mathematics',
        )

    def test_peek_rewinds_so_parser_can_reread(self):
        """detect_* must not consume the file — a subsequent read still sees it."""
        from classroom.upload_services import detect_assignment_subject
        f = _bytesfile(_maths_payload())
        detect_assignment_subject(f)
        # File pointer is back at the start, full content readable again.
        self.assertTrue(json.loads(f.read().decode())['questions'])


class ImportAssignmentQuestionsTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        owner_role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER, defaults={'display_name': 'Institute Owner'},
        )
        cls.owner = CustomUser.objects.create_user(
            'aj_owner', 'aj_owner@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.owner.roles.add(owner_role)
        cls.school = School.objects.create(
            name='AJ School', slug='aj-school', admin=cls.owner,
        )
        SchoolTeacher.objects.get_or_create(school=cls.school, teacher=cls.owner)
        Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        Level.objects.get_or_create(level_number=4, defaults={'display_name': 'Year 4'})

        cls.lang, _ = CodingLanguage.objects.get_or_create(
            slug='python',
            defaults={'name': 'Python', 'color': '#3776AB', 'order': 1, 'is_active': True},
        )
        cls.coding_topic, _ = CodingTopic.objects.get_or_create(
            language=cls.lang, slug='loops', defaults={'name': 'Loops', 'order': 1},
        )

    def test_maths_import_returns_saved_refs(self):
        from classroom.upload_services import import_assignment_questions
        from maths.models import Question as MathsQuestion
        result = import_assignment_questions(_bytesfile(_maths_payload()), self.owner)
        self.assertEqual(result['failed'], 0)
        self.assertEqual(len(result['saved']), 1)
        ref = result['saved'][0]
        self.assertEqual(ref['subject_slug'], 'mathematics')
        # The saved ref points at a real, school-scoped maths question.
        q = MathsQuestion.objects.get(pk=ref['content_id'])
        self.assertEqual(q.school_id, self.school.id)

    def test_coding_import_returns_saved_refs(self):
        from classroom.upload_services import import_assignment_questions
        result = import_assignment_questions(_bytesfile(_coding_payload()), self.owner)
        self.assertEqual(result['failed'], 0)
        self.assertEqual(len(result['saved']), 1)
        ref = result['saved'][0]
        self.assertEqual(ref['subject_slug'], 'coding')
        self.assertTrue(CodingExercise.objects.filter(pk=ref['content_id']).exists())

    def test_coding_problem_is_rejected(self):
        from classroom.upload_services import import_assignment_questions
        payload = json.dumps({'subject': 'coding_problem', 'problems': []}).encode()
        result = import_assignment_questions(_bytesfile(payload), self.owner)
        self.assertEqual(result['saved'], [])
        self.assertTrue(result['errors'])
        self.assertEqual(result['subject'], 'coding_problem')

    def test_saved_refs_deduped(self):
        """Two authored questions that upsert onto the same row yield one ref."""
        from classroom.upload_services import import_assignment_questions
        dup_q = {
            'question_text': 'What is 2 + 2?',
            'question_type': 'multiple_choice',
            'difficulty': 1, 'points': 1,
            'answers': [{'text': '4', 'is_correct': True, 'order': 1}],
        }
        payload = _maths_payload(questions=[dup_q, dict(dup_q)])
        result = import_assignment_questions(_bytesfile(payload), self.owner)
        self.assertEqual(len(result['saved']), 1)


# ---------------------------------------------------------------------------
# Shared teacher/school fixture for the view-level flows
# ---------------------------------------------------------------------------

class _AssignmentFlowBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        from classroom.models import ClassTeacher

        teacher_role, _ = Role.objects.get_or_create(
            name='teacher', defaults={'display_name': 'Teacher'},
        )
        cls.teacher = CustomUser.objects.create_user(
            'af_teacher', 'af_teacher@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.teacher.roles.add(teacher_role)

        cls.admin = CustomUser.objects.create_user(
            'af_admin', 'af_admin@example.com', 'pass1!',
        )
        cls.school = School.objects.create(
            name='AF School', slug='af-school', admin=cls.admin,
        )
        # Teacher belongs to the school (get_school_for_user / _get_question_scope)
        # and teaches the class (_assignable_classrooms via ClassTeacher).
        SchoolTeacher.objects.create(school=cls.school, teacher=cls.teacher, role='teacher')
        Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        Level.objects.get_or_create(level_number=4, defaults={'display_name': 'Year 4'})
        cls.classroom = ClassRoom.objects.create(name='AF Class', school=cls.school)
        ClassTeacher.objects.create(classroom=cls.classroom, teacher=cls.teacher)

        cls.lang, _ = CodingLanguage.objects.get_or_create(
            slug='python',
            defaults={'name': 'Python', 'color': '#3776AB', 'order': 1, 'is_active': True},
        )
        cls.coding_topic, _ = CodingTopic.objects.get_or_create(
            language=cls.lang, slug='loops', defaults={'name': 'Loops', 'order': 1},
        )

    def setUp(self):
        self.client.force_login(self.teacher)


# ---------------------------------------------------------------------------
# 2. Homework JSON upload flow
# ---------------------------------------------------------------------------

class HomeworkJSONUploadFlowTests(_AssignmentFlowBase):

    def test_upload_page_offers_json_input(self):
        resp = self.client.get(reverse('homework:pdf_upload'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('json_file', resp.content.decode())

    def test_json_upload_redirects_to_confirm(self):
        f = _bytesfile(_maths_payload())
        resp = self.client.post(reverse('homework:pdf_upload'), {'json_file': f})
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/homework/json/confirm/', resp.url)

        from homework.models import HomeworkUploadSession
        session = HomeworkUploadSession.objects.latest('created_at')
        self.assertEqual(session.status, HomeworkUploadSession.STATUS_DONE)
        self.assertEqual(len(session.extracted_data['saved']), 1)

    def test_confirm_page_renders(self):
        f = _bytesfile(_maths_payload())
        self.client.post(reverse('homework:pdf_upload'), {'json_file': f})
        from homework.models import HomeworkUploadSession
        session = HomeworkUploadSession.objects.latest('created_at')
        resp = self.client.get(reverse('homework:json_confirm', args=[session.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Confirm')

    def test_confirm_creates_homework_and_questions(self):
        f = _bytesfile(_maths_payload())
        self.client.post(reverse('homework:pdf_upload'), {'json_file': f})

        from homework.models import Homework, HomeworkQuestion, HomeworkUploadSession
        session = HomeworkUploadSession.objects.latest('created_at')

        resp = self.client.post(
            reverse('homework:json_confirm', args=[session.pk]),
            {
                'classroom_ids': [self.classroom.id],
                'due_date': '2026-12-31',
                'homework_title': 'JSON Homework',
            },
        )
        self.assertEqual(resp.status_code, 302)

        hw = Homework.objects.get(title='JSON Homework')
        self.assertEqual(hw.homework_type, 'json_upload')
        self.assertEqual(hw.classroom_id, self.classroom.id)
        hqs = HomeworkQuestion.objects.filter(homework=hw)
        self.assertEqual(hqs.count(), 1)
        hq = hqs.first()
        self.assertEqual(hq.subject_slug, 'mathematics')
        self.assertTrue(hq.content_id)
        self.assertEqual(hq.question_id, hq.content_id)

        session.refresh_from_db()
        self.assertTrue(session.is_confirmed)

    def test_confirm_requires_classroom(self):
        f = _bytesfile(_maths_payload())
        self.client.post(reverse('homework:pdf_upload'), {'json_file': f})
        from homework.models import HomeworkUploadSession, Homework
        session = HomeworkUploadSession.objects.latest('created_at')
        resp = self.client.post(
            reverse('homework:json_confirm', args=[session.pk]),
            {'due_date': '2026-12-31'},
        )
        self.assertEqual(resp.status_code, 302)  # bounced back, no homework made
        self.assertFalse(Homework.objects.exists())

    def test_bad_file_redirects_with_error(self):
        f = _bytesfile(b'not json {{{')
        resp = self.client.post(reverse('homework:pdf_upload'), {'json_file': f})
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/homework/pdf/upload/', resp.url)
        from homework.models import HomeworkUploadSession
        self.assertFalse(HomeworkUploadSession.objects.exists())


# ---------------------------------------------------------------------------
# 3. Worksheet JSON upload flow
# ---------------------------------------------------------------------------

class WorksheetJSONUploadFlowTests(_AssignmentFlowBase):

    def test_upload_page_offers_json_input(self):
        resp = self.client.get(reverse('worksheets:upload'))
        self.assertEqual(resp.status_code, 200)
        self.assertIn('json_file', resp.content.decode())

    def test_maths_json_upload_creates_worksheet(self):
        f = _bytesfile(_maths_payload())
        resp = self.client.post(reverse('worksheets:upload'), {'json_file': f})
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/upload/json/', resp.url)

        from worksheets.models import (
            Worksheet, WorksheetQuestion, WorksheetUploadSession,
        )
        session = WorksheetUploadSession.objects.latest('created_at')
        # Confirm page renders (catches template errors).
        get_resp = self.client.get(reverse('worksheets:json_confirm', args=[session.pk]))
        self.assertEqual(get_resp.status_code, 200)
        resp = self.client.post(
            reverse('worksheets:json_confirm', args=[session.pk]),
            {'worksheet_name': 'JSON Worksheet'},
        )
        self.assertEqual(resp.status_code, 302)

        ws = Worksheet.objects.get(name='JSON Worksheet')
        self.assertEqual(ws.question_count, 1)
        wq = WorksheetQuestion.objects.get(worksheet=ws)
        self.assertEqual(wq.subject_slug, 'mathematics')
        self.assertEqual(wq.question_id, wq.content_id)

    def test_coding_json_upload_creates_worksheet_with_coding_link(self):
        f = _bytesfile(_coding_payload())
        resp = self.client.post(reverse('worksheets:upload'), {'json_file': f})
        self.assertEqual(resp.status_code, 302)

        from worksheets.models import WorksheetQuestion, WorksheetUploadSession, Worksheet
        session = WorksheetUploadSession.objects.latest('created_at')
        self.client.post(
            reverse('worksheets:json_confirm', args=[session.pk]),
            {'worksheet_name': 'Coding Worksheet'},
        )
        ws = Worksheet.objects.get(name='Coding Worksheet')
        wq = WorksheetQuestion.objects.get(worksheet=ws)
        self.assertEqual(wq.subject_slug, 'coding')
        self.assertIsNone(wq.question_id)
        self.assertEqual(wq.coding_exercise_id, wq.content_id)
