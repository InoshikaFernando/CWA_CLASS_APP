"""Name-the-shape mode — service threading, DPI, model/view wiring."""
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School, SchoolTeacher
from worksheets import services
from worksheets.models import WorksheetUploadSession


class BuildSystemPromptTests(SimpleTestCase):
    def test_shape_naming_uses_shape_prompt(self):
        prompt = services._build_system_prompt([], [], shape_naming=True)
        self.assertIn('name the shape', prompt.lower())
        self.assertIn('What is the name of this shape?', prompt)

    def test_default_uses_standard_worksheet_prompt(self):
        prompt = services._build_system_prompt([], [], shape_naming=False)
        self.assertIn('reading school homework worksheets', prompt)
        self.assertNotIn('What is the name of this shape?', prompt)


class ExtractWorksheetPagesDpiTests(SimpleTestCase):
    def _fake_doc(self, captured):
        page = MagicMock()
        page.get_text.return_value = 'txt'
        pix = MagicMock(width=10, height=12)
        pix.tobytes.return_value = b'img'

        def _get_pixmap(dpi):
            captured['dpi'] = dpi
            return pix
        page.get_pixmap.side_effect = _get_pixmap
        page.rect.width = 100.0
        page.rect.height = 140.0
        doc = MagicMock()
        doc.__len__.return_value = 1
        doc.__getitem__.return_value = page
        return doc

    def test_default_dpi(self):
        captured = {}
        services.extract_worksheet_pages(self._fake_doc(captured))
        self.assertEqual(captured['dpi'], services.SCREENSHOT_DPI)

    def test_override_dpi(self):
        captured = {}
        services.extract_worksheet_pages(self._fake_doc(captured), screenshot_dpi=222)
        self.assertEqual(captured['dpi'], 222)


class ClassifyThreadsShapeNamingTests(SimpleTestCase):
    @patch('worksheets.services._get_anthropic_client', return_value=MagicMock())
    @patch('worksheets.services._classify_page_chunk')
    def test_single_chunk_receives_shape_naming(self, mock_chunk, _client):
        mock_chunk.return_value = {'questions': [], 'usage': {}}
        pages = {'page_count': 1, 'pages': [{
            'page_num': 1, 'screenshot': 'b64', 'screenshot_w': 800,
            'screenshot_h': 1100, 'text': 't',
        }]}
        services.classify_worksheet_questions(pages, [], [], shape_naming=True)
        self.assertEqual(mock_chunk.call_args.kwargs['shape_naming'], True)


class ExtractAndClassifyThreadsModeTests(SimpleTestCase):
    # The real pymupdf (fitz) DLL may be unavailable in CI/local; the function does
    # `import fitz` internally, so inject a fake module rather than patch fitz.open.
    def _run(self, **kwargs):
        with patch.dict('sys.modules', {'fitz': MagicMock()}):
            return services.extract_and_classify_worksheet(MagicMock(read=lambda: b'%PDF-1.4'),
                                                           [], [], **kwargs)

    @patch('worksheets.services.render_question_images', return_value=({'questions': []}, {}))
    @patch('worksheets.services.classify_worksheet_questions',
           return_value={'questions': [], 'usage': {'total_tokens': 0}})
    @patch('worksheets.services.extract_worksheet_pages',
           return_value={'pages': [], 'page_count': 1})
    def test_shape_naming_raises_dpi_and_threads_flag(
            self, mock_extract, mock_classify, _render):
        self._run(shape_naming=True)
        self.assertEqual(
            mock_extract.call_args.kwargs['screenshot_dpi'], services.SHAPE_NAMING_DPI)
        self.assertEqual(mock_classify.call_args.kwargs['shape_naming'], True)

    @patch('worksheets.services.render_question_images', return_value=({'questions': []}, {}))
    @patch('worksheets.services.classify_worksheet_questions',
           return_value={'questions': [], 'usage': {'total_tokens': 0}})
    @patch('worksheets.services.extract_worksheet_pages',
           return_value={'pages': [], 'page_count': 1})
    def test_default_mode_keeps_default_dpi(
            self, mock_extract, mock_classify, _render):
        self._run()
        self.assertIsNone(mock_extract.call_args.kwargs['screenshot_dpi'])
        self.assertEqual(mock_classify.call_args.kwargs['shape_naming'], False)


