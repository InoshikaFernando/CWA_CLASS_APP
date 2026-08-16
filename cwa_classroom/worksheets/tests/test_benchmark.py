"""The PDF extraction bench (worksheets/benchmark.py).

The bench itself runs manually over a corpus of real papers — these are just
fast checks that it works and that its verdicts point the right way, so the tool
doesn't rot between uses. No real papers, no AI calls.
"""
import io

import fitz
from PIL import Image

from worksheets.benchmark import compare, measure_offline


def _paper(tmp_path, name='paper.pdf'):
    """A 2-page paper: a question page with an embedded photo, then an answer key.

    The embedded image matters — a real raster overlapping the crop region is
    what used to abort the process inside apply_redactions().
    """
    doc = fitz.open()

    page = doc.new_page(width=400, height=500)
    page.insert_text((50, 60), 'Questions', fontsize=20)
    page.insert_text((50, 120), '1. What shape is this?', fontsize=11)
    buf = io.BytesIO()
    Image.new('RGB', (120, 90), (90, 140, 200)).save(buf, format='PNG')
    page.insert_image(fitz.Rect(60, 140, 260, 290), stream=buf.getvalue())

    key = doc.new_page(width=400, height=500)
    key.insert_text((50, 60), '\n'.join(
        f'{n}\n{chr(65 + n % 4)}\nbecause of reasons {n}' for n in range(1, 8)),
        fontsize=10)

    path = tmp_path / name
    doc.save(str(path))
    doc.close()
    return path


def test_offline_run_measures_a_paper_without_touching_the_ai(tmp_path):
    result = measure_offline(_paper(tmp_path))

    assert result['errors'] == []
    assert result['pages'] == 2
    assert result['figures_found'] >= 1
    assert result['images_rendered'] >= 1          # the crop path really ran
    assert result['key_rows'] >= 5                 # the answer key was read
    assert [s['reason'] for s in result['skipped']] == ['answer_key']
    assert result['pages_classified'] == 1
    assert result['ai_calls'] == 1


def test_a_broken_pdf_is_reported_not_raised(tmp_path):
    """One bad paper must not take the rest of the corpus down with it."""
    broken = tmp_path / 'broken.pdf'
    broken.write_bytes(b'%PDF-1.4 this is not really a pdf')

    result = measure_offline(broken)

    assert result['errors']
    assert result['mode'] == 'offline'


# --- verdicts ----------------------------------------------------------------

def _compare_one(metric, before, after):
    rows = compare({'p.pdf': {metric: before}}, {'p.pdf': {metric: after}})
    return rows[0][4] if rows else 'unchanged'


def test_losing_a_rendered_image_is_a_regression():
    assert _compare_one('images_rendered', 39, 30) == 'worse'
    assert _compare_one('images_rendered', 30, 39) == 'better'


def test_reading_more_of_the_answer_key_is_an_improvement():
    assert _compare_one('key_rows', 0, 50) == 'better'


def test_more_answers_matching_the_key_is_an_improvement():
    assert _compare_one('answer_accuracy_pct', 82.0, 94.0) == 'better'


def test_costing_more_to_classify_is_a_regression():
    assert _compare_one('ai_calls', 5, 6) == 'worse'
    assert _compare_one('cost_usd', 0.4, 0.2) == 'better'


def test_timings_and_page_counts_have_no_direction():
    """The machine moves these; calling them better or worse would be noise."""
    assert _compare_one('extract_s', 3.3, 3.9) == 'changed'
    assert _compare_one('pages_classified', 19, 24) == 'changed'


def test_skipping_a_different_number_of_pages_is_flagged_but_not_judged():
    rows = compare(
        {'p.pdf': {'skipped': [{'page': 1, 'reason': 'answer_sheet'}]}},
        {'p.pdf': {'skipped': []}},
    )
    assert rows == [('p.pdf', 'skipped', 1, 0, 'changed')]


def test_a_new_error_is_always_a_regression():
    rows = compare({'p.pdf': {'errors': []}}, {'p.pdf': {'errors': ['boom']}})
    assert rows == [('p.pdf', 'errors', 0, 1, 'worse')]


def test_an_unchanged_run_reports_nothing():
    report = {'p.pdf': {'images_rendered': 39, 'key_rows': 50, 'errors': []}}
    assert compare(report, report) == []


def test_a_paper_added_to_the_corpus_is_called_out():
    rows = compare({}, {'new.pdf': {'images_rendered': 3}})
    assert rows == [('new.pdf', '(new paper)', None, None, 'changed')]
