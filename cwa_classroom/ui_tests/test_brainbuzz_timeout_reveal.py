"""
test_brainbuzz_timeout_reveal.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Playwright UI tests for CPP-267: correct answer visible on timeout,
teacher controls pace (no auto-advance).

Coverage:
  - Student sees "Waiting for teacher to reveal the answer…" banner for ≥2s
    after the question countdown expires
  - Student stays on REVEAL for 8s with no auto-navigation (old auto was 5s)
  - Teacher REVEAL header shows "Results" badge, prominent Next button
  - Teacher Next → button advances session to next question
  - Student REVEAL view shows correct answer highlighted in green
  - Student REVEAL footer shows "Waiting for teacher to continue…" (not "Next in Xs…")
"""
from datetime import timedelta

import pytest
from playwright.sync_api import expect

from .conftest import do_login, TEST_PASSWORD

pytestmark = pytest.mark.brainbuzz_timeout_reveal


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
    return Subject.objects.get_or_create(slug='bb-tr-subj', defaults={'name': 'BB TR Subj'})[0]


def _make_session(teacher, subject, status, code, current_index=0):
    from django.utils import timezone
    from brainbuzz.models import BrainBuzzSession
    return BrainBuzzSession.objects.create(
        code=code,
        host=teacher,
        subject=subject,
        status=status,
        current_index=current_index,
        state_version=1,
        time_per_question_sec=20,
        question_deadline=(
            timezone.now() + timedelta(seconds=60)
            if status == BrainBuzzSession.STATUS_ACTIVE else None
        ),
    )


def _make_active_short_timer(teacher, subject, code, timer_sec=4):
    """ACTIVE session whose deadline expires in `timer_sec` seconds.

    Sets time_limit_sec equal to timer_sec so readWindowEnds = deadline - timer_sec = now,
    meaning the answer tiles are immediately visible (no read window delay).
    """
    from django.utils import timezone
    from brainbuzz.models import BrainBuzzSession
    return BrainBuzzSession.objects.create(
        code=code,
        host=teacher,
        subject=subject,
        status=BrainBuzzSession.STATUS_ACTIVE,
        current_index=0,
        state_version=1,
        time_per_question_sec=timer_sec,
        question_deadline=timezone.now() + timedelta(seconds=timer_sec),
    )


def _make_mcq_question(session, order=0, correct_label='A', time_limit_sec=20, text=None):
    from brainbuzz.models import BrainBuzzSessionQuestion, QUESTION_TYPE_MCQ
    return BrainBuzzSessionQuestion.objects.create(
        session=session,
        order=order,
        question_text=text or f'UI Test Question {order + 1}',
        question_type=QUESTION_TYPE_MCQ,
        options_json=[
            {'label': 'A', 'text': 'Alpha', 'is_correct': correct_label == 'A', 'image_url': ''},
            {'label': 'B', 'text': 'Beta',  'is_correct': correct_label == 'B', 'image_url': ''},
            {'label': 'C', 'text': 'Gamma', 'is_correct': correct_label == 'C', 'image_url': ''},
        ],
        time_limit_sec=time_limit_sec,
        points_base=1000,
        source_model='Test',
        source_id=order,
    )


def _make_participant(session, nickname='UITester'):
    from brainbuzz.models import BrainBuzzParticipant
    return BrainBuzzParticipant.objects.create(session=session, nickname=nickname)


def _set_participant_cookie(page, live_server_url, join_code, participant_id):
    """Inject the participant ID into a Django session so the student page loads correctly."""
    from django.test import Client
    client = Client()
    client.get(f'{live_server_url}/')
    django_session = client.session
    django_session[f'bb_pid_{join_code}'] = participant_id
    django_session.save()
    session_key = django_session.session_key
    page.goto(live_server_url)
    page.evaluate(f"() => {{ document.cookie = 'sessionid={session_key}; path=/'; }}")


# ---------------------------------------------------------------------------
# Student: "waiting" banner appears after countdown expires
# ---------------------------------------------------------------------------

