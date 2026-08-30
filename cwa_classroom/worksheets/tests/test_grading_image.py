"""A question's diagram either reaches the grader, or nobody is graded.

An extended answer is written against the picture beside the question. When
that picture cannot be loaded, the old code logged a warning and graded the
text on its own — so a child was marked against a diagram the grader never
saw, and neither the child nor the teacher was told. These tests pin the
replacement: a diagram that exists and cannot be read stops the grading, says
so, and is never cached as a verdict.
"""
import pytest
from unittest.mock import MagicMock, patch

from worksheets.grading_service import (
    QuestionImageUnavailable,
    _call_claude_grade,
    _fetch_image_block,
    grade_extended_answer,
)

PNG_BYTES = b'\x89PNG\r\n\x1a\n fake png body'


class _FakeFile:
    """Minimal stand-in for the file default_storage.open() returns."""

    def __init__(self, data):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._data


def _make_question(image_name=None):
    from classroom.models import Level, Subject, Topic
    from maths.models import Question
    subject = Subject.objects.get_or_create(
        slug='mathematics', school=None, defaults={'name': 'Mathematics'})[0]
    level = Level.objects.get_or_create(
        level_number=7, defaults={'display_name': 'Year 7'})[0]
    topic = Topic.objects.get_or_create(
        name='Angles IMG', subject=subject,
        defaults={'slug': 'angles-img', 'is_active': True})[0]
    q = Question.objects.create(
        question_text='Find angle x and explain your reasoning.',
        question_type='extended_answer',
        topic=topic,
        level=level,
    )
    if image_name:
        q.image = image_name
        q.save(update_fields=['image'])
    return q


@pytest.mark.django_db
class TestFetchImageBlock:

    def test_no_diagram_returns_none(self):
        """No image on the question is not a failure — grade the text."""
        assert _fetch_image_block(_make_question()) is None

    def test_png_is_base64_encoded_with_its_media_type(self):
        import base64
        q = _make_question('questions/year7/angles/x.png')
        with patch('django.core.files.storage.default_storage.open',
                   return_value=_FakeFile(PNG_BYTES)):
            block = _fetch_image_block(q)
        assert block['type'] == 'image'
        assert block['source']['media_type'] == 'image/png'
        assert base64.standard_b64decode(block['source']['data']) == PNG_BYTES

    @pytest.mark.parametrize('name,expected', [
        ('questions/a.png', 'image/png'),
        ('questions/a.JPG', 'image/jpeg'),
        ('questions/a.jpeg', 'image/jpeg'),
        ('questions/a.gif', 'image/gif'),
        ('questions/a.webp', 'image/webp'),
    ])
    def test_media_type_follows_the_extension(self, name, expected):
        q = _make_question(name)
        with patch('django.core.files.storage.default_storage.open',
                   return_value=_FakeFile(PNG_BYTES)):
            assert _fetch_image_block(q)['source']['media_type'] == expected

    def test_unsupported_format_raises_rather_than_guessing_jpeg(self):
        """An SVG used to be labelled image/jpeg and rejected by the API as a
        nameless "grading failed"; now it names itself."""
        q = _make_question('questions/year7/angles/x.svg')
        with pytest.raises(QuestionImageUnavailable) as exc:
            _fetch_image_block(q)
        assert 'x.svg' in str(exc.value)

    def test_unreadable_storage_raises(self):
        q = _make_question('questions/year7/angles/gone.png')
        with patch('django.core.files.storage.default_storage.open',
                   side_effect=IOError('NoSuchKey')):
            with pytest.raises(QuestionImageUnavailable) as exc:
                _fetch_image_block(q)
        assert 'gone.png' in str(exc.value)
        assert 'NoSuchKey' in str(exc.value)

    def test_empty_file_raises(self):
        """A zero-byte object in Spaces is a missing diagram, not a blank one."""
        q = _make_question('questions/year7/angles/empty.png')
        with patch('django.core.files.storage.default_storage.open',
                   return_value=_FakeFile(b'')):
            with pytest.raises(QuestionImageUnavailable):
                _fetch_image_block(q)


@pytest.mark.django_db
class TestGradingStopsWhenTheDiagramIsMissing:

    @patch('anthropic.Anthropic')
    def test_no_api_call_and_the_result_says_why(self, mock_anthropic):
        q = _make_question('questions/year7/angles/gone.png')
        with patch('worksheets.grading_service._fetch_image_block',
                   side_effect=QuestionImageUnavailable('could not read diagram')):
            result = _call_claude_grade(q, 'x is 40 degrees because...', 'x is 40')

        # Not graded on the text alone — the model was never asked.
        mock_anthropic.return_value.messages.create.assert_not_called()
        assert result['error']
        assert 'diagram' in result['error']
        assert 'diagram' in result['feedback'].lower()
        assert 'teacher' in result['feedback'].lower()
        # No verdict means no marks recorded against the student.
        assert result['is_correct'] is False
        assert result['is_partial'] is False
        assert result['score_fraction'] == 0.0
        assert result['input_tokens'] == 0
        assert result['output_tokens'] == 0

    @patch('worksheets.grading_service._call_claude_grade')
    def test_a_failure_is_never_cached(self, mock_claude):
        """A cached failure would be served back as 0.0 to every later student
        who wrote the same answer, without an API call to notice the fix."""
        from worksheets.grading_service import _get_cache_model
        mock_claude.return_value = {
            'is_correct': False,
            'is_partial': False,
            'score_fraction': 0.0,
            'feedback': "This question's diagram could not be loaded.",
            'what_was_correct': '',
            'what_to_add': '',
            'cache_hit': False,
            'input_tokens': 0,
            'output_tokens': 0,
            'error': 'diagram unavailable: could not read diagram',
        }
        q = _make_question('questions/year7/angles/gone.png')
        answer = 'x is 40 degrees because the angles are co-interior.'

        first = grade_extended_answer(q, answer)
        assert first['error']
        assert _get_cache_model().objects.filter(question_id=q.pk).count() == 0

        # Second attempt re-grades rather than replaying the failure.
        second = grade_extended_answer(q, answer)
        assert mock_claude.call_count == 2
        assert second['cache_hit'] is False

    @patch('worksheets.grading_service._call_claude_grade')
    def test_a_real_verdict_is_still_cached(self, mock_claude):
        """The no-cache rule is for failures only — the token saving stands."""
        from worksheets.grading_service import _get_cache_model
        mock_claude.return_value = {
            'is_correct': True,
            'is_partial': False,
            'score_fraction': 1.0,
            'feedback': 'Correct.',
            'what_was_correct': 'Everything.',
            'what_to_add': 'Nothing.',
            'cache_hit': False,
            'input_tokens': 300,
            'output_tokens': 60,
        }
        q = _make_question('questions/year7/angles/x.png')
        grade_extended_answer(q, 'Co-interior angles add to 180.')
        assert _get_cache_model().objects.filter(question_id=q.pk).count() == 1
