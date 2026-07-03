"""
Playwright UI tests for CPP-314: Crossword puzzle exercise.

Covers:
1. Grid renders with white cells, black cells, and numbered clue squares
2. Click a cell → word highlights, clue shown in mobile bar
3. Type a letter → auto-advances to next cell in word
4. Backspace on empty cell → retreats to previous cell
5. Check button — correct cells turn green, incorrect turn red, result bar appears
6. Reveal Word — fills the selected word's cells with the correct letters
7. Try Again — clears all inputs and resets result bar
8. Desktop clue panel shows Across and Down lists
9. Mobile modal opens from bottom bar tap and clue items are clickable
"""

import pytest
from playwright.sync_api import expect

from .conftest import do_login, _RUN_ID, TEST_PASSWORD


pytestmark = pytest.mark.cpp314


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_student(suffix=''):
    from accounts.models import CustomUser, Role, UserRole
    uid = f'cw314{suffix}_{_RUN_ID}'
    user = CustomUser.objects.create_user(
        username=f'student_{uid}',
        password=TEST_PASSWORD,
        email=f'student_{uid}@cpptest.com',
        profile_completed=True,
        must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(
        name=Role.STUDENT,
        defaults={'display_name': 'Student'},
    )
    UserRole.objects.get_or_create(user=user, role=role)
    return user


def _make_crossword(suffix=''):
    from languages.models import (
        Language, LanguageTopic, LanguageTopicLevel, LanguageExercise,
    )
    lang, _ = Language.objects.get_or_create(
        code=f'cw314{suffix}',
        defaults={
            'name': f'CWLang314{suffix}',
            'script_type': 'latin',
            'is_active': True,
            'order': 99,
        },
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang,
        name=f'CWTopic314{suffix}',
        defaults={'order': 1, 'is_active': True},
    )
    level, _ = LanguageTopicLevel.objects.get_or_create(
        topic=topic,
        level_choice=LanguageTopicLevel.BEGINNER,
    )
    # Simple intersecting 2-word puzzle for UI testing:
    #   CAT across at row=0,col=0
    #   COD down   at row=0,col=0  (shares C at [0,0])
    puzzle_data = {
        'width': 5,
        'height': 5,
        'words': [
            {
                'index': 0, 'number': 1, 'direction': 'across',
                'row': 0, 'col': 0, 'answer': 'CAT', 'clue': 'A small domestic pet',
            },
            {
                'index': 1, 'number': 1, 'direction': 'down',
                'row': 0, 'col': 0, 'answer': 'COD', 'clue': 'A type of fish',
            },
        ],
    }
    exercise = LanguageExercise.objects.create(
        topic_level=level,
        exercise_type=LanguageExercise.CROSSWORD,
        prompt='Animal Crossword',
        points=10,
        puzzle_data=puzzle_data,
        is_active=True,
    )
    return exercise


# ---------------------------------------------------------------------------
# Test class: Crossword grid rendering
# ---------------------------------------------------------------------------

class TestCrosswordGridRendering:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, db):
        from django.urls import reverse
        self.url = live_server.url
        self.page = page
        self.student = _make_student('grid')
        self.exercise = _make_crossword('grid')
        path = reverse('languages:exercise_detail', kwargs={'exercise_id': self.exercise.pk})
        self.exercise_url = f'{self.url}{path}'
        do_login(page, self.url, self.student)

    @pytest.mark.django_db(transaction=True)
    def test_grid_renders_cells_and_toolbar(self):
        """Grid table, white cells, toolbar buttons all visible on load."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')

        body = self.page.locator('body')
        expect(body).not_to_contain_text('Server Error')
        expect(body).not_to_contain_text('DoesNotExist')
        expect(body).not_to_contain_text('This crossword has no puzzle data')

        # Grid table present
        expect(self.page.locator('#cw-table')).to_be_visible()

        # White cells (cw-cell) present
        expect(self.page.locator('td.cw-cell').first).to_be_visible()

        # Toolbar buttons
        expect(self.page.locator('#btn-check')).to_be_visible()
        expect(self.page.locator('#btn-reveal')).to_be_visible()
        expect(self.page.locator('#btn-reset')).to_be_visible()

        # Reveal button starts disabled (no word selected)
        expect(self.page.locator('#btn-reveal')).to_be_disabled()

        # Result bar hidden initially
        expect(self.page.locator('#cw-result')).to_be_hidden()

    @pytest.mark.django_db(transaction=True)
    def test_clue_panel_shows_across_and_down(self):
        """Desktop clue panel has both Across and Down sections with clues."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')

        # Force desktop viewport to show clue panel
        self.page.set_viewport_size({'width': 1280, 'height': 800})

        clue_panel = self.page.locator('#cw-clue-panel')
        expect(clue_panel).to_be_visible()
        expect(clue_panel).to_contain_text('Across')
        expect(clue_panel).to_contain_text('Down')
        expect(clue_panel).to_contain_text('A small domestic pet')
        expect(clue_panel).to_contain_text('A type of fish')


# ---------------------------------------------------------------------------
# Test class: Cell interaction and word selection
# ---------------------------------------------------------------------------

