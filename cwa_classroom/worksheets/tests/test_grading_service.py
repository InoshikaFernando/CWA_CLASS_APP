"""
Unit tests for worksheets/grading_service.py

Covers:
  - _parse_cache_feedback: plain text and JSON variants
  - _store_cache / _lookup_cache: round-trip including what_was_correct / what_to_add
  - grade_extended_answer: is_partial flag, quota exceeded path, cache hit path
  - _call_claude_grade: partial credit returned correctly (mocked API)

All DB tests use @pytest.mark.django_db.
"""
import json
import pytest
from unittest.mock import MagicMock, patch

from worksheets.grading_service import (
    _parse_cache_feedback,
    _normalise,
    grade_extended_answer,
)


# ---------------------------------------------------------------------------
# _parse_cache_feedback
# ---------------------------------------------------------------------------

class TestParseCacheFeedback:
    def test_plain_text_returns_feedback_only(self):
        result = _parse_cache_feedback('Your proof is incomplete.')
        assert result['feedback'] == 'Your proof is incomplete.'
        assert result['what_was_correct'] == ''
        assert result['what_to_add'] == ''

    def test_json_with_all_fields(self):
        raw = json.dumps({
            'feedback': 'Partially correct.',
            'what_was_correct': 'Mentioned gravity.',
            'what_to_add': 'Add inverse square law.',
        })
        result = _parse_cache_feedback(raw)
        assert result['feedback'] == 'Partially correct.'
        assert result['what_was_correct'] == 'Mentioned gravity.'
        assert result['what_to_add'] == 'Add inverse square law.'

    def test_json_without_structured_fields_returns_feedback(self):
        raw = json.dumps({'feedback': 'Great work!'})
        result = _parse_cache_feedback(raw)
        assert result['feedback'] == 'Great work!'
        assert result['what_was_correct'] == ''
        assert result['what_to_add'] == ''

    def test_invalid_json_returns_plain_text(self):
        raw = 'not json at all'
        result = _parse_cache_feedback(raw)
        assert result['feedback'] == 'not json at all'

    def test_json_array_treated_as_plain_text(self):
        raw = '["a", "b"]'
        result = _parse_cache_feedback(raw)
        assert result['feedback'] == raw


# ---------------------------------------------------------------------------
# Cache round-trip tests (require DB + homework.AIGradingCache model)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCacheRoundTrip:

    def _make_question(self):
        """Create a minimal maths.Question for cache FK."""
        from classroom.models import Level, Subject, Topic
        from maths.models import Question
        subject = Subject.objects.get_or_create(slug='mathematics', school=None, defaults={'name': 'Mathematics'})[0]
        level = Level.objects.get_or_create(level_number=7, defaults={'display_name': 'Year 7'})[0]
        topic = Topic.objects.get_or_create(name='Algebra GS', subject=subject, defaults={'slug': 'algebra-gs', 'is_active': True})[0]
        return Question.objects.create(
            question_text='Define gravity.',
            question_type='extended_answer',
            topic=topic,
            level=level,
        )

    def test_store_and_retrieve_structured_feedback(self):
        """Storing a result with what_was_correct/what_to_add round-trips correctly."""
        from worksheets.grading_service import _store_cache, _lookup_cache
        q = self._make_question()
        normalised = 'gravity pulls objects together'
        result = {
            'is_correct': False,
            'score_fraction': 0.3,
            'feedback': 'Partially correct.',
            'what_was_correct': 'Mentioned attraction correctly.',
            'what_to_add': 'Add mass and distance relationship.',
        }
        _store_cache(q.pk, normalised, result)

        cached = _lookup_cache(q.pk, normalised, threshold=0.85)
        assert cached is not None
        assert cached['is_correct'] is False
        assert cached['score_fraction'] == pytest.approx(0.3)
        assert cached['feedback'] == 'Partially correct.'
        assert cached['what_was_correct'] == 'Mentioned attraction correctly.'
        assert cached['what_to_add'] == 'Add mass and distance relationship.'
        assert cached['is_partial'] is True

    def test_store_plain_feedback_no_structured_fields(self):
        """Old-format entries (plain text feedback) still parse without error."""
        from worksheets.grading_service import _store_cache, _lookup_cache
        q = self._make_question()
        normalised = 'the apple falls down'
        result = {
            'is_correct': True,
            'score_fraction': 1.0,
            'feedback': 'Correct!',
            # No what_was_correct / what_to_add
        }
        _store_cache(q.pk, normalised, result)

        cached = _lookup_cache(q.pk, normalised, threshold=0.85)
        assert cached is not None
        assert cached['is_correct'] is True
        assert cached['what_was_correct'] == ''
        assert cached['what_to_add'] == ''
        assert cached['is_partial'] is False

    def test_lookup_returns_is_partial_true_for_score_0_3(self):
        """Cache hit at score 0.3 returns is_partial=True."""
        from worksheets.grading_service import _store_cache, _lookup_cache
        q = self._make_question()
        normalised = 'partial answer text'
        _store_cache(q.pk, normalised, {
            'is_correct': False,
            'score_fraction': 0.3,
            'feedback': 'Some credit.',
            'what_was_correct': '',
            'what_to_add': '',
        })
        cached = _lookup_cache(q.pk, normalised)
        assert cached['is_partial'] is True

    def test_lookup_returns_is_partial_false_for_score_1_0(self):
        from worksheets.grading_service import _store_cache, _lookup_cache
        q = self._make_question()
        normalised = 'perfect answer'
        _store_cache(q.pk, normalised, {
            'is_correct': True,
            'score_fraction': 1.0,
            'feedback': 'Full marks.',
            'what_was_correct': 'Everything.',
            'what_to_add': 'Nothing.',
        })
        cached = _lookup_cache(q.pk, normalised)
        assert cached['is_partial'] is False


