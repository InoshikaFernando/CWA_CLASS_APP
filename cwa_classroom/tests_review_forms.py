"""Every review page must post only the fields the card is editing.

Three pages let a teacher review AI-extracted questions before importing them —
homework PDF upload, worksheet PDF upload, and AI import. They share the
extractor, the question-type list, the crop modal and, historically, each
other's bugs.

Two of them shipped the same one: the card renders every structured-spec panel
(long division, prime factorisation, column arithmetic, plane, graph, measure,
number line, table, sketch) hidden so the type dropdown can reveal one without
a reload — and a browser posts every ENABLED field, shown or not. At ~29 and
~28 fields per question a long upload crossed
``settings.DATA_UPLOAD_MAX_NUMBER_FIELDS`` inside Django's request parser,
before any view ran, and the submit came back as a bare "Bad Request (400)"
with the teacher still on the review page. Nothing went red; the ceiling was
raised twice before the shape of the form was the thing that got fixed.

Each page has its own rendered budget test (they measure what a browser really
submits, which is the honest check):

    homework/tests_preview_form_size.py
    ai_import/tests/tests_preview_form_size.py
    worksheets/tests/tests_preview_form_size.py

Those are path-filtered onto their apps. This file is the net around all three:
it is static, needs no database, and runs in the ungated migration-check job,
so a fourth review page — or a spec field added to a page that had none —
fails here even on a PR that touches nothing else.
"""
import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent
TEMPLATE_DIRS = [PROJECT_ROOT / 'templates', PROJECT_ROOT / 'worksheets' / 'templates']

# A per-question form field: name="q_<something templated>_<field>".
PER_QUESTION_FIELD = re.compile(r'name="q_\{\{[^}]*\}\}_([a-z0-9_]+)"')

# The review pages, and the budget suite that measures each one. Keyed by the
# template path relative to cwa_classroom/.
REVIEW_PAGES = {
    'templates/homework/upload_preview.html':
        'homework/tests_preview_form_size.py',
    'templates/ai_import/preview.html':
        'ai_import/tests/tests_preview_form_size.py',
    'templates/worksheets/preview.html':
        'worksheets/tests/tests_preview_form_size.py',
}

# Fields that belong to one question type's structured-spec panel. A card must
# post these only when that type is the question's own — every other panel is
# rendered disabled, which is what keeps the field count per question flat.
SPEC_FIELDS = {
    'dividend', 'divisor',
    'operands', 'operator',
    'target_number',
    'plane_spec', 'graph_spec', 'number_line_spec', 'table_spec', 'sketch_spec',
    'numeric_answer', 'answer_tolerance', 'answer_unit',
    'measure_numeric_answer', 'measure_answer_tolerance', 'measure_answer_unit',
}


def _templates_with_per_question_fields():
    found = []
    for root in TEMPLATE_DIRS:
        if not root.exists():
            continue
        for path in sorted(root.rglob('*.html')):
            text = path.read_text(encoding='utf-8')
            if PER_QUESTION_FIELD.search(text):
                found.append(str(path.relative_to(PROJECT_ROOT)))
    return found


def test_every_review_page_is_covered_by_a_budget_suite():
    """A new review page must be measured, not assumed.

    The two pages that 400'd were each found by a teacher, not by CI. Anything
    that posts a block of fields per question is the same shape and needs the
    same guard, so a new one fails here until it has a budget test.
    """
    found = set(_templates_with_per_question_fields())
    known = set(REVIEW_PAGES)

    unlisted = sorted(found - known)
    assert not unlisted, (
        'These templates post a block of form fields per question, the shape '
        'that returned a bare "Bad Request (400)" on submit twice:\n  '
        + '\n  '.join(unlisted)
        + '\n\nAdd each to REVIEW_PAGES here, and give it a rendered '
          'fields-per-question budget test like the ones it names.'
    )

    missing = sorted(known - found)
    assert not missing, (
        'REVIEW_PAGES names templates that no longer post per-question fields '
        '(moved or renamed?):\n  ' + '\n  '.join(missing)
    )


@pytest.mark.parametrize('template', sorted(REVIEW_PAGES))
def test_its_budget_suite_exists(template):
    suite = PROJECT_ROOT / REVIEW_PAGES[template]
    assert suite.exists(), (
        f'{template} has no budget suite at {REVIEW_PAGES[template]} — without '
        f'one, nothing measures what its form posts per question.'
    )


@pytest.mark.parametrize('template', sorted(REVIEW_PAGES))
def test_no_spec_field_posts_unconditionally(template):
    """A spec field must carry a condition that disables it off its own type.

    Checked in the markup rather than by rendering, because this has to hold
    for a page that has no fixtures yet. The condition itself is what the
    rendered budget suites verify actually works.
    """
    text = (PROJECT_ROOT / template).read_text(encoding='utf-8')

    offenders = []
    for match in re.finditer(r'name="q_\{\{[^}]*\}\}_([a-z0-9_]+)"', text):
        field = match.group(1)
        if field not in SPEC_FIELDS:
            continue
        # The element this name sits in: from its opening '<' to the '>' that
        # closes the tag. `disabled` must be in there, under a condition.
        start = text.rfind('<', 0, match.start())
        end = text.find('>', match.end())
        element = text[start:end] if start != -1 and end != -1 else ''
        if 'disabled' not in element:
            offenders.append(field)

    assert not offenders, (
        f'{template} posts these structured-spec fields on every question, '
        f'whatever its type: {sorted(set(offenders))}.\n'
        'A browser submits every enabled field, shown or not, so each one is '
        'paid for by every question on the page and the submit 400s on a long '
        'upload. Render them {% if q.spec_panel != \'<panel>\' %}disabled'
        '{% endif %}, and toggle disabled with hidden in handleTypeChange.'
    )