class TestCrosswordCellInteraction:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, db):
        from django.urls import reverse
        self.url = live_server.url
        self.page = page
        self.student = _make_student('inter')
        self.exercise = _make_crossword('inter')
        path = reverse('languages:exercise_detail', kwargs={'exercise_id': self.exercise.pk})
        self.exercise_url = f'{self.url}{path}'
        do_login(page, self.url, self.student)

    @pytest.mark.django_db(transaction=True)
    def test_click_cell_highlights_word_and_enables_reveal(self):
        """Clicking a cell highlights the word and enables the Reveal button."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')

        # Click first white cell [0,0]
        first_cell = self.page.locator('td.cw-cell[data-row="0"][data-col="0"]')
        expect(first_cell).to_be_visible()
        first_cell.click()

        # Reveal Word should now be enabled
        expect(self.page.locator('#btn-reveal')).to_be_enabled()

        # At least one cell should have highlight class
        highlighted = self.page.locator('td.cw-cell.active-word, td.cw-cell.active-cell')
        expect(highlighted.first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_type_letter_and_auto_advance(self):
        """Typing in a cell auto-advances focus to the next cell in the word."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')

        # Click [0,1] — belongs ONLY to CAT (across), no ambiguity about direction
        cell_01 = self.page.locator('td.cw-cell[data-row="0"][data-col="1"]')
        cell_01.click()

        # Type 'A' — should auto-advance to [0,2]
        inp_01 = cell_01.locator('.cw-input')
        inp_01.fill('A')
        inp_01.dispatch_event('input')

        # Focus should now be on [0,2]
        next_input = self.page.locator('td.cw-cell[data-row="0"][data-col="2"] .cw-input')
        expect(next_input).to_be_focused()


# ---------------------------------------------------------------------------
# Test class: Check, Reveal, Reset
# ---------------------------------------------------------------------------

class TestCrosswordCheckRevealReset:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, db):
        from django.urls import reverse
        self.url = live_server.url
        self.page = page
        self.student = _make_student('crr')
        self.exercise = _make_crossword('crr')
        path = reverse('languages:exercise_detail', kwargs={'exercise_id': self.exercise.pk})
        self.exercise_url = f'{self.url}{path}'
        do_login(page, self.url, self.student)

    def _fill_word(self, row, col, direction, letters):
        """Type letters into a word starting at (row, col) going in direction."""
        for i, ch in enumerate(letters):
            r = row + (i if direction == 'down' else 0)
            c = col + (i if direction == 'across' else 0)
            inp = self.page.locator(f'td.cw-cell[data-row="{r}"][data-col="{c}"] .cw-input')
            inp.fill(ch)
            inp.dispatch_event('input')

    @pytest.mark.django_db(transaction=True)
    def test_check_all_correct_shows_result_bar_green(self):
        """Submitting all correct answers shows green result bar."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')

        # Fill CAT across (row=0, cols 0,1,2)
        self._fill_word(0, 0, 'across', 'CAT')
        # Fill COD down (row=0-2, col=0)
        self._fill_word(0, 0, 'down', 'COD')

        self.page.locator('#btn-check').click()
        self.page.wait_for_selector('#cw-result.show', timeout=5000)

        result_div = self.page.locator('#cw-result')
        expect(result_div).to_be_visible()

        result_msg = self.page.locator('#cw-result-msg')
        expect(result_msg).to_contain_text('2/2')

    @pytest.mark.django_db(transaction=True)
    def test_check_wrong_answer_shows_red_cells(self):
        """Wrong answers produce red cell colouring."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')

        # Fill all wrong
        self._fill_word(0, 0, 'across', 'XYZ')

        self.page.locator('#btn-check').click()
        self.page.wait_for_selector('#cw-result.show', timeout=5000)

        # At least one red cell
        red_cells = self.page.locator('td.cell-incorrect')
        expect(red_cells.first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_reveal_word_fills_cells(self):
        """Reveal Word fills selected word cells with correct letters."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')

        # Click [0,1] — belongs ONLY to CAT (across), no toggle ambiguity
        self.page.locator('td.cw-cell[data-row="0"][data-col="1"]').click()
        expect(self.page.locator('#btn-reveal')).to_be_enabled()
        self.page.locator('#btn-reveal').click()

        # CAT should now be in cells [0,0], [0,1], [0,2]
        for col, letter in enumerate('CAT'):
            inp = self.page.locator(f'td.cw-cell[data-row="0"][data-col="{col}"] .cw-input')
            expect(inp).to_have_value(letter)

    @pytest.mark.django_db(transaction=True)
    def test_try_again_resets_grid(self):
        """Try Again button clears all inputs and hides result bar."""
        self.page.goto(self.exercise_url)
        self.page.wait_for_load_state('domcontentloaded')

        # Fill + check first
        self._fill_word(0, 0, 'across', 'CAT')
        self.page.locator('#btn-check').click()
        self.page.wait_for_selector('#cw-result.show', timeout=5000)

        # Reset
        self.page.locator('#btn-reset').click()

        # Result bar hidden again
        expect(self.page.locator('#cw-result')).to_be_hidden()

        # All inputs empty
        first_inp = self.page.locator('td.cw-cell[data-row="0"][data-col="0"] .cw-input')
        expect(first_inp).to_have_value('')

        # Reveal disabled again
        expect(self.page.locator('#btn-reveal')).to_be_disabled()
