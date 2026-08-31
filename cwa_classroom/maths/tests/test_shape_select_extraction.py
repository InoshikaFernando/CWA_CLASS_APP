"""Tracing an extracted "colour all the triangles" scene into a shape_spec.

The classifier is asked for ONE thing on these questions — which kind of shape
to colour — and never for the geometry. Vertex lists read off a picture and
written into a JSON tool call are exactly what the contour detection in
``maths.shape_detect`` does better, and a shape whose outline is a few pixels
wrong is one the student cannot colour correctly.

So the scene is cropped like any other figure and traced afterwards. This pins
that step: a real round-trip (draw known shapes → trace them back), and every
way it can fail landing the question with the teacher rather than importing one
nobody can answer.

The AI fallback is never called for real — the synthetic sheets are the clean
line-art OpenCV was tuned for, and bulk tracing is OpenCV-only by default.
"""
import base64
import io

import pytest

from maths.geometry_grading import shape_target_ids, validate_shape_spec
from maths.shape_detect import (
    SHAPE_TRACE_ALLOW_AI_ENV,
    UNTRACEABLE_RUBRIC,
    trace_shape_select_scenes,
)


def _sheet_b64():
    """Two triangles, a square, a circle and a wide ellipse — as a PNG crop."""
    from PIL import Image, ImageDraw

    img = Image.new('RGB', (600, 400), 'white')
    d = ImageDraw.Draw(img)
    d.polygon([(60, 40), (140, 40), (100, 120)], outline='black', width=3)
    d.rectangle([(220, 40), (320, 140)], outline='black', width=3)
    d.ellipse([(400, 40), (500, 140)], outline='black', width=3)
    d.ellipse([(400, 220), (560, 300)], outline='black', width=3)
    d.polygon([(80, 220), (180, 220), (130, 320)], outline='black', width=3)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode()


def _question(**overrides):
    q = {
        'question_text': 'Colour all the triangles.',
        'question_type': 'shape_select',
        'shape_target_type': 'triangle',
        'image_ref': 'scene.png',
        'has_image': True,
        'validation_type': 'auto',
        'answers': [],
    }
    q.update(overrides)
    return q


class TestTracingASceneThatWorks:

    def test_the_scene_becomes_a_valid_spec(self):
        q = _question()
        traced, failed = trace_shape_select_scenes([q], {'scene.png': _sheet_b64()})

        assert (traced, failed) == (1, 0)
        validate_shape_spec(q['shape_spec'])
        assert q['shape_spec']['target_type'] == 'triangle'
        # Both triangles found, and they are what the answer key derives from.
        assert len(shape_target_ids(q['shape_spec'])) == 2

    def test_the_question_stays_answerable_in_the_app(self):
        q = _question()
        trace_shape_select_scenes([q], {'scene.png': _sheet_b64()})

        assert q['question_type'] == 'shape_select'
        assert q['validation_type'] == 'auto'
        assert q['answers'] == []

    def test_the_raster_stops_being_the_figure(self):
        """The app redraws the traced scene, so the crop is no longer the
        figure — but the ref is kept so the review page can show a teacher what
        was traced."""
        q = _question()
        trace_shape_select_scenes([q], {'scene.png': _sheet_b64()})

        assert q['has_image'] is False
        assert q['image_ref'] == 'scene.png'

    def test_a_different_target_picks_different_shapes(self):
        q = _question(shape_target_type='circle',
                      question_text='Colour all the circles.')
        traced, _ = trace_shape_select_scenes([q], {'scene.png': _sheet_b64()})

        assert traced == 1
        assert q['shape_spec']['target_type'] == 'circle'
        assert len(shape_target_ids(q['shape_spec'])) == 1

    def test_other_question_types_are_left_alone(self):
        other = {'question_type': 'short_answer', 'question_text': '2 + 2?'}
        traced, failed = trace_shape_select_scenes(
            [other], {'scene.png': _sheet_b64()})

        assert (traced, failed) == (0, 0)
        assert other == {'question_type': 'short_answer', 'question_text': '2 + 2?'}


class TestASceneThatCannotBeTraced:
    """Every failure goes to the teacher — never an unanswerable import."""

    @pytest.mark.parametrize('q,images,why', [
        (_question(image_ref=None), {}, 'no crop'),
        (_question(), {}, 'crop missing from the pool'),
        (_question(shape_target_type='hexagon'), {'scene.png': ''}, 'unknown target'),
        (_question(shape_target_type=''), {'scene.png': ''}, 'no target'),
        (_question(), {'scene.png': 'not-base64!!'}, 'unreadable image'),
    ])
    def test_it_is_routed_to_the_teacher(self, q, images, why):
        traced, failed = trace_shape_select_scenes([q], images)

        assert (traced, failed) == (0, 1), why
        assert q['question_type'] == 'extended_answer'
        assert q['validation_type'] == 'human_graded'
        assert q['grading_rubric'] == UNTRACEABLE_RUBRIC
        # Flagged, and unticked so the teacher opts in rather than out.
        assert q['needs_review'] is True
        assert q['include'] is False

    def test_a_sheet_with_no_shape_of_the_target_type_is_not_answerable(self):
        """Nothing to colour is not a question — it must not import as one."""
        from PIL import Image, ImageDraw

        img = Image.new('RGB', (400, 300), 'white')
        ImageDraw.Draw(img).ellipse([(100, 80), (300, 220)], outline='black', width=3)
        buf = io.BytesIO()
        img.save(buf, format='PNG')

        q = _question()   # asks for triangles; the sheet has only a circle
        traced, failed = trace_shape_select_scenes(
            [q], {'scene.png': base64.b64encode(buf.getvalue()).decode()})

        assert (traced, failed) == (0, 1)
        assert q['validation_type'] == 'human_graded'

    def test_a_rubric_the_model_wrote_is_not_overwritten(self):
        q = _question(grading_rubric='Look for four triangles.')
        trace_shape_select_scenes([q], {})

        assert q['grading_rubric'] == 'Look for four triangles.'


class TestTheAIFallbackIsOffByDefault:
    """It costs a vision call per scene, and a worksheet's shapes are the clean
    line-art OpenCV was tuned for."""

    def test_bulk_tracing_does_not_reach_for_the_model(self, monkeypatch):
        import maths.shape_detect as sd

        monkeypatch.delenv(SHAPE_TRACE_ALLOW_AI_ENV, raising=False)
        called = []
        monkeypatch.setattr(sd, 'detect_shapes_ai',
                            lambda *a, **k: called.append(1) or [])

        # A sheet with no triangle is exactly when the fallback would fire.
        from PIL import Image, ImageDraw
        img = Image.new('RGB', (400, 300), 'white')
        ImageDraw.Draw(img).ellipse([(100, 80), (300, 220)], outline='black', width=3)
        buf = io.BytesIO()
        img.save(buf, format='PNG')

        trace_shape_select_scenes(
            [_question()], {'scene.png': base64.b64encode(buf.getvalue()).decode()})

        assert called == []

    def test_it_can_be_switched_on(self, monkeypatch):
        monkeypatch.setenv(SHAPE_TRACE_ALLOW_AI_ENV, '1')
        from maths.shape_detect import _trace_ai_allowed
        assert _trace_ai_allowed() is True
