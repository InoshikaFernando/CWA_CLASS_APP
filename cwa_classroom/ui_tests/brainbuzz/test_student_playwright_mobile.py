"""
test_student_playwright_mobile.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Playwright mobile E2E tests for the BrainBuzz student flow (CPP-237), on an
iPhone 12 mini viewport (375×812):

  - Full lobby → question → lock-in → reveal → results journey
  - Real join through the join screen (code → nickname → lobby)
  - Colorblind-safe tile shapes and colours
  - Countdown pill
  - Haptic feedback on tap
  - Already-answered lock
  - Network error banner and retry/recovery
  - ARIA live regions, tab order, and tiles fitting the viewport

These drive the live server and the real database, like the rest of ui_tests/,
and step the session through its states from the test body — the student page
polls ``/brainbuzz/api/session/<code>/state/``, so a DB change is picked up by
the page within one poll interval.
"""
import re
from datetime import timedelta

import pytest
from playwright.sync_api import expect

from ..conftest import TEST_PASSWORD

pytestmark = pytest.mark.brainbuzz_mobile

# iPhone 12 mini.
MOBILE_VIEWPORT = {"width": 375, "height": 812}
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1"
)

# The student page polls every 400ms (lobby) / 800ms (active) / 1200ms (reveal),
# so anything driven by a DB change needs a few seconds of slack.
POLL_TIMEOUT = 10_000


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mobile_page(browser):
    """A page on a phone-sized, touch-enabled viewport.

    The shared ``page`` fixture is pinned to 1280×800 so the desktop sidebar is
    visible (see ui_tests/conftest.py); the student flow is phone-first, so
    these tests get their own context instead of resizing the shared one.
    """
    context = browser.new_context(
        viewport=dict(MOBILE_VIEWPORT),
        device_scale_factor=3,
        is_mobile=True,
        has_touch=True,
        user_agent=MOBILE_UA,
    )
    page = context.new_page()
    yield page
    context.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_teacher(username):
    from accounts.models import CustomUser, Role
    user = CustomUser.objects.create_user(
        username=username,
        password=TEST_PASSWORD,
        email=f'{username}@test.local',
        profile_completed=True,
        must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(name=Role.TEACHER)
    user.roles.add(role)
    return user


def _make_subject():
    from classroom.models import Subject
    return Subject.objects.get_or_create(
        slug='bb-mobile-subj', defaults={'name': 'BB Mobile Subj'}
    )[0]


def _make_session(teacher, subject, code, status, timer_sec=30, current_index=0):
    """A session in `status`.

    ACTIVE sessions get a deadline `timer_sec` out. Questions are created with
    ``time_limit_sec == timer_sec`` so the read window (deadline - time_limit)
    has already elapsed and the answer tiles render immediately.
    """
    from django.utils import timezone
    from brainbuzz.models import BrainBuzzSession
    return BrainBuzzSession.objects.create(
        code=code,
        host=teacher,
        subject=subject,
        status=status,
        current_index=current_index,
        state_version=1,
        time_per_question_sec=timer_sec,
        question_deadline=(
            timezone.now() + timedelta(seconds=timer_sec)
            if status == BrainBuzzSession.STATUS_ACTIVE else None
        ),
    )


def _make_mcq_question(session, order=0, correct_label='A', time_limit_sec=30,
                       text=None, option_count=4):
    from brainbuzz.models import BrainBuzzSessionQuestion, QUESTION_TYPE_MCQ
    labels = ['A', 'B', 'C', 'D'][:option_count]
    names = ['Alpha', 'Beta', 'Gamma', 'Delta'][:option_count]
    return BrainBuzzSessionQuestion.objects.create(
        session=session,
        order=order,
        question_text=text or f'Mobile Test Question {order + 1}',
        question_type=QUESTION_TYPE_MCQ,
        options_json=[
            {'label': label, 'text': name,
             'is_correct': label == correct_label, 'image_url': ''}
            for label, name in zip(labels, names)
        ],
        time_limit_sec=time_limit_sec,
        points_base=1000,
        source_model='Test',
        source_id=order,
    )


def _make_short_question(session, order=0, answer='4', text='What is 2+2?',
                         time_limit_sec=30):
    from brainbuzz.models import (
        BrainBuzzSessionQuestion, QUESTION_TYPE_SHORT_ANSWER,
    )
    return BrainBuzzSessionQuestion.objects.create(
        session=session,
        order=order,
        question_text=text,
        question_type=QUESTION_TYPE_SHORT_ANSWER,
        options_json=[],
        correct_short_answer=answer,
        time_limit_sec=time_limit_sec,
        points_base=1000,
        source_model='Test',
        source_id=order,
    )


def _make_participant(session, nickname='MobileTester'):
    from brainbuzz.models import BrainBuzzParticipant
    return BrainBuzzParticipant.objects.create(session=session, nickname=nickname)


def _seat_participant(page, live_server_url, join_code, participant_id):
    """Put `participant_id` in the browser's Django session for `join_code`.

    The student page reads the participant out of the session cookie, so this
    is the shortcut past the join screen for tests that are not about joining.
    """
    from django.test import Client
    client = Client()
    client.get(f'{live_server_url}/')
    django_session = client.session
    django_session[f'bb_pid_{join_code}'] = participant_id
    django_session.save()
    page.goto(live_server_url)
    page.evaluate(
        f"() => {{ document.cookie = 'sessionid={django_session.session_key}; path=/'; }}"
    )


def _open_play(page, live_server_url, join_code):
    page.goto(f'{live_server_url}/brainbuzz/play/{join_code}/')
    page.wait_for_load_state('domcontentloaded')
    # Alpine's init() publishes the component instance; several tests below
    # drive it directly, and every test needs the first paint to have happened.
    page.wait_for_function('() => !!window.bbStudentApp', timeout=POLL_TIMEOUT)


def _tiles(page):
    return page.locator('button[aria-label^="Option "]')


def _activate(session, timer_sec=30, current_index=0):
    """Move a session to ACTIVE with a fresh deadline (as the teacher would)."""
    from django.utils import timezone
    from brainbuzz.models import BrainBuzzSession
    session.refresh_from_db()
    session.status = BrainBuzzSession.STATUS_ACTIVE
    session.current_index = current_index
    session.question_deadline = timezone.now() + timedelta(seconds=timer_sec)
    session.save()
    session.bump_version()


def _set_status(session, status):
    # refresh + bump_version, never `state_version += 1` on a stale instance:
    # the app bumps the version too (api_join does, for one), so writing back a
    # remembered value can land on the number the browser already polled — the
    # next poll 304s and the page never learns the state changed.
    session.refresh_from_db()
    session.status = status
    session.save()
    session.bump_version()


# ---------------------------------------------------------------------------
# Full journey
# ---------------------------------------------------------------------------

class TestStudentMobileE2E:
    """Lobby → question → lock-in → reveal → results, all on one page load."""

    @pytest.fixture(autouse=True)
    def _setup(self, db, live_server, mobile_page):
        self.url = live_server.url
        self.page = mobile_page
        self.teacher = _make_teacher('bb_mob_e2e_t')
        self.subject = _make_subject()

    def test_full_quiz_flow_mcq(self):
        from brainbuzz.models import BrainBuzzSession

        session = _make_session(
            self.teacher, self.subject, 'MOBE01', BrainBuzzSession.STATUS_LOBBY
        )
        _make_mcq_question(session, correct_label='A')
        participant = _make_participant(session)
        _seat_participant(self.page, self.url, 'MOBE01', participant.id)
        _open_play(self.page, self.url, 'MOBE01')

        # ── Lobby ────────────────────────────────────────────────────────
        expect(self.page.get_by_text('Waiting for teacher to start', exact=False)
               ).to_be_visible()

        # ── Teacher starts: question and four tiles appear ───────────────
        _activate(session)
        expect(self.page.get_by_text('Mobile Test Question 1', exact=False)
               ).to_be_visible(timeout=POLL_TIMEOUT)
        tiles = _tiles(self.page)
        expect(tiles).to_have_count(4, timeout=POLL_TIMEOUT)

        # Colorblind-safe: each tile carries its own shape SVG *and* colour, so
        # the four are distinguishable without relying on hue alone.
        shape_markers = ['polygon', 'polygon', 'circle', 'rect']
        colours = ['bg-red-500', 'bg-blue-500', 'bg-yellow-500', 'bg-green-600']
        for index, (marker, colour) in enumerate(zip(shape_markers, colours)):
            tile = tiles.nth(index)
            assert marker in tile.inner_html(), (
                f'tile {index} is missing its {marker} shape — colour would be '
                f'the only cue left')
            assert colour in (tile.get_attribute('class') or '')

        # ── Tap the correct tile → locks in with points ──────────────────
        tiles.nth(0).click()
        expect(self.page.get_by_text('Answer locked in!', exact=False)
               ).to_be_visible(timeout=5_000)
        expect(self.page.get_by_text('🎯 Correct!', exact=True)).to_be_visible()
        expect(self.page.get_by_text(re.compile(r'^\+\d+ pts$'))).to_be_visible()
        participant.refresh_from_db()
        assert participant.score > 0

        # ── Reveal: rank and the class answer distribution ───────────────
        _set_status(session, BrainBuzzSession.STATUS_REVEAL)
        expect(self.page.get_by_text('Your Rank', exact=False)
               ).to_be_visible(timeout=POLL_TIMEOUT)
        expect(self.page.get_by_text('Class Answers', exact=False)).to_be_visible()
        expect(self.page.get_by_text('Waiting for teacher to continue', exact=False)
               ).to_be_visible()

        # ── Finished: rank, total score, and a way back in ───────────────
        _set_status(session, BrainBuzzSession.STATUS_FINISHED)
        expect(self.page.get_by_text('You came #', exact=False)
               ).to_be_visible(timeout=POLL_TIMEOUT)
        expect(self.page.get_by_text('Total Score', exact=False)).to_be_visible()
        expect(self.page.get_by_role('link', name='Play Again', exact=False)
               ).to_be_visible()

    def test_join_screen_to_lobby(self):
        """The real join path: prefilled code → nickname → lobby."""
        from brainbuzz.models import BrainBuzzParticipant, BrainBuzzSession

        session = _make_session(
            self.teacher, self.subject, 'MOBJ01', BrainBuzzSession.STATUS_LOBBY
        )
        _make_mcq_question(session)

        # ?code= prefills and skips straight to the nickname step.
        self.page.goto(f'{self.url}/brainbuzz/join/?code=MOBJ01')
        self.page.wait_for_load_state('domcontentloaded')

        nickname = self.page.locator('#nickname-input')
        expect(nickname).to_be_visible(timeout=POLL_TIMEOUT)
        nickname.fill('MobileJoiner')
        self.page.get_by_role('button', name="Let's Go!", exact=False).click()

        expect(self.page.get_by_text('Waiting for host to start…', exact=True)
               ).to_be_visible(timeout=POLL_TIMEOUT)
        assert BrainBuzzParticipant.objects.filter(
            session=session, nickname='MobileJoiner').exists()

        # Teacher starts → the lobby forwards the student into the game.
        _activate(session)
        self.page.wait_for_url('**/brainbuzz/play/MOBJ01/', timeout=POLL_TIMEOUT)

    def test_short_answer_variant(self):
        from brainbuzz.models import BrainBuzzSession

        session = _make_session(
            self.teacher, self.subject, 'MOBS01', BrainBuzzSession.STATUS_ACTIVE
        )
        _make_short_question(session, answer='4')
        participant = _make_participant(session)
        _seat_participant(self.page, self.url, 'MOBS01', participant.id)
        _open_play(self.page, self.url, 'MOBS01')

        answer = self.page.locator('#bb-text-answer')
        expect(answer).to_be_visible(timeout=POLL_TIMEOUT)
        assert answer.get_attribute('placeholder') == 'Your answer...'

        answer.fill('4')
        self.page.get_by_role('button', name='Submit Answer').click()

        expect(self.page.get_by_text('Answer locked in!', exact=False)
               ).to_be_visible(timeout=5_000)
        expect(self.page.get_by_text('Correct!', exact=True)).to_be_visible()


# ---------------------------------------------------------------------------
# Question chrome
# ---------------------------------------------------------------------------

class TestQuestionChrome:

    @pytest.fixture(autouse=True)
    def _setup(self, db, live_server, mobile_page):
        self.url = live_server.url
        self.page = mobile_page
        self.teacher = _make_teacher('bb_mob_chrome_t')
        self.subject = _make_subject()

    def test_countdown_timer_display(self):
        """The countdown pill shows seconds remaining and ticks down."""
        from brainbuzz.models import BrainBuzzSession

        session = _make_session(
            self.teacher, self.subject, 'MOBC01',
            BrainBuzzSession.STATUS_ACTIVE, timer_sec=25,
        )
        _make_mcq_question(session, time_limit_sec=25)
        participant = _make_participant(session)
        _seat_participant(self.page, self.url, 'MOBC01', participant.id)
        _open_play(self.page, self.url, 'MOBC01')

        expect(_tiles(self.page).first).to_be_visible(timeout=POLL_TIMEOUT)

        # The pill renders whatever the countdown currently is — checked inside
        # ONE browser evaluation.
        #
        # Reading window.bbStudentApp.countdown into Python and THEN asserting
        # that number is on screen races the timer it is measuring: between the
        # two steps the pill ticks to the next second, and to_be_visible then
        # spends its whole timeout waiting for a value that will never come
        # back. It passed only when the read happened to land early in a tick.
        # Comparing the DOM against the live value in the same evaluation has no
        # gap to lose, and wait_for_function simply retries if a tick lands
        # mid-check.
        self.page.wait_for_function(
            """() => {
                 const app = window.bbStudentApp;
                 if (!app || !(app.countdown > 0)) return false;
                 return [...document.querySelectorAll('span')]
                   .some(el => el.textContent.trim() === String(app.countdown));
               }""",
            timeout=POLL_TIMEOUT)

        # ...and it ticks down. Safe to snapshot here: the countdown only ever
        # decreases, so a stale read makes the wait strictly easier, not flaky.
        first = self.page.evaluate('() => window.bbStudentApp.countdown')
        assert 0 < first <= 25, f'countdown started at {first}'
        self.page.wait_for_function(
            f'() => window.bbStudentApp.countdown < {first}', timeout=5_000)

    def test_haptic_feedback_on_tap(self):
        """Tapping a tile fires navigator.vibrate."""
        from brainbuzz.models import BrainBuzzSession

        session = _make_session(
            self.teacher, self.subject, 'MOBH01', BrainBuzzSession.STATUS_ACTIVE
        )
        _make_mcq_question(session)
        participant = _make_participant(session)
        _seat_participant(self.page, self.url, 'MOBH01', participant.id)

        # navigator.vibrate is absent in headless Chromium, so the page's
        # `if (navigator.vibrate)` guard would skip silently. Install a stub
        # before any page script runs and record what it is called with.
        self.page.add_init_script("""
            window.__vibrations = [];
            Object.defineProperty(navigator, 'vibrate', {
                configurable: true,
                value: function (pattern) {
                    window.__vibrations.push(pattern);
                    return true;
                },
            });
        """)
        _open_play(self.page, self.url, 'MOBH01')

        tiles = _tiles(self.page)
        expect(tiles.first).to_be_visible(timeout=POLL_TIMEOUT)
        tiles.first.click()

        self.page.wait_for_function(
            '() => window.__vibrations.length > 0', timeout=5_000)

    def test_already_answered_lock(self):
        """Reloading after answering shows the lock banner, not fresh tiles."""
        from brainbuzz.models import BrainBuzzSession

        session = _make_session(
            self.teacher, self.subject, 'MOBA01', BrainBuzzSession.STATUS_ACTIVE
        )
        _make_mcq_question(session, correct_label='A')
        participant = _make_participant(session)
        _seat_participant(self.page, self.url, 'MOBA01', participant.id)
        _open_play(self.page, self.url, 'MOBA01')

        tiles = _tiles(self.page)
        expect(tiles.first).to_be_visible(timeout=POLL_TIMEOUT)
        tiles.nth(0).click()
        expect(self.page.get_by_text('Answer locked in!', exact=False)
               ).to_be_visible(timeout=5_000)

        # Second visit to the same question: no tappable tiles, still locked.
        _open_play(self.page, self.url, 'MOBA01')
        expect(self.page.get_by_text('Answer locked in!', exact=False)
               ).to_be_visible(timeout=POLL_TIMEOUT)
        expect(_tiles(self.page)).to_have_count(0)


# ---------------------------------------------------------------------------
# Network resilience
# ---------------------------------------------------------------------------

class TestNetworkResilience:

    @pytest.fixture(autouse=True)
    def _setup(self, db, live_server, mobile_page):
        self.url = live_server.url
        self.page = mobile_page
        self.teacher = _make_teacher('bb_mob_net_t')
        self.subject = _make_subject()

    def _seated_session(self, code):
        from brainbuzz.models import BrainBuzzSession
        session = _make_session(
            self.teacher, self.subject, code, BrainBuzzSession.STATUS_ACTIVE
        )
        _make_mcq_question(session)
        participant = _make_participant(session)
        _seat_participant(self.page, self.url, code, participant.id)
        return session

    def test_network_error_banner(self):
        """A failing state poll raises the reconnecting banner."""
        self._seated_session('MOBN01')
        _open_play(self.page, self.url, 'MOBN01')
        expect(_tiles(self.page).first).to_be_visible(timeout=POLL_TIMEOUT)

        # Kill the state endpoint; the next poll fails.
        self.page.route('**/brainbuzz/api/session/**/state/**',
                        lambda route: route.abort())

        expect(self.page.get_by_text('Network error', exact=False)
               ).to_be_visible(timeout=POLL_TIMEOUT)

    def test_offline_retry_backoff_and_recovery(self):
        """Polling keeps retrying while offline, backs off, then recovers."""
        self._seated_session('MOBN02')

        self.page.add_init_script("""
            window.__pollAttempts = [];
            const realFetch = window.fetch;
            window.__failPolls = false;
            window.fetch = function (...args) {
                const url = typeof args[0] === 'string' ? args[0] : args[0].url;
                if (window.__failPolls && url.includes('/state/')) {
                    window.__pollAttempts.push(Date.now());
                    return Promise.reject(new Error('offline'));
                }
                return realFetch.apply(this, args);
            };
        """)
        _open_play(self.page, self.url, 'MOBN02')
        expect(_tiles(self.page).first).to_be_visible(timeout=POLL_TIMEOUT)

        self.page.evaluate('() => { window.__failPolls = true; }')

        # It must keep trying rather than give up after the first failure.
        self.page.wait_for_function(
            '() => window.__pollAttempts.length >= 3', timeout=20_000)
        expect(self.page.get_by_text('Network error', exact=False)
               ).to_be_visible(timeout=POLL_TIMEOUT)

        gaps = self.page.evaluate("""
            () => window.__pollAttempts
                .slice(1)
                .map((t, i) => t - window.__pollAttempts[i])
        """)
        assert gaps[-1] > gaps[0], (
            f'retries are not backing off — gaps were {gaps}ms, so a flapping '
            f'connection would be hammered at a constant rate')

        # Back online: the banner clears without a reload.
        self.page.evaluate('() => { window.__failPolls = false; }')
        expect(self.page.get_by_text('Network error', exact=False)
               ).to_be_hidden(timeout=30_000)


# ---------------------------------------------------------------------------
# Accessibility and mobile layout
# ---------------------------------------------------------------------------

class TestMobileAccessibility:

    @pytest.fixture(autouse=True)
    def _setup(self, db, live_server, mobile_page):
        self.url = live_server.url
        self.page = mobile_page
        self.teacher = _make_teacher('bb_mob_a11y_t')
        self.subject = _make_subject()

    def _open_active(self, code):
        from brainbuzz.models import BrainBuzzSession
        session = _make_session(
            self.teacher, self.subject, code, BrainBuzzSession.STATUS_ACTIVE
        )
        _make_mcq_question(session)
        participant = _make_participant(session)
        _seat_participant(self.page, self.url, code, participant.id)
        _open_play(self.page, self.url, code)
        expect(_tiles(self.page).first).to_be_visible(timeout=POLL_TIMEOUT)
        return session

    def test_aria_live_regions(self):
        """Screen readers get announcements for state changes."""
        self._open_active('MOBY01')
        expect(self.page.locator('[aria-live="polite"]').first).to_be_attached()
        assert self.page.locator('[aria-live]').count() > 0

        # The answer result is assertive — it interrupts, because it is the
        # thing the student just asked for.
        _tiles(self.page).first.click()
        expect(self.page.locator('[aria-live="assertive"]').first
               ).to_be_visible(timeout=5_000)

    def test_every_tile_has_an_accessible_name(self):
        self._open_active('MOBY02')
        tiles = _tiles(self.page)
        for index in range(tiles.count()):
            label = tiles.nth(index).get_attribute('aria-label')
            assert label and label.startswith('Option '), (
                f'tile {index} has aria-label {label!r}; the letter badge and '
                f'shape are aria-hidden, so this is the only name it has')

    def test_tab_order_reaches_the_tiles(self):
        """Keyboard users can reach the answer tiles."""
        self._open_active('MOBY03')

        label = None
        for _ in range(25):
            self.page.keyboard.press('Tab')
            label = self.page.evaluate(
                "() => document.activeElement && "
                "document.activeElement.getAttribute('aria-label')")
            if label and label.startswith('Option '):
                break
        assert label and label.startswith('Option '), (
            'tabbing 25 times never landed on an answer tile')

    def test_mobile_viewport_sizing(self):
        """Four tiles fit the phone viewport without horizontal scrolling."""
        self._open_active('MOBY04')

        assert self.page.viewport_size == MOBILE_VIEWPORT

        scroll_width, client_width = self.page.evaluate(
            '() => [document.documentElement.scrollWidth, '
            'document.documentElement.clientWidth]')
        assert scroll_width <= client_width + 1, (
            f'page scrolls sideways on a {MOBILE_VIEWPORT["width"]}px screen '
            f'({scroll_width}px of content in {client_width}px)')

        tiles = _tiles(self.page)
        for index in range(tiles.count()):
            box = tiles.nth(index).bounding_box()
            assert box is not None, f'tile {index} has no box'
            assert box['x'] >= -1 and box['x'] + box['width'] <= client_width + 1, (
                f'tile {index} overflows the viewport horizontally: {box}')
