"""
Tests for the Phase 3 registry-driven subject-sidebar context processor.

``classroom.context_processors.subject_sidebar_context`` now dispatches
via the SubjectPlugin registry (plugin.url_prefixes) instead of hard-coded
path branches. These tests pin the behaviour:

  - /maths/...           → subject_sidebar='maths',  slug='mathematics'
  - /number-puzzles/...  → subject_sidebar='maths'   (legacy maths prefix)
  - /coding/...          → subject_sidebar='coding', slug='coding'
  - /music/...           → subject_sidebar='music'   (legacy non-plugin path)
  - /science/...         → subject_sidebar='science' (legacy non-plugin path)
  - /hub/ (non-subject)  → no subject_sidebar key

These run as plain Django unit tests (no Playwright) — they're about the
context processor's logic, not UI rendering.
"""

from __future__ import annotations

import pytest
from django.test import RequestFactory

from classroom.context_processors import subject_sidebar_context


@pytest.fixture
def rf():
    return RequestFactory()


@pytest.mark.django_db(transaction=True)
class TestSubjectSidebarContext:

    def test_maths_prefix_maps_to_maths_sidebar(self, rf, subject):
        ctx = subject_sidebar_context(rf.get('/maths/dashboard/'))
        assert ctx['subject_sidebar'] == 'maths'
        assert ctx['current_subject_slug'] == 'mathematics'

    def test_number_puzzles_prefix_maps_to_maths_sidebar(self, rf, subject):
        """Legacy maths mini-app — registered under MathsPlugin.url_prefixes."""
        ctx = subject_sidebar_context(rf.get('/number-puzzles/'))
        assert ctx['subject_sidebar'] == 'maths'
        assert ctx['current_subject_slug'] == 'mathematics'

    def test_coding_prefix_maps_to_coding_sidebar(self, rf, coding_subject):
        ctx = subject_sidebar_context(rf.get('/coding/python/'))
        assert ctx['subject_sidebar'] == 'coding'
        assert ctx['current_subject_slug'] == 'coding'

    def test_music_prefix_falls_through_to_legacy_branch(self, rf):
        """No MusicPlugin yet — legacy lookup keeps /music/ working."""
        ctx = subject_sidebar_context(rf.get('/music/'))
        # Legacy branch sets subject_sidebar='music' even without a Subject row
        assert ctx['subject_sidebar'] == 'music'
        assert ctx['current_subject_slug'] == 'music'

    def test_science_prefix_falls_through_to_legacy_branch(self, rf):
        ctx = subject_sidebar_context(rf.get('/science/'))
        assert ctx['subject_sidebar'] == 'science'
        assert ctx['current_subject_slug'] == 'science'

    def test_non_subject_path_returns_empty(self, rf):
        ctx = subject_sidebar_context(rf.get('/hub/'))
        assert 'subject_sidebar' not in ctx

    def test_accounts_path_returns_empty(self, rf):
        ctx = subject_sidebar_context(rf.get('/accounts/profile/'))
        assert 'subject_sidebar' not in ctx

    def test_current_subject_id_set_when_global_subject_exists(self, rf, coding_subject):
        ctx = subject_sidebar_context(rf.get('/coding/'))
        assert ctx['current_subject_id'] == coding_subject.pk