class TestStudentWaitingBanner:

    @pytest.fixture(autouse=True)
    def _setup(self, db, live_server, page):
        self.url = live_server.url
        self.page = page
        self.teacher = _make_teacher('bb_tr_wait_t')
        self.subject = _make_subject()

    def test_waiting_banner_appears_after_countdown(self):
        """After the question timer expires, the student sees the 'waiting' banner
        and it stays visible for the full 2-second hold period."""
        # Session expires in 4s; time_limit_sec=4 → no read window
        session = _make_active_short_timer(
            self.teacher, self.subject, 'TRWT01', timer_sec=4
        )
        _make_mcq_question(session, time_limit_sec=4)
        participant = _make_participant(session)
        _set_participant_cookie(self.page, self.url, 'TRWT01', participant.id)

        self.page.goto(f'{self.url}/brainbuzz/play/TRWT01/')
        self.page.wait_for_load_state('domcontentloaded')

        # Banner appears ~4s after load; wait up to 12s (4s timer + 2s hold + buffer)
        banner = self.page.get_by_text('Waiting for teacher to reveal the answer', exact=False)
        banner.wait_for(timeout=12_000)
        expect(banner).to_be_visible()


# ---------------------------------------------------------------------------
# Student: no auto-advance from REVEAL
# ---------------------------------------------------------------------------

class TestStudentNoAutoAdvance:

    @pytest.fixture(autouse=True)
    def _setup(self, db, live_server, page):
        self.url = live_server.url
        self.page = page
        self.teacher = _make_teacher('bb_tr_noadv_t')
        self.subject = _make_subject()

    def test_student_stays_in_reveal_no_auto_advance(self):
        """Student polls for 8s from REVEAL — session never auto-advances."""
        from brainbuzz.models import BrainBuzzSession
        session = _make_session(
            self.teacher, self.subject, BrainBuzzSession.STATUS_REVEAL, 'TRNA01'
        )
        _make_mcq_question(session, order=0)
        _make_mcq_question(session, order=1)
        participant = _make_participant(session)
        _set_participant_cookie(self.page, self.url, 'TRNA01', participant.id)

        self.page.goto(f'{self.url}/brainbuzz/play/TRNA01/')
        self.page.wait_for_load_state('domcontentloaded')

        # Wait for REVEAL state to be visible (footer always shown in reveal)
        self.page.wait_for_selector('text=Waiting for teacher to continue', timeout=5_000)

        # Wait 8s — old auto-advance triggered at 5s; this proves it's gone
        self.page.wait_for_timeout(8_000)

        # Must NOT have advanced to finish screen
        expect(self.page.get_by_text('Play Again', exact=False)).to_have_count(0)

        # DB confirms session unmoved
        session.refresh_from_db()
        assert session.status == BrainBuzzSession.STATUS_REVEAL
        assert session.current_index == 0


# ---------------------------------------------------------------------------
# Teacher: REVEAL header and Next button
# ---------------------------------------------------------------------------