# ---------------------------------------------------------------------------
# grade_extended_answer — mocked API calls
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestGradeExtendedAnswer:

    def _make_question(self):
        from classroom.models import Level, Subject, Topic
        from maths.models import Question
        subject = Subject.objects.get_or_create(slug='mathematics', school=None, defaults={'name': 'Mathematics'})[0]
        level = Level.objects.get_or_create(level_number=8, defaults={'display_name': 'Year 8'})[0]
        topic = Topic.objects.get_or_create(name='Geometry GEA', subject=subject, defaults={'slug': 'geometry-gea', 'is_active': True})[0]
        return Question.objects.create(
            question_text='Explain Newton\'s first law.',
            question_type='extended_answer',
            topic=topic,
            level=level,
        )

    @patch('worksheets.grading_service._call_claude_grade')
    def test_grade_returns_is_partial_true_for_score_0_3(self, mock_claude):
        mock_claude.return_value = {
            'is_correct': False,
            'is_partial': True,
            'score_fraction': 0.3,
            'feedback': 'Partially correct.',
            'what_was_correct': 'Object at rest stays at rest.',
            'what_to_add': 'Mention net force and inertia.',
            'cache_hit': False,
            'input_tokens': 300,
            'output_tokens': 80,
        }
        q = self._make_question()
        result = grade_extended_answer(q, 'An object at rest stays at rest.')
        assert result['is_partial'] is True
        assert result['is_correct'] is False
        assert result['what_was_correct'] == 'Object at rest stays at rest.'
        assert result['what_to_add'] == 'Mention net force and inertia.'

    @patch('worksheets.grading_service._call_claude_grade')
    def test_grade_returns_is_partial_false_for_correct(self, mock_claude):
        mock_claude.return_value = {
            'is_correct': True,
            'is_partial': False,
            'score_fraction': 0.95,
            'feedback': 'Excellent.',
            'what_was_correct': 'Everything.',
            'what_to_add': 'Nothing.',
            'cache_hit': False,
            'input_tokens': 300,
            'output_tokens': 60,
        }
        q = self._make_question()
        result = grade_extended_answer(q, 'A full and correct answer.')
        assert result['is_partial'] is False
        assert result['is_correct'] is True

    @patch('worksheets.grading_service._call_claude_grade')
    def test_grade_cache_miss_stores_and_retrieves(self, mock_claude):
        """After a cache miss, the result is stored; second call hits cache."""
        mock_claude.return_value = {
            'is_correct': False,
            'is_partial': True,
            'score_fraction': 0.3,
            'feedback': 'Partially correct.',
            'what_was_correct': 'Some correct.',
            'what_to_add': 'Add more.',
            'cache_hit': False,
            'input_tokens': 300,
            'output_tokens': 80,
        }
        q = self._make_question()
        answer_text = 'An object at rest stays at rest unless acted on.'
        grade_extended_answer(q, answer_text)
        assert mock_claude.call_count == 1

        # Second call with same text → cache hit, Claude not called again
        result2 = grade_extended_answer(q, answer_text)
        assert mock_claude.call_count == 1  # still 1
        assert result2['cache_hit'] is True
        assert result2['is_partial'] is True

    def test_quota_exceeded_returns_pending_flag(self):
        """When school quota is exceeded, returns quota_exceeded=True without calling Claude."""
        q = self._make_question()
        mock_school = MagicMock()
        mock_school.free_ai_grading = False

        with patch('worksheets.grading_service.check_ai_grading_quota') as mock_quota:
            mock_quota.return_value = (False, 50, 50)
            result = grade_extended_answer(q, 'Some answer', school=mock_school)

        assert result['quota_exceeded'] is True
        assert result['is_correct'] is False
