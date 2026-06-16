"""Tests for image → shape_spec detection (OpenCV + AI fallback).

The OpenCV backend is exercised on synthetic images drawn with Pillow (a
deterministic round-trip: draw known shapes → detect them back). The AI backend
is never called for real — its parsing is unit-tested on a stub response and its
fallback wiring is tested by monkeypatching, so the suite spends zero tokens.
"""
import io

import pytest

from maths.geometry_grading import shape_target_ids, validate_shape_spec


def _img(draw_fn, size=(600, 400)):
    from PIL import Image, ImageDraw

    img = Image.new('RGB', size, 'white')
    draw_fn(ImageDraw.Draw(img))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _mixed_sheet():
    def draw(d):
        d.polygon([(60, 40), (140, 40), (100, 120)], outline='black', width=3)   # triangle
        d.rectangle([(220, 40), (320, 140)], outline='black', width=3)           # square
        d.ellipse([(400, 40), (500, 140)], outline='black', width=3)             # circle
        d.polygon([(80, 220), (180, 220), (130, 320)], outline='black', width=3)  # triangle
    return _img(draw)


def _circle_only():
    return _img(lambda d: d.ellipse([(250, 150), (350, 250)], outline='black', width=3))


# ── OpenCV backend (real detection on synthetic images) ──────────────────

def test_opencv_detects_shape_types():
    from maths.shape_detect import detect_shapes_opencv

    w, h, shapes = detect_shapes_opencv(_mixed_sheet())
    assert (w, h) == (600, 400)
    types = [s['type'] for s in shapes]
    assert types.count('triangle') == 2
    assert any(s['type'] == 'circle' for s in shapes)
    assert any(s['type'] in ('square', 'rectangle') for s in shapes)


def test_build_spec_opencv_backend():
    from maths.shape_detect import build_shape_spec_from_image

    spec, backend = build_shape_spec_from_image(_mixed_sheet(), 'triangle', allow_ai=False)
    assert backend == 'opencv'
    validate_shape_spec(spec)
    assert len(shape_target_ids(spec)) == 2
    assert all(s['id'] == f's{i}' for i, s in enumerate(spec['shapes']))   # stable ids


def test_build_spec_raises_when_no_target_and_no_ai():
    from maths.shape_detect import build_shape_spec_from_image

    # No triangle in the image and AI disabled → unanswerable → ValueError.
    with pytest.raises(ValueError):
        build_shape_spec_from_image(_circle_only(), 'triangle', allow_ai=False)


# ── AI backend (no live calls) ───────────────────────────────────────────

def test_ai_response_parsing_drops_bad_shapes():
    from types import SimpleNamespace

    from maths.shape_detect import _shapes_from_ai_response

    block = SimpleNamespace(type='tool_use', input={'shapes': [
        {'type': 'triangle', 'points': [[0.1, 0.1], [0.2, 0.1], [0.15, 0.3]]},
        {'type': 'bogus', 'points': [[0, 0], [1, 1], [2, 2]]},   # unknown type → dropped
        {'type': 'circle', 'points': [[0.5, 0.4]]},              # < 3 points → dropped
    ]})
    resp = SimpleNamespace(content=[block])
    shapes = _shapes_from_ai_response(resp, 100, 200)
    assert len(shapes) == 1
    assert shapes[0]['type'] == 'triangle'
    assert shapes[0]['points'][0] == [10.0, 20.0]   # scaled to pixels


def test_ai_fallback_used_when_opencv_finds_no_target(monkeypatch):
    import maths.shape_detect as sd

    def fake_ai(image_bytes, w, h, **kw):
        return [{'type': 'triangle', 'points': [[10, 10], [50, 10], [30, 50]]}]

    monkeypatch.setattr(sd, 'detect_shapes_ai', fake_ai)
    spec, backend = sd.build_shape_spec_from_image(_circle_only(), 'triangle', allow_ai=True)
    assert backend == 'ai'
    assert any(s['type'] == 'triangle' for s in spec['shapes'])


# ── management command (DB) ──────────────────────────────────────────────

@pytest.mark.django_db
def test_import_command_creates_question(tmp_path):
    from django.core.management import call_command

    from classroom.models import Level
    from maths.models import Question

    Level.objects.get_or_create(level_number=970, defaults={'display_name': 'cmd fixture'})
    p = tmp_path / 'sheet.png'
    p.write_bytes(_mixed_sheet())

    call_command('import_shape_image', '--image', str(p),
                 '--target', 'triangle', '--level', '970', '--no-ai')

    q = Question.objects.filter(question_type='shape_select').order_by('-id').first()
    assert q is not None
    assert q.shape_spec['target_type'] == 'triangle'
    assert len(shape_target_ids(q.shape_spec)) == 2