class TestTeacherRevealUI:

    @pytest.fixture(autouse=True)
    def _setup(self, db, live_server, page):
        self.url = live_server.url
        self.page = page
        self.teacher = _make_teacher('bb_tr_tchr_t')
        self.subject = _make_subject()
        do_login(page, live_server.url, self.teacher)

    def test_results_badge_visible_in_reveal(self):
        """Teacher REVEAL header shows a 'Results' badge."""
        from brainbuzz.models import BrainBuzzSession
        session = _make_session(
            self.teacher, self.subject, BrainBuzzSession.STATUS_REVEAL, 'TRUI01'
        )
        _make_mcq_question(session)

        self.page.goto(f'{self.url}/brainbuzz/session/TRUI01/play/')
        self.page.wait_for_load_state('domcontentloaded')

        self.page.wait_for_selector('text=Results', timeout=5_000)
        expect(self.page.get_by_text('Results', exact=True)).to_be_visible()

    def test_next_button_visible_in_reveal(self):
        """Teacher REVEAL header shows the prominent 'Next →' button."""
        from brainbuzz.models import BrainBuzzSession
        session = _make_session(
            self.teacher, self.subject, BrainBuzzSession.STATUS_REVEAL, 'TRUI02'
        )
        _make_mcq_question(session)

        self.page.goto(f'{self.url}/brainbuzz/session/TRUI02/play/')
        self.page.wait_for_load_state('domcontentloaded')

        next_btn = self.page.locator('button:has-text("Next")')
        next_btn.wait_for(timeout=5_000)
        expect(next_btn).to_be_visible()

    def test_no_auto_next_countdown_in_teacher_reveal(self):
        """Teacher REVEAL must NOT show any auto-advance countdown text."""
        from brainbuzz.models import BrainBuzzSession
        session = _make_session(
            self.teacher, self.subject, BrainBuzzSession.STATUS_REVEAL, 'TRUI03'
        )
        _make_mcq_question(session)

        self.page.goto(f'{self.url}/brainbuzz/session/TRUI03/play/')
        self.page.wait_for_load_state('domcontentloaded')
        self.page.wait_for_selector('text=Results', timeout=5_000)

        # Wait 6s — old auto-next fired at 5s, so any countdown text would be gone by now
        self.page.wait_for_timeout(6_000)
        expect(self.page.get_by_text('Auto-next', exact=False)).to_have_count(0)

    def test_teacher_next_advances_to_next_question(self):
        """Clicking Next → from REVEAL advances the session to Q2 (ACTIVE status)."""
        from brainbuzz.models import BrainBuzzSession
        session = _make_session(
            self.teacher, self.subject, BrainBuzzSession.STATUS_REVEAL, 'TRUI04'
        )
        _make_mcq_question(session, order=0, text='Question One')
        _make_mcq_question(session, order=1, text='Question Two')

        self.page.goto(f'{self.url}/brainbuzz/session/TRUI04/play/')
        self.page.wait_for_load_state('domcontentloaded')

        next_btn = self.page.locator('button:has-text("Next")')
        next_btn.wait_for(timeout=5_000)
        next_btn.click()

        # "Results" badge is REVEAL-only; its disappearance proves ACTIVE transition
        # (teacher page also shows a Next button in ACTIVE, so waiting for that to
        # detach would never succeed — "Results" is the reliable sentinel)
        self.page.get_by_text('Results', exact=True).wait_for(state='hidden', timeout=8_000)

        # DB confirms advancement
        session.refresh_from_db()
        assert session.current_index == 1
        assert session.status == BrainBuzzSession.STATUS_ACTIVE


# ---------------------------------------------------------------------------
# Student: correct answer visible in REVEAL, footer text correct
# ---------------------------------------------------------------------------

