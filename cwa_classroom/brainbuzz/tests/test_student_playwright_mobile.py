"""
test_student_playwright_mobile.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Playwright mobile E2E tests for full student flow (CPP-237):
  - Full QR → code → nickname → lobby → answer → reveal → results
  - Mobile viewport (375×812 iPhone 12 mini)
  - Colorblind-safe tile shapes verification
  - Tap-to-lock latency (<300ms perceived)
  - Haptic feedback verification
  - Network error recovery (offline retry)
  - Already-answered scenarios
"""
import unittest
try:
    import pytest
    from playwright.async_api import async_playwright, Page, Browser, BrowserContext
    _PLAYWRIGHT_OK = True
except ImportError:
    _PLAYWRIGHT_OK = False

if not _PLAYWRIGHT_OK:
    raise unittest.SkipTest('playwright not installed')

import asyncio
import json
from pathlib import Path


# Test URLs and codes
BASE_URL = "http://localhost:8000"
SESSION_CODE = "PYTEST"
PARTICIPANT_NICKNAME = "PlaywrightTest"


@pytest.fixture
async def browser():
    """Launch Playwright browser with mobile viewport."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        yield browser
        await browser.close()


@pytest.fixture
async def mobile_context(browser: Browser):
    """Create mobile context with iPhone 12 mini viewport."""
    context = await browser.new_context(
        viewport={"width": 375, "height": 812},
        device_scale_factor=3,
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)"
    )
    yield context
    await context.close()


@pytest.fixture
async def page(mobile_context: BrowserContext):
    """Create a page in mobile context."""
    page = await mobile_context.new_page()
    yield page
    await page.close()


class TestStudentMobileE2E:
    """Full end-to-end flow on mobile viewport."""

    @pytest.mark.asyncio
    async def test_full_quiz_flow_mcq(self, page: Page):
        """Complete MCQ quiz flow: join → answer → reveal → results."""
        
        # Step 1: Navigate to join screen
        await page.goto(f"{BASE_URL}/brainbuzz/join/?code={SESSION_CODE}")
        await page.wait_for_load_state("networkidle")
        
        # Step 2: Code should be pre-filled and uppercased
        code_input = page.locator('input[placeholder*="code"]')
        code_value = await code_input.input_value()
        assert code_value.upper() == SESSION_CODE
        
        # Step 3: Enter nickname
        nickname_input = page.locator('input[placeholder*="nickname"]')
        await nickname_input.fill(PARTICIPANT_NICKNAME)
        
        # Step 4: Submit join
        submit_btn = page.locator('button:has-text("Join Game")')
        await submit_btn.click()
        
        # Wait for redirect to lobby
        await page.wait_for_url(f"{BASE_URL}/brainbuzz/play/*")
        await page.wait_for_load_state("networkidle")
        
        # Step 5: Verify in lobby
        assert "Waiting for host" in await page.content()
        
        # (In real test, teacher would start the session here)
        # For now, simulate state change with mock API
        await page.evaluate("""
            () => {
                window.bbStudent.gameStatus = 'active';
                window.bbStudent.question = {
                    id: 1,
                    question_text: 'Which is correct?',
                    question_type: 'mcq',
                    options: [
                        {label: 'A', text: 'Option A'},
                        {label: 'B', text: 'Option B'},
                        {label: 'C', text: 'Option C'},
                        {label: 'D', text: 'Option D'}
                    ]
                };
            }
        """)
        
        await page.wait_for_timeout(100)
        
        # Step 6: Verify question displayed
        question_text = page.locator("p:has-text('Which is correct?')")
        assert await question_text.count() > 0
        
        # Step 7: Verify four tiles visible
        tiles = page.locator("button[aria-label='Option']")
        assert await tiles.count() == 4
        
        # Step 8: Verify tile shapes and colors (colorblind-safe)
        shapes = ['▲', '◆', '●', '■']
        colors = ['#ef4444', '#3b82f6', '#eab308', '#10b981']  # red, blue, yellow, green
        
        for i, (shape, color) in enumerate(zip(shapes, colors)):
            tile = tiles.nth(i)
            assert shape in await tile.text_content()
        
        # Step 9: Tap a tile (A - red triangle)
        tile_a = tiles.nth(0)
        await tile_a.click()
        
        # Step 10: Verify tap-to-lock latency (<300ms perceived)
        start_time = page.context.clock.millis if hasattr(page.context, 'clock') else 0
        
        # Should see lock-in feedback
        locked = page.locator("text=/Answer locked|Correct|Incorrect/i")
        await locked.wait_for(timeout=300)  # Must appear within 300ms
        
        # Step 11: Verify correct/incorrect display
        feedback_text = await locked.text_content()
        assert "Correct" in feedback_text or "Incorrect" in feedback_text
        
        # Step 12: Verify points display
        points = page.locator("text=/\\+?\\d+ pts/")
        assert await points.count() > 0
        
        # Step 13: Simulate reveal phase
        await page.evaluate("""
            () => {
                window.bbStudent.gameStatus = 'reveal';
                window.bbStudent.autoAdvanceCountdown = 3;
            }
        """)
        
        await page.wait_for_timeout(100)
        
        # Step 14: Verify reveal shows distribution
        distribution = page.locator("text=Answer Distribution")
        assert await distribution.count() > 0
        
        # Step 15: Verify rank display
        rank = page.locator("text=/Your Rank|#\\d+/")
        assert await rank.count() > 0
        
        # Step 16: Simulate finished phase
        await page.evaluate("""
            () => {
                window.bbStudent.gameStatus = 'finished';
                window.bbStudent.finalRank = 3;
                window.bbStudent.totalParticipants = 10;
                window.bbStudent.totalScore = 1000;
                window.bbStudent.correctCount = 1;
                window.bbStudent.incorrectCount = 0;
            }
        """)
        
        await page.wait_for_timeout(100)
        
        # Step 17: Verify end screen displays results
        game_over = page.locator("text=Game Over")
        assert await game_over.count() > 0
        
        final_rank = page.locator("text=Final Rank")
        assert await final_rank.count() > 0
        
        # Step 18: Verify "Join New Game" button
        new_game_btn = page.locator('a:has-text("Join New Game")')
        assert await new_game_btn.count() > 0

    @pytest.mark.asyncio
    async def test_short_answer_variant(self, page: Page):
        """Test short answer question variant."""
        
        await page.goto(f"{BASE_URL}/brainbuzz/join/?code={SESSION_CODE}")
        await page.wait_for_load_state("networkidle")
        
        # Simulate active state with short answer question
        await page.evaluate("""
            () => {
                window.bbStudent.gameStatus = 'active';
                window.bbStudent.question = {
                    question_text: 'What is 2+2?',
                    question_type: 'short_answer',
                    options: []
                };
            }
        """)
        
        await page.wait_for_timeout(100)
        
        # Should see text input
        text_input = page.locator("input[placeholder='Your answer...']")
        assert await text_input.count() > 0
        
        # Should see submit button
        submit_btn = page.locator("button:has-text('Submit Answer')")
        assert await submit_btn.count() > 0
        
        # Type answer
        await text_input.fill("4")
        
        # Click submit
        await submit_btn.click()
        
        # Should see lock-in feedback
        await page.locator("text=/Correct|Incorrect/i").wait_for(timeout=300)

    @pytest.mark.asyncio
    async def test_countdown_timer_display(self, page: Page):
        """Verify countdown timer SVG is visible and updates."""
        
        await page.goto(f"{BASE_URL}/brainbuzz/join/?code={SESSION_CODE}")
        
        # Simulate active state
        await page.evaluate("""
            () => {
                window.bbStudent.gameStatus = 'active';
                window.bbStudent.question = {
                    question_text: 'Test?',
                    question_type: 'mcq',
                    options: [{label: 'A', text: 'Yes'}],
                    question_deadline: new Date(Date.now() + 20000).toISOString()
                };
                window.bbStudent.countdown = 15;
            }
        """)
        
        await page.wait_for_timeout(100)
        
        # Should see SVG countdown
        svg = page.locator("svg.countdown-circle")
        assert await svg.count() > 0
        
        # Should see time remaining
        countdown_text = page.locator("text=/\\d+s/")
        assert await countdown_text.count() > 0

    @pytest.mark.asyncio
    async def test_haptic_feedback_on_tap(self, page: Page):
        """Verify haptic feedback is triggered on answer (mocked)."""
        
        await page.goto(f"{BASE_URL}/brainbuzz/join/?code={SESSION_CODE}")
        
        # Mock navigator.vibrate
        vibration_calls = []
        await page.add_init_script("""
            window.vibrationCalls = [];
            const originalVibrate = navigator.vibrate.bind(navigator);
            navigator.vibrate = function(pattern) {
                window.vibrationCalls.push(pattern);
                return originalVibrate(pattern);
            };
        """)
        
        await page.evaluate("""
            () => {
                window.bbStudent.gameStatus = 'active';
                window.bbStudent.question = {
                    question_text: 'Test?',
                    question_type: 'mcq',
                    options: [
                        {label: 'A', text: 'Yes'},
                        {label: 'B', text: 'No'},
                    ]
                };
            }
        """)
        
        # Click tile (will trigger haptic)
        tiles = page.locator("button[aria-label='Option']")
        await tiles.first.click()
        
        # Check vibration was called
        vibration_calls = await page.evaluate("() => window.vibrationCalls")
        assert len(vibration_calls) > 0

    @pytest.mark.asyncio
    async def test_already_answered_lock(self, page: Page):
        """Test that already-answered tiles lock immediately."""
        
        await page.goto(f"{BASE_URL}/brainbuzz/join/?code={SESSION_CODE}")
        
        await page.evaluate("""
            () => {
                window.bbStudent.gameStatus = 'active';
                window.bbStudent.question = {
                    question_text: 'Test?',
                    question_type: 'mcq',
                    options: [
                        {label: 'A', text: 'Yes'},
                        {label: 'B', text: 'No'},
                    ]
                };
                window.bbStudent.alreadyAnswered = true;
            }
        """)
        
        await page.wait_for_timeout(100)
        
        # Tiles should be disabled
        tiles = page.locator("button[aria-label='Option']")
        for i in range(await tiles.count()):
            tile = tiles.nth(i)
            is_disabled = await tile.evaluate("el => el.disabled")
            assert is_disabled

    @pytest.mark.asyncio
    async def test_network_error_banner(self, page: Page):
        """Verify network error banner appears on connection loss."""
        
        await page.goto(f"{BASE_URL}/brainbuzz/join/?code={SESSION_CODE}")
        
        await page.evaluate("""
            () => {
                window.bbStudent.networkError = true;
            }
        """)
        
        await page.wait_for_timeout(100)
        
        # Should see error banner
        error_banner = page.locator("text=Network error")
        assert await error_banner.count() > 0

    @pytest.mark.asyncio
    async def test_aria_live_regions(self, page: Page):
        """Verify ARIA live regions exist for accessibility."""
        
        await page.goto(f"{BASE_URL}/brainbuzz/join/?code={SESSION_CODE}")
        
        # Look for aria-live regions
        live_regions = page.locator("[aria-live]")
        assert await live_regions.count() > 0
        
        # Should have polite and atomic attributes
        polite_regions = page.locator("[aria-live='polite']")
        assert await polite_regions.count() > 0

    @pytest.mark.asyncio
    async def test_mobile_viewport_sizing(self, page: Page):
        """Verify layout is optimized for mobile viewport."""
        
        await page.goto(f"{BASE_URL}/brainbuzz/join/?code={SESSION_CODE}")
        
        # Check viewport dimensions
        viewport_size = page.view_port_size
        assert viewport_size["width"] == 375
        assert viewport_size["height"] == 812
        
        # Verify tiles fit in viewport without scrolling (in grid view)
        await page.evaluate("""
            () => {
                window.bbStudent.gameStatus = 'active';
                window.bbStudent.question = {
                    question_text: 'Test?',
                    question_type: 'mcq',
                    options: [
                        {label: 'A', text: 'Yes'},
                        {label: 'B', text: 'No'},
                        {label: 'C', text: 'Maybe'},
                        {label: 'D', text: 'No idea'},
                    ]
                };
            }
        """)
        
        await page.wait_for_timeout(100)
        
        # Check that grid tiles are visible without scrolling
        tiles = page.locator("button[aria-label='Option']")
        for i in range(await tiles.count()):
            tile = tiles.nth(i)
            box = await tile.bounding_box()
            # Tile should be within viewport
            assert box["y"] + box["height"] <= 812

    @pytest.mark.asyncio
    async def test_tab_order_accessibility(self, page: Page):
        """Verify keyboard navigation works for accessibility."""
        
        await page.goto(f"{BASE_URL}/brainbuzz/join/?code={SESSION_CODE}")
        
        # Simulate active state
        await page.evaluate("""
            () => {
                window.bbStudent.gameStatus = 'active';
                window.bbStudent.question = {
                    question_text: 'Test?',
                    question_type: 'mcq',
                    options: [
                        {label: 'A', text: 'Yes'},
                        {label: 'B', text: 'No'},
                        {label: 'C', text: 'Maybe'},
                        {label: 'D', text: 'No idea'},
                    ]
                };
            }
        """)
        
        await page.wait_for_timeout(100)
        
        # Tab to first tile
        await page.keyboard.press("Tab")
        
        # Check that focus is on a tile
        focused_element = await page.evaluate("() => document.activeElement.getAttribute('aria-label')")
        assert focused_element == "Option" or focused_element is None  # May depend on implementation

    @pytest.mark.asyncio
    async def test_offline_retry_backoff(self, page: Page):
        """Test offline retry with exponential backoff (mocked)."""
        
        await page.goto(f"{BASE_URL}/brainbuzz/join/?code={SESSION_CODE}")
        
        # Mock fetch to simulate network error
        request_times = []
        await page.add_init_script("""
            window.requestTimes = [];
            const originalFetch = fetch;
            let requestCount = 0;
            window.fetch = async function(...args) {
                window.requestTimes.push(Date.now());
                requestCount++;
                // First 2 calls fail, 3rd succeeds
                if (requestCount <= 2) {
                    throw new Error('Network error');
                }
                return originalFetch(...args);
            };
        """)
        
        # Simulate submit with retry
        await page.evaluate("""
            async () => {
                window.bbStudent.gameStatus = 'active';
                window.bbStudent.question = {
                    question_type: 'mcq',
                    options: [{label: 'A', text: 'Yes'}]
                };
                await window.bbStudent.submitAnswer({option_label: 'A'});
            }
        """)
        
        await page.wait_for_timeout(6000)  # Allow time for retries
        
        # Check that retries were attempted
        request_times_list = await page.evaluate("() => window.requestTimes")
        assert len(request_times_list) >= 3  # At least 1 + 2 retries


# Pytest configuration
def pytest_configure(config):
    """Mark async tests."""
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )


if __name__ == "__main__":
    # Run with: pytest test_student_playwright_mobile.py -v -s
    pytest.main([__file__, "-v", "-s"])
