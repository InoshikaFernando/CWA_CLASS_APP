"""Tests for the shared Adjust-image view helpers (page render + re-crop).

Driven with a minimal fake session/request so the logic is covered without the
per-app auth/CBV stack (each app's view is a thin ownership-checked delegate).
"""
import base64
import json
from types import SimpleNamespace

import fitz

from worksheets.image_adjust import page_image_response, recrop_response


def _pdf():
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.draw_rect(fitz.Rect(120, 150, 280, 260), fill=(0.6, 0.6, 0.6))
    data = doc.tobytes()
    doc.close()
    return data


class _Session:
    def __init__(self, questions, pdf=True):
        self.pdf_file = _pdf() if pdf else b''
        self.extracted_data = {'questions': questions}
        self.extracted_images = {}
        self.page_count = 1
        self.saved_fields = None

    def save(self, update_fields=None):
        self.saved_fields = update_fields


def _get(page=1):
    return SimpleNamespace(GET={'page': str(page)})


def _post(payload):
    return SimpleNamespace(body=json.dumps(payload).encode('utf-8'))


def test_page_image_returns_png_and_point_dims():
    resp = page_image_response(_Session([{}]), _get(1))
    assert resp.status_code == 200
    j = json.loads(resp.content)
    assert j['page'] == 1 and round(j['page_w']) == 400 and round(j['page_h']) == 500
    assert base64.b64decode(j['image_b64'])[:8] == b'\x89PNG\r\n\x1a\n'


def test_page_image_no_pdf_errors():
    resp = page_image_response(_Session([{}], pdf=False), _get(1))
    assert resp.status_code == 400


def test_recrop_updates_question_and_stores_image():
    sess = _Session([{'question_text': 'Q', 'has_image': False, 'image_ref': None}])
    resp = recrop_response(sess, _post({'q_idx': 0, 'page': 1, 'box': [0.25, 0.25, 0.75, 0.6]}))
    assert resp.status_code == 200
    j = json.loads(resp.content)
    ref = j['ref']
    # New image stored on the session and the question repointed at it.
    assert ref in sess.extracted_images
    q = sess.extracted_data['questions'][0]
    assert q['image_ref'] == ref and q['has_image'] is True
    assert q['image_page'] == 1 and len(q['image_bbox_frac']) == 4
    assert 'extracted_images' in sess.saved_fields and 'extracted_data' in sess.saved_fields
    assert base64.b64decode(j['image_b64'])[:8] == b'\x89PNG\r\n\x1a\n'


def test_recrop_bad_index_errors():
    sess = _Session([{'question_text': 'Q'}])
    resp = recrop_response(sess, _post({'q_idx': 9, 'page': 1, 'box': [0.1, 0.1, 0.5, 0.5]}))
    assert resp.status_code == 400
    assert sess.saved_fields is None          # nothing persisted


def test_recrop_too_small_box_errors():
    sess = _Session([{'question_text': 'Q'}])
    resp = recrop_response(sess, _post({'q_idx': 0, 'page': 1, 'box': [0.5, 0.5, 0.5001, 0.5001]}))
    assert resp.status_code == 400


def test_recrop_malformed_body_errors():
    sess = _Session([{'question_text': 'Q'}])
    resp = recrop_response(sess, SimpleNamespace(body=b'not json'))
    assert resp.status_code == 400