class TestStudentRevealUI:

    @pytest.fixture(autouse=True)
    def _setup(self, db, live_server, page):
        self.url = live_server.url
        self.page = page
        self.teacher = _make_teacher('bb_tr_strev_t')
        self.subject = _make_subject()

    def test_correct_answer_highlighted_in_reveal(self):
        """Student REVEAL shows MCQ tiles: correct option (B/Beta) green, others dimmed."""
        from brainbuzz.models import BrainBuzzSession
        session = _make_session(
            self.teacher, self.subject, BrainBuzzSession.STATUS_REVEAL, 'TRSV01'
        )
        _make_mcq_question(session, correct_label='B')
        participant = _make_participant(session)
        _set_participant_cookie(self.page, self.url, 'TRSV01', participant.id)

        self.page.goto(f'{self.url}/brainbuzz/play/TRSV01/')
        self.page.wait_for_load_state('domcontentloaded')

        # Wait for REVEAL tiles grid to render
        self.page.wait_for_selector('.grid', timeout=5_000)

        # The correct option tile (Beta) must have green styling
        correct_tile = self.page.locator('.grid > div:has-text("Beta")')
        expect(correct_tile).to_be_visible()
        # Green border applied via Alpine :class binding
        tile_class = correct_tile.get_attribute('class')
        assert 'border-green-400' in (tile_class or ''), \
            f"Expected green border on correct tile, got classes: {tile_class}"

        # Wrong tiles must be dimmed (opacity-40)
        alpha_tile = self.page.locator('.grid > div:has-text("Alpha")')
        alpha_class = alpha_tile.get_attribute('class')
        assert 'opacity-40' in (alpha_class or ''), \
            f"Expected opacity-40 on wrong tile, got: {alpha_class}"

    def test_correct_short_answer_visible_in_reveal(self):
        """Student REVEAL shows correct_short_answer for short-answer questions."""
        from brainbuzz.models import BrainBuzzSession, BrainBuzzSessionQuestion, QUESTION_TYPE_SHORT_ANSWER
        session = _make_session(
            self.teacher, self.subject, BrainBuzzSession.STATUS_REVEAL, 'TRSV03'
        )
        BrainBuzzSessionQuestion.objects.create(
            session=session, order=0,
            question_text='What is 2+2?',
            question_type=QUESTION_TYPE_SHORT_ANSWER,
            options_json=[],
            correct_short_answer='4',
            time_limit_sec=20, points_base=1000,
            source_model='Test', source_id=0,
        )
        participant = _make_participant(session, nickname='ShortTester')
        _set_participant_cookie(self.page, self.url, 'TRSV03', participant.id)

        self.page.goto(f'{self.url}/brainbuzz/play/TRSV03/')
        self.page.wait_for_load_state('domcontentloaded')

        # "Correct Answer" panel with answer "4" must appear
        self.page.wait_for_selector('text=Correct Answer', timeout=5_000)
        expect(self.page.get_by_text('Correct Answer', exact=True)).to_be_visible()
        expect(self.page.get_by_text('4', exact=True)).to_be_visible()

    def test_correct_short_answer_hidden_in_active(self):
        """Student ACTIVE view does NOT reveal correct_short_answer."""
        # Use _make_active_short_timer so time_per_question_sec == deadline window,
        # eliminating the read window that would hide the short-answer input.
        session = _make_active_short_timer(
            self.teacher, self.subject, 'TRSV04', timer_sec=30
        )
        from brainbuzz.models import BrainBuzzSessionQuestion, QUESTION_TYPE_SHORT_ANSWER
        BrainBuzzSessionQuestion.objects.create(
            session=session, order=0,
            question_text='What is 3+3?',
            question_type=QUESTION_TYPE_SHORT_ANSWER,
            options_json=[],
            correct_short_answer='6',
            time_limit_sec=30, points_base=1000,  # match session timer → no read window
            source_model='Test', source_id=0,
        )
        participant = _make_participant(session, nickname='HiddenTester')
        _set_participant_cookie(self.page, self.url, 'TRSV04', participant.id)

        self.page.goto(f'{self.url}/brainbuzz/play/TRSV04/')
        self.page.wait_for_load_state('domcontentloaded')

        # Wait for page to render (short-answer input should appear)
        self.page.wait_for_selector('input[placeholder="Your answer..."]', timeout=5_000)

        # Correct answer "6" must NOT be visible anywhere on the page
        expect(self.page.get_by_text('6', exact=True)).to_have_count(0)

    def test_student_reveal_footer_shows_waiting_not_countdown(self):
        """Student REVEAL footer shows 'Waiting for teacher to continue…'
        and does NOT show any 'Next in Xs…' countdown."""
        from brainbuzz.models import BrainBuzzSession
        session = _make_session(
            self.teacher, self.subject, BrainBuzzSession.STATUS_REVEAL, 'TRSV02'
        )
        _make_mcq_question(session)
        participant = _make_participant(session)
        _set_participant_cookie(self.page, self.url, 'TRSV02', participant.id)

        self.page.goto(f'{self.url}/brainbuzz/play/TRSV02/')
        self.page.wait_for_load_state('domcontentloaded')

        footer = self.page.get_by_text('Waiting for teacher to continue', exact=False)
        footer.wait_for(timeout=5_000)
        expect(footer).to_be_visible()

        # Old countdown text must not exist
        expect(self.page.get_by_text('Next in', exact=False)).to_have_count(0)
