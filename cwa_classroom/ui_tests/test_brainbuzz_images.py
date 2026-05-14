"""
Playwright UI tests for CPP-250: BrainBuzz question + answer image rendering.

Covers:
  - Student play view renders question image when image_url is set
  - Student play view renders no <img> when image_url is empty
  - Student MCQ tiles render option images when opt.image_url is set
  - Teacher in-game view renders question image when present
  - Teacher in-game view renders no <img> when image_url is empty
"""
import json

import pytest
from playwright.sync_api import expect

from .conftest import do_login, TEST_PASSWORD

pytestmark = pytest.mark.brainbuzz_images

# 1x1 transparent GIF — loads from memory, @error never fires
TINY_GIF = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'


# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def bb_teacher(db, roles):
    from accounts.models import CustomUser, Role
    u = CustomUser.objects.create_user(
        username='bb_img_teacher',
        password=TEST_PASSWORD,
        email='bb_img_teacher@test.local',
        profile_completed=True,
        must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(name=Role.TEACHER)
    u.roles.add(role)
    return u


@pytest.fixture
def bb_subject(db):
    from classroom.models import Subject
    return Subject.objects.get_or_create(slug='bb-img-subject', defaults={'name': 'BB Image Subject'})[0]


def _make_active_session(teacher, subject, code='BBIMG1'):
    from django.utils import timezone
    from datetime import timedelta
    from brainbuzz.models import BrainBuzzSession
    session = BrainBuzzSession.objects.create(
        code=code,
        host=teacher,
        subject=subject,
        status=BrainBuzzSession.STATUS_ACTIVE,
        current_index=0,
        state_version=1,
        time_per_question_sec=20,
        question_deadline=timezone.now() + timedelta(seconds=20),
    )
    return session


def _make_question(session, image_url='', options=None):
    from brainbuzz.models import BrainBuzzSessionQuestion, QUESTION_TYPE_MCQ
    if options is None:
        options = [
            {'label': 'A', 'text': 'Alpha', 'is_correct': True,  'image_url': ''},
            {'label': 'B', 'text': 'Beta',  'is_correct': False, 'image_url': ''},
        ]
    return BrainBuzzSessionQuestion.objects.create(
        session=session,
        order=0,
        question_text='What colour is the sky?',
        question_type=QUESTION_TYPE_MCQ,
        options_json=options,
        image_url=image_url,
        time_limit_sec=20,
        source_model='Test',
        source_id=1,
    )


def _make_participant(session, nickname='UITester'):
    from brainbuzz.models import BrainBuzzParticipant
    return BrainBuzzParticipant.objects.create(session=session, nickname=nickname)


def _set_participant_cookie(page, live_server_url, join_code, participant_id):
    """Inject the Django session with the BrainBuzz participant ID."""
    from django.test import Client
    client = Client()
    client.get(f'{live_server_url}/')
    session = client.session
    session[f'bb_pid_{join_code}'] = participant_id
    session.save()
    session_key = session.session_key

    page.goto(live_server_url)
    page.evaluate(f"""() => {{
        document.cookie = 'sessionid={session_key}; path=/';
    }}""")


# ---------------------------------------------------------------------------
# Student view: question image
# ---------------------------------------------------------------------------

class TestStudentQuestionImage:

    @pytest.fixture(autouse=True)
    def _setup(self, db, live_server, page, bb_teacher, bb_subject):
        self.url = live_server.url
        self.page = page
        self.teacher = bb_teacher
        self.subject = bb_subject

    def test_question_image_renders_when_url_set(self):
        session = _make_active_session(self.teacher, self.subject, code='IMGQ01')
        _make_question(session, image_url=TINY_GIF)
        participant = _make_participant(session)
        _set_participant_cookie(self.page, self.url, 'IMGQ01', participant.id)

        self.page.goto(f'{self.url}/brainbuzz/play/IMGQ01/')
        self.page.wait_for_load_state('domcontentloaded')

        # Wait for the question image Alpine renders via x-if (alt text set in template)
        self.page.wait_for_selector('img[alt="Question image"]', timeout=5000)

        img = self.page.locator('img[alt="Question image"]')
        expect(img).to_have_count(1)

    def test_no_img_tag_when_question_has_no_image(self):
        session = _make_active_session(self.teacher, self.subject, code='IMGQ02')
        _make_question(session, image_url='')
        participant = _make_participant(session)
        _set_participant_cookie(self.page, self.url, 'IMGQ02', participant.id)

        self.page.goto(f'{self.url}/brainbuzz/play/IMGQ02/')
        self.page.wait_for_load_state('domcontentloaded')

        # Wait for Alpine to render the question text (proves x-if has run)
        self.page.wait_for_selector('.bb-question-body', timeout=5000)

        # No orphan broken-image icons — question area img must not exist
        question_imgs = self.page.locator(
            '.bb-question-body img, [x-text*="question_text"] ~ img'
        )
        expect(question_imgs).to_have_count(0)


# ---------------------------------------------------------------------------
# Student view: option images in MCQ tiles
# ---------------------------------------------------------------------------

class TestStudentOptionImage:

    @pytest.fixture(autouse=True)
    def _setup(self, db, live_server, page, bb_teacher, bb_subject):
        self.url = live_server.url
        self.page = page
        self.teacher = bb_teacher
        self.subject = bb_subject

    def test_option_image_renders_in_tile(self):
        opts = [
            {'label': 'A', 'text': '',     'is_correct': True,  'image_url': TINY_GIF},
            {'label': 'B', 'text': 'Beta', 'is_correct': False, 'image_url': ''},
        ]
        session = _make_active_session(self.teacher, self.subject, code='IMGO01')
        _make_question(session, options=opts)
        participant = _make_participant(session)
        _set_participant_cookie(self.page, self.url, 'IMGO01', participant.id)

        self.page.goto(f'{self.url}/brainbuzz/play/IMGO01/')
        self.page.wait_for_load_state('domcontentloaded')

        # MCQ tiles only show when readWindow=false; deadline=now+20, timeLimitSec=20
        # so readWindowEnds = deadline - 20s = now → readWindow is immediately false
        self.page.wait_for_selector('.grid button img', timeout=5000)

        opt_img = self.page.locator('.grid button img')
        expect(opt_img).to_have_count(1)

    def test_no_option_img_when_image_url_empty(self):
        opts = [
            {'label': 'A', 'text': 'Alpha', 'is_correct': True,  'image_url': ''},
            {'label': 'B', 'text': 'Beta',  'is_correct': False, 'image_url': ''},
        ]
        session = _make_active_session(self.teacher, self.subject, code='IMGO02')
        _make_question(session, options=opts)
        participant = _make_participant(session)
        _set_participant_cookie(self.page, self.url, 'IMGO02', participant.id)

        self.page.goto(f'{self.url}/brainbuzz/play/IMGO02/')
        self.page.wait_for_load_state('domcontentloaded')

        # Wait for MCQ tiles to render (proves Alpine x-for has run)
        self.page.wait_for_selector('.grid button', timeout=5000)

        # No option images should be rendered
        opt_imgs = self.page.locator('.grid button img')
        expect(opt_imgs).to_have_count(0)


# ---------------------------------------------------------------------------
# Teacher in-game view: question image
# ---------------------------------------------------------------------------

class TestTeacherQuestionImage:

    @pytest.fixture(autouse=True)
    def _setup(self, db, live_server, page, bb_teacher, bb_subject):
        self.url = live_server.url
        self.page = page
        self.teacher = bb_teacher
        self.subject = bb_subject
        do_login(page, live_server.url, bb_teacher)

    def test_teacher_question_image_renders_when_url_set(self):
        session = _make_active_session(self.teacher, self.subject, code='IMGT01')
        _make_question(session, image_url=TINY_GIF)

        self.page.goto(f'{self.url}/brainbuzz/session/IMGT01/play/')
        self.page.wait_for_load_state('domcontentloaded')

        # Wait for question image (alt text added in template for accessibility)
        self.page.wait_for_selector('img[alt="Question image"]', timeout=5000)

        img = self.page.locator('img[alt="Question image"]')
        expect(img).to_have_count(1)

    def test_teacher_no_img_when_question_has_no_image(self):
        session = _make_active_session(self.teacher, self.subject, code='IMGT02')
        _make_question(session, image_url='')

        self.page.goto(f'{self.url}/brainbuzz/session/IMGT02/play/')
        self.page.wait_for_load_state('domcontentloaded')

        # Wait for Alpine to render the question text (proves x-if has run)
        self.page.wait_for_selector('.bb-question-body', timeout=5000)

        # The question card should have no <img> inside it
        question_card_imgs = self.page.locator(
            'main .rounded-3xl img'
        )
        expect(question_card_imgs).to_have_count(0)

    def test_teacher_option_image_renders_in_active_tile(self):
        opts = [
            {'label': 'A', 'text': '',     'is_correct': True,  'image_url': TINY_GIF},
            {'label': 'B', 'text': 'Beta', 'is_correct': False, 'image_url': ''},
        ]
        session = _make_active_session(self.teacher, self.subject, code='IMGT03')
        _make_question(session, options=opts)

        self.page.goto(f'{self.url}/brainbuzz/session/IMGT03/play/')
        self.page.wait_for_load_state('domcontentloaded')

        # data: URI loads inline — @error never fires, image stays visible
        self.page.wait_for_selector('img[src^="data:image"]', timeout=5000)

        img = self.page.locator('img[src^="data:image"]')
        expect(img).to_have_count(1)
