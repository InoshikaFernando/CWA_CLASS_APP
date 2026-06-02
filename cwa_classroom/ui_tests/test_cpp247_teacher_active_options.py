"""
test_cpp247_teacher_active_options.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Playwright UI tests for CPP-247: Show answer options to teacher in active phase.

Coverage:
  - MCQ answer tiles visible during ACTIVE (not just REVEAL)
  - Correct option tile has emerald border; wrong tiles do not
  - Tiles are read-only (pointer-events-none — clicking does not submit)
  - SA/FB: "Expected Answer" block visible with the correct answer text
  - SA/FB: "Expected Answer" block NOT shown for MCQ questions
  - Read window hides tiles; tiles appear once answer phase begins
  - Tiles appear after read window expires
  - REVEAL distribution chart still renders (regression)
  - Student does NOT see correct-answer markers during ACTIVE (security)
"""
import re
from datetime import timedelta

import pytest
from playwright.sync_api import expect

from .conftest import do_login, TEST_PASSWORD

pytestmark = pytest.mark.cpp247


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_teacher(username):
    from accounts.models import CustomUser, Role
    u = CustomUser.objects.create_user(
        username=username,
        password=TEST_PASSWORD,
        email=f'{username}@test.local',
        profile_completed=True,
        must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(name=Role.TEACHER)
    u.roles.add(role)
    return u


def _make_subject():
    from classroom.models import Subject
    return Subject.objects.get_or_create(slug='bb-247-subj', defaults={'name': 'BB 247 Subj'})[0]


def _make_active_session(teacher, subject, code, time_per_question_sec=30):
    """ACTIVE session with no read window (deadline far enough away that tiles show immediately)."""
    from django.utils import timezone
    from brainbuzz.models import BrainBuzzSession
    # deadline = now + time_per_question_sec
    # readWindowEnds = deadline - time_per_question_sec = now  → no read window
    return BrainBuzzSession.objects.create(
        code=code,
        host=teacher,
        subject=subject,
        status=BrainBuzzSession.STATUS_ACTIVE,
        current_index=0,
        state_version=1,
        time_per_question_sec=time_per_question_sec,
        question_deadline=timezone.now() + timedelta(seconds=time_per_question_sec),
    )


def _make_read_window_session(teacher, subject, code, time_per_question_sec=30):
    """ACTIVE session still inside the read window (answer tiles hidden)."""
    from django.utils import timezone
    from brainbuzz.models import BrainBuzzSession
    # deadline = now + time_per_question_sec * 2
    # readWindowEnds = deadline - time_per_question_sec = now + time_per_question_sec → still in future
    return BrainBuzzSession.objects.create(
        code=code,
        host=teacher,
        subject=subject,
        status=BrainBuzzSession.STATUS_ACTIVE,
        current_index=0,
        state_version=1,
        time_per_question_sec=time_per_question_sec,
        question_deadline=timezone.now() + timedelta(seconds=time_per_question_sec * 2),
    )


def _make_reveal_session(teacher, subject, code):
    from brainbuzz.models import BrainBuzzSession
    return BrainBuzzSession.objects.create(
        code=code,
        host=teacher,
        subject=subject,
        status=BrainBuzzSession.STATUS_REVEAL,
        current_index=0,
        state_version=2,
        time_per_question_sec=20,
        question_deadline=None,
    )


def _make_mcq_question(session, order=0, correct_label='B'):
    from brainbuzz.models import BrainBuzzSessionQuestion, QUESTION_TYPE_MCQ
    return BrainBuzzSessionQuestion.objects.create(
        session=session,
        order=order,
        question_text='What is the capital of France?',
        question_type=QUESTION_TYPE_MCQ,
        options_json=[
            {'label': 'A', 'text': 'Berlin',  'is_correct': correct_label == 'A', 'image_url': ''},
            {'label': 'B', 'text': 'Paris',   'is_correct': correct_label == 'B', 'image_url': ''},
            {'label': 'C', 'text': 'Rome',    'is_correct': correct_label == 'C', 'image_url': ''},
            {'label': 'D', 'text': 'Madrid',  'is_correct': correct_label == 'D', 'image_url': ''},
        ],
        time_limit_sec=session.time_per_question_sec,
        points_base=1000,
        source_model='Test',
        source_id=order,
    )


def _make_sa_question(session, order=0, correct_answer='photosynthesis'):
    from brainbuzz.models import BrainBuzzSessionQuestion, QUESTION_TYPE_SHORT_ANSWER
    return BrainBuzzSessionQuestion.objects.create(
        session=session,
        order=order,
        question_text='What process do plants use to make food?',
        question_type=QUESTION_TYPE_SHORT_ANSWER,
        options_json=[],
        correct_short_answer=correct_answer,
        time_limit_sec=session.time_per_question_sec,
        points_base=1000,
        source_model='Test',
        source_id=order,
    )


def _make_participant(session, nickname='UIStudent'):
    from brainbuzz.models import BrainBuzzParticipant
    return BrainBuzzParticipant.objects.create(session=session, nickname=nickname)


def _set_participant_cookie(page, live_server_url, join_code, participant_id):
    """Inject a participant session cookie so the student page loads correctly."""
    from django.test import Client as DjangoClient
    client = DjangoClient()
    client.get(f'{live_server_url}/')
    django_session = client.session
    django_session[f'bb_pid_{join_code}'] = participant_id
    django_session.save()
    session_key = django_session.session_key
    page.goto(live_server_url)
    page.evaluate(f"() => {{ document.cookie = 'sessionid={session_key}; path=/'; }}")


def _ingame_url(live_server_url, code):
    from django.urls import reverse
    return f'{live_server_url}{reverse("brainbuzz:teacher_ingame", kwargs={"join_code": code})}'


def _student_url(live_server_url, code):
    from django.urls import reverse
    return f'{live_server_url}{reverse("brainbuzz:student_play", kwargs={"join_code": code})}'


# ---------------------------------------------------------------------------
# UI1: MCQ tiles visible during ACTIVE
# ---------------------------------------------------------------------------

class TestMcqTilesVisibleDuringActive:

    @pytest.fixture(autouse=True)
    def _setup(self, db, live_server, page):
        self.url = live_server.url
        self.page = page
        self.teacher = _make_teacher('bb247_mcq_t')
        self.subject = _make_subject()

    def test_mcq_tiles_visible_during_active(self):
        session = _make_active_session(self.teacher, self.subject, 'C247A1')
        _make_mcq_question(session, correct_label='B')

        do_login(self.page, self.url, self.teacher.username, TEST_PASSWORD)
        self.page.goto(_ingame_url(self.url, 'C247A1'))
        self.page.wait_for_load_state('domcontentloaded')

        # All 4 option tiles should be visible
        for label in ['A', 'B', 'C', 'D']:
            tile_text = self.page.get_by_text({'A': 'Berlin', 'B': 'Paris', 'C': 'Rome', 'D': 'Madrid'}[label])
            expect(tile_text).to_be_visible(timeout=6_000)


# ---------------------------------------------------------------------------
# UI2: Correct option has emerald border; wrong options do not
# ---------------------------------------------------------------------------

class TestCorrectOptionEmeraldBorder:

    @pytest.fixture(autouse=True)
    def _setup(self, db, live_server, page):
        self.url = live_server.url
        self.page = page
        self.teacher = _make_teacher('bb247_emr_t')
        self.subject = _make_subject()

    def test_correct_option_has_emerald_border(self):
        session = _make_active_session(self.teacher, self.subject, 'C247B1')
        _make_mcq_question(session, correct_label='B')  # B = Paris is correct

        do_login(self.page, self.url, self.teacher.username, TEST_PASSWORD)
        self.page.goto(_ingame_url(self.url, 'C247B1'))
        self.page.wait_for_load_state('domcontentloaded')
        self.page.wait_for_timeout(1_500)  # let Alpine render

        # The tile row containing "Paris" should have the emerald border class
        paris_tile = self.page.locator('div', has_text='Paris').filter(
            has=self.page.locator('span', has_text='B')
        ).first
        expect(paris_tile).to_have_class(re.compile(r'border-emerald-400'), timeout=5_000)

    def test_incorrect_options_do_not_have_emerald_border(self):
        session = _make_active_session(self.teacher, self.subject, 'C247B2')
        _make_mcq_question(session, correct_label='B')  # B is correct; A/C/D are wrong

        do_login(self.page, self.url, self.teacher.username, TEST_PASSWORD)
        self.page.goto(_ingame_url(self.url, 'C247B2'))
        self.page.wait_for_load_state('domcontentloaded')
        self.page.wait_for_timeout(1_500)

        # Berlin tile (A) should NOT have emerald border
        berlin_tile = self.page.locator('div', has_text='Berlin').filter(
            has=self.page.locator('span', has_text='A')
        ).first
        class_attr = berlin_tile.get_attribute('class') or ''
        assert 'border-emerald-400' not in class_attr


# ---------------------------------------------------------------------------
# UI3: Tiles are read-only (no answer submission on click)
# ---------------------------------------------------------------------------

class TestTilesReadOnly:

    @pytest.fixture(autouse=True)
    def _setup(self, db, live_server, page):
        self.url = live_server.url
        self.page = page
        self.teacher = _make_teacher('bb247_ro_t')
        self.subject = _make_subject()

    def test_tiles_are_pointer_events_none(self):
        """Teacher tiles must carry pointer-events-none so they cannot be clicked."""
        session = _make_active_session(self.teacher, self.subject, 'C247C1')
        _make_mcq_question(session, correct_label='A')

        do_login(self.page, self.url, self.teacher.username, TEST_PASSWORD)
        self.page.goto(_ingame_url(self.url, 'C247C1'))
        self.page.wait_for_load_state('domcontentloaded')
        self.page.wait_for_timeout(1_500)

        # Verify pointer-events-none is present on the tile grid items
        tile = self.page.locator('div.pointer-events-none').first
        expect(tile).to_be_visible(timeout=5_000)


# ---------------------------------------------------------------------------
# UI4: SA expected-answer block visible for SA question
# ---------------------------------------------------------------------------

class TestSaExpectedAnswerVisible:

    @pytest.fixture(autouse=True)
    def _setup(self, db, live_server, page):
        self.url = live_server.url
        self.page = page
        self.teacher = _make_teacher('bb247_sa_t')
        self.subject = _make_subject()

    def test_sa_expected_answer_block_visible(self):
        session = _make_active_session(self.teacher, self.subject, 'C247D1')
        _make_sa_question(session, correct_answer='photosynthesis')

        do_login(self.page, self.url, self.teacher.username, TEST_PASSWORD)
        self.page.goto(_ingame_url(self.url, 'C247D1'))
        self.page.wait_for_load_state('domcontentloaded')
        self.page.wait_for_timeout(1_500)

        expect(self.page.get_by_text('Expected Answer', exact=False)).to_be_visible(timeout=6_000)
        expect(self.page.get_by_text('photosynthesis', exact=False)).to_be_visible(timeout=6_000)

    def test_sa_expected_answer_not_shown_for_mcq(self):
        """MCQ question must NOT show the "Expected Answer" heading."""
        session = _make_active_session(self.teacher, self.subject, 'C247D2')
        _make_mcq_question(session, correct_label='C')

        do_login(self.page, self.url, self.teacher.username, TEST_PASSWORD)
        self.page.goto(_ingame_url(self.url, 'C247D2'))
        self.page.wait_for_load_state('domcontentloaded')
        self.page.wait_for_timeout(1_500)

        expect(self.page.get_by_text('Expected Answer', exact=False)).not_to_be_visible(timeout=4_000)


# ---------------------------------------------------------------------------
# UI5: Read window hides tiles; tiles appear after window expires
# ---------------------------------------------------------------------------

class TestReadWindowHidesTiles:

    @pytest.fixture(autouse=True)
    def _setup(self, db, live_server, page):
        self.url = live_server.url
        self.page = page
        self.teacher = _make_teacher('bb247_rw_t')
        self.subject = _make_subject()

    def test_read_window_hides_tiles(self):
        """During read window, option tiles must not be visible."""
        # time_per_question_sec=5; deadline = now + 10s → readWindowEnds = now+5s (still future)
        session = _make_read_window_session(self.teacher, self.subject, 'C247E1', time_per_question_sec=5)
        _make_mcq_question(session, correct_label='A')

        do_login(self.page, self.url, self.teacher.username, TEST_PASSWORD)
        self.page.goto(_ingame_url(self.url, 'C247E1'))
        self.page.wait_for_load_state('domcontentloaded')
        self.page.wait_for_timeout(800)

        # Read window placeholder must be visible
        expect(self.page.get_by_text('Read window', exact=False)).to_be_visible(timeout=4_000)
        # Option tiles must NOT be visible
        expect(self.page.get_by_text('Berlin', exact=False)).not_to_be_visible(timeout=3_000)

    def test_tiles_appear_after_read_window(self):
        """Tiles become visible once the read window countdown reaches zero."""
        # time_per_question_sec=3; deadline = now + 3s → readWindowEnds = now (no read window)
        # Use a very short timer so tiles appear quickly
        from django.utils import timezone
        from brainbuzz.models import BrainBuzzSession
        session = BrainBuzzSession.objects.create(
            code='C247E2',
            host=self.teacher,
            subject=self.subject,
            status=BrainBuzzSession.STATUS_ACTIVE,
            current_index=0,
            state_version=1,
            time_per_question_sec=3,
            # deadline = now+6s; readWindowEnds = now+3s → 3s read window then tiles
            question_deadline=timezone.now() + timedelta(seconds=6),
        )
        _make_mcq_question(session, correct_label='A')

        do_login(self.page, self.url, self.teacher.username, TEST_PASSWORD)
        self.page.goto(_ingame_url(self.url, 'C247E2'))
        self.page.wait_for_load_state('domcontentloaded')

        # Read window placeholder visible initially
        expect(self.page.get_by_text('Read window', exact=False)).to_be_visible(timeout=4_000)

        # After ~4s the read window ends and tiles should appear
        expect(self.page.get_by_text('Berlin', exact=False)).to_be_visible(timeout=10_000)


# ---------------------------------------------------------------------------
# UI6: REVEAL distribution chart still renders (regression)
# ---------------------------------------------------------------------------

class TestRevealDistributionRegression:

    @pytest.fixture(autouse=True)
    def _setup(self, db, live_server, page):
        self.url = live_server.url
        self.page = page
        self.teacher = _make_teacher('bb247_rev_t')
        self.subject = _make_subject()

    def test_reveal_distribution_still_works(self):
        """REVEAL phase distribution chart renders with correct-answer checkmark."""
        from brainbuzz.models import BrainBuzzParticipant, BrainBuzzAnswer
        session = _make_reveal_session(self.teacher, self.subject, 'C247F1')
        q = _make_mcq_question(session, correct_label='B')
        p = BrainBuzzParticipant.objects.create(session=session, nickname='Tester')
        BrainBuzzAnswer.objects.create(
            participant=p,
            session_question=q,
            selected_option_label='B',
            is_correct=True,
            points_awarded=1000,
            time_taken_ms=500,
        )

        do_login(self.page, self.url, self.teacher.username, TEST_PASSWORD)
        self.page.goto(_ingame_url(self.url, 'C247F1'))
        self.page.wait_for_load_state('domcontentloaded')
        self.page.wait_for_timeout(1_500)

        # Paris tile (correct) should be visible in distribution
        expect(self.page.get_by_text('Paris', exact=False)).to_be_visible(timeout=6_000)
        # The checkmark for correct answer
        expect(self.page.get_by_text('✓')).to_be_visible(timeout=4_000)


# ---------------------------------------------------------------------------
# UI7: Student does NOT see correct-answer markers during ACTIVE (security)
# ---------------------------------------------------------------------------

class TestStudentNoCorrectMarkerDuringActive:

    @pytest.fixture(autouse=True)
    def _setup(self, db, live_server, page):
        self.url = live_server.url
        self.page = page
        self.teacher = _make_teacher('bb247_sec_t')
        self.subject = _make_subject()

    def test_student_does_not_see_correct_marker_during_active(self):
        """Student tile for the wrong option must NOT have the emerald border class."""
        session = _make_active_session(self.teacher, self.subject, 'C247G1')
        _make_mcq_question(session, correct_label='B')
        participant = _make_participant(session)

        _set_participant_cookie(self.page, self.url, 'C247G1', participant.id)
        self.page.goto(_student_url(self.url, 'C247G1'))
        self.page.wait_for_load_state('domcontentloaded')
        self.page.wait_for_timeout(1_500)

        # Student tiles should render but none should have emerald border
        tile_divs = self.page.locator('[class*="border-emerald-400"]')
        expect(tile_divs).to_have_count(0, timeout=5_000)

    def test_student_state_api_omits_is_correct_during_active(self):
        """The /state/ API must strip is_correct from options for non-host clients."""
        import json as _json
        from django.test import Client as DjangoClient
        from django.urls import reverse

        session = _make_active_session(self.teacher, self.subject, 'C247G2')
        _make_mcq_question(session, correct_label='C')

        # Unauthenticated (student-perspective) request
        client = DjangoClient()
        url = reverse('brainbuzz:api_session_state', kwargs={'join_code': 'C247G2'})
        resp = client.get(url)
        data = _json.loads(resp.content)
        for opt in data.get('question', {}).get('options', []):
            assert 'is_correct' not in opt, f"is_correct must not be exposed to students: {opt}"
