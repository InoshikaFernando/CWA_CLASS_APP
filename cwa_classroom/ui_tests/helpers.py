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


def assert_sidebar_has_link(page: Page, text: str) -> None:
    """Assert that a sidebar link with the given text is visible."""
    link = page.locator("nav a, aside a, [class*='sidebar'] a", has_text=text).first
    expect(link).to_be_visible()


def assert_sidebar_missing_link(page: Page, text: str) -> None:
    """Assert that a sidebar link with the given text is NOT visible."""
    link = page.locator("nav a, aside a, [class*='sidebar'] a", has_text=text)
    expect(link).to_have_count(0)


def click_sidebar_link(page: Page, text: str) -> None:
    """Click a sidebar link and wait for navigation."""
    link = page.locator("nav a, aside a, [class*='sidebar'] a", has_text=text).first
    expect(link).to_be_visible()
    link.click()
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
