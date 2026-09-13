"""Shared helper utilities for Playwright UI tests."""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect


def wait_for_htmx(page: Page, timeout: int = 5_000) -> None:
    """Wait until any in-flight HTMX request finishes."""
    page.wait_for_function(
        "() => !document.querySelector('.htmx-request')",
        timeout=timeout,
    )


def wait_for_network_idle(page: Page, timeout: int = 5_000) -> None:
    """Wait for all network activity to settle (useful after fetch-based quiz submissions)."""
    page.wait_for_load_state("networkidle", timeout=timeout)


def _ensure_sidebar_visible(page: Page) -> None:
    """Force the desktop sidebar to be visible and expand collapsed sections.

    Tailwind CDN may not generate responsive ``md:flex`` styles in headless
    Chromium, so the ``hidden md:flex`` aside stays ``display:none``.
    We also expand any Alpine.js collapsed sections (x-show divs) so all
    sidebar links are accessible for testing.
    """
    page.evaluate("""() => {
        const aside = document.querySelector('aside#sidebar');
        if (aside) {
            aside.style.display = 'flex';
            aside.style.flexDirection = 'column';
            // Force ALL hidden elements visible inside sidebar via CSS override
            aside.querySelectorAll('[x-show], [style*="display: none"], [style*="display:none"]').forEach(el => {
                el.style.setProperty('display', 'block', 'important');
            });
            aside.querySelectorAll('nav [x-show]').forEach(el => {
                if (el.querySelector('a')) {
                    el.style.setProperty('display', 'flex', 'important');
                }
            });
        }
    }""")


def assert_sidebar_has_link(page: Page, text: str) -> None:
    """Assert that a sidebar link with the given text exists."""
    _ensure_sidebar_visible(page)
    link = page.locator("aside#sidebar a", has_text=text).first
    expect(link).to_be_visible()


def assert_sidebar_missing_link(page: Page, text: str) -> None:
    """Assert that a sidebar link with the given text does NOT exist."""
    _ensure_sidebar_visible(page)
    link = page.locator("aside#sidebar a", has_text=text)
    expect(link).to_have_count(0)


def click_sidebar_link(page: Page, text: str) -> None:
    """Click a sidebar link and wait for navigation."""
    _ensure_sidebar_visible(page)
    link = page.locator("aside#sidebar a", has_text=text).first
    expect(link).to_be_visible()
    link.click(force=True)
    page.wait_for_load_state("domcontentloaded")


def assert_page_has_text(page: Page, text: str) -> None:
    """Assert the page body contains the given text."""
    expect(page.locator("body")).to_contain_text(text)


def assert_url_contains(page: Page, fragment: str) -> None:
    """Assert the current URL contains the given fragment."""
    expect(page).to_have_url(re.compile(re.escape(fragment)))


def assert_card_visible(page: Page, text: str) -> None:
    """Assert a card-like element (div/section with rounded styling) containing text is visible."""
    card = page.locator(
        "div.rounded-2xl, div.rounded-xl, div.rounded-lg, section",
        has_text=text,
    ).first
    expect(card).to_be_visible()


def content_excluding_progress_art(page: Page) -> str:
    """The page's HTML with the progress-art panel stripped out.

    Use this instead of ``page.content()`` for "this answer must never appear in
    the source" assertions.

    The panel embeds its hidden picture as a few hundred SVG path coordinates,
    so a bare number the test cares about can turn up inside it by pure
    coincidence — "105" occurs in three of the pictures. Since which picture a
    quiz gets is seeded on its session id, a whole-page check against a bare
    number then failed only on the runs that happened to pick one of the three.

    Stripping the panel keeps the assertion's full breadth over everything that
    could actually leak an answer, rather than narrowing it to one element.
    """
    return page.evaluate(
        """() => {
            const doc = document.documentElement.cloneNode(true);
            doc.querySelectorAll('[data-progress-art]').forEach(el => el.remove());
            return doc.outerHTML;
        }"""
    )