class IncludeDefaultByValidationTypeTests(SimpleTestCase):
    """Teacher-graded (human_graded) questions are deselected by default; all
    other questions are included by default. Shared by the homework and worksheet
    PDF upload previews via extract_and_classify_worksheet."""

    def _run(self, classified_questions):
        with patch.dict('sys.modules', {'fitz': MagicMock()}), \
             patch('worksheets.services.extract_worksheet_pages',
                   return_value={'pages': [], 'page_count': 1}), \
             patch('worksheets.services.classify_worksheet_questions',
                   return_value={'questions': classified_questions,
                                 'usage': {'total_tokens': 0}}), \
             patch('worksheets.services.render_question_images',
                   side_effect=lambda doc, pages, result: (result, {})):
            output = services.extract_and_classify_worksheet(
                MagicMock(read=lambda: b'%PDF-1.4'), [], [])
        return output['result']['questions']

    def test_human_graded_deselected_others_selected(self):
        questions = self._run([
            {'question_text': 'auto q', 'validation_type': 'auto'},
            {'question_text': 'ai q', 'validation_type': 'ai_graded'},
            {'question_text': 'teacher q', 'validation_type': 'human_graded'},
        ])
        by_type = {q['validation_type']: q for q in questions}
        self.assertTrue(by_type['auto']['include'])
        self.assertTrue(by_type['ai_graded']['include'])
        self.assertFalse(by_type['human_graded']['include'])

    def test_missing_validation_type_defaults_included(self):
        questions = self._run([{'question_text': 'no vt'}])
        self.assertTrue(questions[0]['include'])

    def test_explicit_include_is_not_overridden(self):
        # A pre-set include value (e.g. re-processing) wins over the default rule.
        questions = self._run([
            {'question_text': 'opted-in teacher q',
             'validation_type': 'human_graded', 'include': True},
        ])
        self.assertTrue(questions[0]['include'])


class WorksheetSessionModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('ws_sn', 'ws_sn@test.internal', 'pw1!')

    def test_defaults_off(self):
        s = WorksheetUploadSession.objects.create(user=self.user, pdf_filename='a.pdf')
        self.assertFalse(s.shape_naming)

    def test_can_enable(self):
        s = WorksheetUploadSession.objects.create(
            user=self.user, pdf_filename='a.pdf', shape_naming=True)
        s.refresh_from_db()
        self.assertTrue(s.shape_naming)


class WorksheetUploadViewShapeNamingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner_role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER, defaults={'display_name': 'Institute Owner'})
        cls.owner = CustomUser.objects.create_user(
            'ws_v', 'ws_v@test.internal', 'pw1!',
            profile_completed=True, must_change_password=False)
        cls.owner.roles.add(owner_role)
        cls.school = School.objects.create(name='WS V', slug='ws-v', admin=cls.owner)
        SchoolTeacher.objects.get_or_create(school=cls.school, teacher=cls.owner)

    def setUp(self):
        self.client.force_login(self.owner)

    @patch('worksheets.tasks.process_worksheet_pdf')
    @patch('taskqueue.services.django_rq.get_queue')
    def _post(self, data, mock_get_queue, _task):
        mock_job = MagicMock(); mock_job.id = 'j1'
        mock_queue = MagicMock(); mock_queue.enqueue.return_value = mock_job
        mock_get_queue.return_value = mock_queue
        pdf = SimpleUploadedFile('q.pdf', b'%PDF-1.4 x', content_type='application/pdf')
        return self.client.post(reverse('worksheets:upload'), {'pdf_file': pdf, **data})

    def test_checkbox_on_sets_shape_naming(self):
        self._post({'shape_naming': 'on'})
        session = WorksheetUploadSession.objects.get(user=self.owner)
        self.assertTrue(session.shape_naming)

    def test_checkbox_absent_defaults_off(self):
        self._post({})
        session = WorksheetUploadSession.objects.get(user=self.owner)
        self.assertFalse(session.shape_naming)

    def test_upload_page_renders_shape_naming_checkbox(self):
        resp = self.client.get(reverse('worksheets:upload'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="shape_naming"')
