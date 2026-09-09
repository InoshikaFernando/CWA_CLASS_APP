"""Playwright UI test — upload a homework PDF, review it, press Continue.

The bug this covers is the one a teacher reported and no unit test caught: after
uploading a workbook and reviewing the extracted questions, pressing
"Continue to Confirm" came back on the same URL showing Django's bare
``Bad Request (400)`` (prod session 134). Nothing reached the view — the review
form posted every one of its nine structured-spec panels for every question,
and a long workbook crossed Django's request-parser field ceiling while
``CsrfViewMiddleware`` was reading ``request.POST``.

So this drives the real journey in a browser — pick a PDF, submit the upload
form, land on the review page, press Continue — rather than requesting the
review URL directly, because the failure was in what the *rendered form*
submits, which only a browser builds.

The AI call and the RQ worker are the two things stubbed: extraction runs inline
against a canned classification result, so the flow is real from the upload form
onwards without needing Claude or Redis.
"""
from __future__ import annotations

from unittest import mock

import pytest
from playwright.sync_api import Page, expect

from ..conftest import do_login


# One question of each shape the review page renders a spec panel for, plus
# plain ones — the mix that made every card carry all nine panels.
_TYPES = [
    'short_answer', 'multiple_choice', 'long_division', 'column_operation',
    'plot_points', 'read_graph', 'measure', 'number_line', 'table_of_values',
    'sketch_graph', 'prime_factorization', 'extended_answer',
]

# Enough questions that the old form's ~29 parts each would cross
# DATA_UPLOAD_MAX_NUMBER_FIELDS (20000) on submit, and the new form's ~13 do not.
QUESTION_COUNT = 720


def _pdf_bytes() -> bytes:
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=300, height=400)
    page.insert_text((40, 60), "Term 3 workbook")
    data = doc.tobytes()
    doc.close()
    return data


def _question(index):
    question_type = _TYPES[index % len(_TYPES)]
    question = {
        'question_text': f'Question {index + 1}',
        'question_type': question_type,
        'explanation': 'Work it out step by step.',
        'validation_type': 'auto',
        'grading_rubric': '',
        'difficulty': 2,
        'points': 1,
        'include': True,
        'answers': [{'text': 'a', 'is_correct': True}, {'text': 'b', 'is_correct': False}],
    }
    if question_type == 'long_division':
        question.update(dividend=611, divisor=47)
    elif question_type == 'column_operation':
        question.update(operands=[23, 25], operator='+')
    elif question_type == 'plot_points':
        question['plane_spec'] = {'bounds': {'xmin': -5, 'xmax': 5, 'ymin': -5, 'ymax': 5},
                                  'mode': 'points', 'target': {'points': [[3, -2]]}}
    elif question_type == 'read_graph':
        question.update(numeric_answer='130', answer_tolerance='5', answer_unit='km')
    elif question_type == 'measure':
        question.update(numeric_answer='135', answer_tolerance='2', answer_unit='°')
    elif question_type == 'number_line':
        question['number_line_spec'] = {'min': 0, 'max': 10, 'step': 1,
                                        'mode': 'mark', 'target': [4]}
    elif question_type == 'table_of_values':
        question['table_spec'] = {'headers': ['a', 'b'],
                                  'rows': [[{'given': '1'}, {'answer': '2'}]],
                                  'tolerance': 0}
    elif question_type == 'sketch_graph':
        question['sketch_spec'] = {'equation': 'y = x', 'bounds': {'xmin': -5, 'xmax': 5,
                                                                  'ymin': -5, 'ymax': 5}}
    elif question_type == 'prime_factorization':
        question['target_number'] = 60
    return question


def _canned_extraction(*args, **kwargs):
    """What the AI classifier would have returned, without calling it."""
    return {
        'result': {
            'year_level': 5,
            'subject': 'Mathematics',
            'strand': 'Number',
            'topic': 'Mixed',
            'questions': [_question(i) for i in range(QUESTION_COUNT)],
            'usage': {},
        },
        'extracted_images': {},
        'page_count': 1,
    }


def _run_inline(*, school, user, task_type, func, args=None, kwargs=None, **_ignored):
    """Stand in for enqueue_task: run the job now, in-process, no Redis."""
    func(*(args or []), **(kwargs or {}))
    return None, None


class TestReviewContinue:

    @pytest.mark.django_db(transaction=True)
    def test_upload_review_and_continue_reaches_the_confirm_step(
        self, page: Page, live_server, school, teacher_user, tmp_path
    ):
        pdf_path = tmp_path / "workbook.pdf"
        pdf_path.write_bytes(_pdf_bytes())

        do_login(page, str(live_server), teacher_user)

        with mock.patch('taskqueue.services.enqueue_task', _run_inline), \
             mock.patch('worksheets.services.extract_and_classify_worksheet',
                        _canned_extraction), \
             mock.patch('billing.page_quota.check_page_budget',
                        return_value=(True, '', None)):
            page.goto(f"{live_server}/homework/pdf/upload/")
            page.wait_for_load_state("domcontentloaded")
            page.set_input_files('input[name="pdf_file"]', str(pdf_path))
            page.click('#submit-btn')

            # Upload → processing → review. The worker ran inline, so the
            # processing page redirects straight through.
            page.wait_for_url("**/homework/pdf/preview/**", timeout=30_000)
            expect(page.locator('#preview-form')).to_be_attached()
            expect(page.locator('textarea[name="q_0_text"]')).to_be_attached()

            # The teacher reviews, then continues. This is the click that used
            # to come back as "Bad Request (400)" on this same URL.
            page.click('button[type="submit"]:has-text("Continue to Confirm")')
            page.wait_for_url("**/homework/pdf/confirm/**", timeout=30_000)

        body = page.locator('body').inner_text()
        assert 'Bad Request' not in body, body[:400]
        # The confirm step really rendered, with every question carried over.
        expect(page.get_by_text('Questions included')).to_be_visible()
        assert str(QUESTION_COUNT) in body, body[:400]

    @pytest.mark.django_db(transaction=True)
    def test_a_structured_question_still_posts_its_own_spec(
        self, page: Page, live_server, school, teacher_user
    ):
        """The panels are disabled, not removed: switching a question's type in
        the browser must enable that type's fields so the edit still saves."""
        from homework.models import HomeworkUploadSession

        session = HomeworkUploadSession.objects.create(
            user=teacher_user, school=school, pdf_filename="w.pdf",
            homework_title="Switching types",
            status=HomeworkUploadSession.STATUS_DONE, is_confirmed=False,
            extracted_data={
                'year_level': 5, 'subject': 'Mathematics', 'topic': 'Mixed',
                'questions': [{'question_text': 'How many?', 'include': True,
                               'question_type': 'short_answer', 'answers': []}],
            },
            extracted_images={},
        )
        do_login(page, str(live_server), teacher_user)
        page.goto(f"{live_server}/homework/pdf/preview/{session.pk}/")
        page.wait_for_load_state("domcontentloaded")

        # A short answer posts no spec fields — the panel is there but disabled.
        table_spec = page.locator('textarea[name="q_0_table_spec"]')
        expect(table_spec).to_be_disabled()

        page.select_option('select[name="q_0_type"]', 'table_of_values')
        expect(table_spec).to_be_enabled()
        table_spec.fill('{"headers": ["a", "b"], '
                        '"rows": [[{"given": "1"}, {"answer": "2"}]], "tolerance": 0}')

        page.click('button[type="submit"]:has-text("Continue to Confirm")')
        page.wait_for_url("**/homework/pdf/confirm/**", timeout=30_000)

        session.refresh_from_db()
        saved = session.extracted_data['questions'][0]
        assert saved['question_type'] == 'table_of_values'
        assert saved['table_spec']['rows'][0][1]['answer'] == '2'
