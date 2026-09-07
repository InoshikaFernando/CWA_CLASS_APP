"""Print-dialog page selection for PDF uploads.

The parser is pure, so it's tested exhaustively here; the pipeline tests below
prove that a selection really does keep excluded pages out of the AI call and
that absolute page numbers survive a partial extraction.
"""
from unittest.mock import patch

import pytest
from django.test import TestCase

from worksheets import services
from worksheets.page_selection import (
    MAX_SPEC_LENGTH, PageSelectionError, clean_upload_selection,
    describe_page_selection, excluded_pages, format_page_list,
    parse_page_selection, pdf_page_count, selection_summary,
)


def _pdf_bytes(page_count, text_prefix='Question'):
    """A minimal multi-page PDF whose pages are individually identifiable."""
    import fitz

    doc = fitz.open()
    for index in range(page_count):
        page = doc.new_page(width=300, height=400)
        page.insert_text((40, 60), f'{text_prefix} on page {index + 1}')
    data = doc.tobytes()
    doc.close()
    return data


# ---------------------------------------------------------------------------
# parse_page_selection
# ---------------------------------------------------------------------------

class ParsePageSelectionTests(TestCase):

    def test_blank_and_all_mean_every_page(self):
        for spec in (None, '', '   ', 'all', 'ALL', ' All '):
            with self.subTest(spec=spec):
                self.assertEqual(parse_page_selection(spec, 4), [1, 2, 3, 4])

    def test_single_page(self):
        self.assertEqual(parse_page_selection('3', 5), [3])

    def test_closed_range(self):
        self.assertEqual(parse_page_selection('2-4', 10), [2, 3, 4])

    def test_open_ended_range_runs_to_the_last_page(self):
        """"2-" is how a teacher skips a cover / instruction sheet."""
        self.assertEqual(parse_page_selection('2-', 5), [2, 3, 4, 5])

    def test_leading_dash_range_starts_at_page_one(self):
        """"-8" is how a teacher drops a marking scheme off the back."""
        self.assertEqual(parse_page_selection('-3', 6), [1, 2, 3])

    def test_mixed_tokens_are_merged_sorted_and_deduplicated(self):
        self.assertEqual(
            parse_page_selection('5, 2-4, 2, 9-', 10),
            [2, 3, 4, 5, 9, 10],
        )

    def test_separators_are_forgiving(self):
        for spec in ('2-4, 7', '2-4,7', '2-4 7', '2-4;7', '  2 - 4 ,  7  '):
            with self.subTest(spec=spec):
                self.assertEqual(parse_page_selection(spec, 8), [2, 3, 4, 7])

    def test_pasted_en_and_em_dashes_are_accepted(self):
        """Copying "2–7" out of a document shouldn't be an error."""
        for spec in ('2–4', '2—4', '2−4', '2‑4'):
            with self.subTest(spec=spec):
                self.assertEqual(parse_page_selection(spec, 6), [2, 3, 4])

    def test_whole_document_range_is_allowed(self):
        self.assertEqual(parse_page_selection('1-3', 3), [1, 2, 3])

    # -- rejections ---------------------------------------------------------

    def test_page_past_the_end_is_rejected_naming_the_real_length(self):
        with self.assertRaises(PageSelectionError) as ctx:
            parse_page_selection('14', 12)
        self.assertIn('14', str(ctx.exception))
        self.assertIn('12 pages', str(ctx.exception))

    def test_range_past_the_end_is_rejected(self):
        with self.assertRaises(PageSelectionError):
            parse_page_selection('8-20', 12)

    def test_page_zero_is_rejected(self):
        with self.assertRaises(PageSelectionError) as ctx:
            parse_page_selection('0-3', 5)
        self.assertIn('numbered from 1', str(ctx.exception))

    def test_backwards_range_is_rejected_with_the_fix(self):
        with self.assertRaises(PageSelectionError) as ctx:
            parse_page_selection('7-3', 10)
        self.assertIn('3-7', str(ctx.exception))

    def test_gibberish_is_rejected_naming_the_bad_token(self):
        with self.assertRaises(PageSelectionError) as ctx:
            parse_page_selection('2-4, banana', 8)
        self.assertIn('banana', str(ctx.exception))

    def test_bare_dash_is_rejected(self):
        with self.assertRaises(PageSelectionError):
            parse_page_selection('-', 5)

    def test_overlong_spec_is_rejected_rather_than_truncated(self):
        spec = ', '.join(['1'] * 200)
        self.assertGreater(len(spec), MAX_SPEC_LENGTH)
        with self.assertRaises(PageSelectionError) as ctx:
            parse_page_selection(spec, 5)
        self.assertIn('too long', str(ctx.exception))

    def test_empty_pdf_is_rejected(self):
        with self.assertRaises(PageSelectionError):
            parse_page_selection('1', 0)


# ---------------------------------------------------------------------------
# formatting / summaries
# ---------------------------------------------------------------------------

class FormatPageListTests(TestCase):

    def test_runs_are_collapsed(self):
        self.assertEqual(format_page_list([1, 2, 3, 7]), '1-3, 7')

    def test_a_pair_is_listed_rather_than_hyphenated(self):
        """"11, 12" reads better than "11-12" for two pages."""
        self.assertEqual(format_page_list([11, 12]), '11, 12')

    def test_single_page(self):
        self.assertEqual(format_page_list([4]), '4')

    def test_unsorted_input_with_duplicates(self):
        self.assertEqual(format_page_list([5, 2, 3, 2, 4]), '2-5')

    def test_empty(self):
        self.assertEqual(format_page_list([]), '')
        self.assertEqual(format_page_list(None), '')


class SummaryTests(TestCase):

    def test_excluded_pages(self):
        self.assertEqual(excluded_pages([2, 3, 4], 6), [1, 5, 6])

    def test_selection_summary_records_both_sides(self):
        summary = selection_summary('2-4', [2, 3, 4], 6)
        self.assertEqual(summary['spec'], '2-4')
        self.assertEqual(summary['total'], 6)
        self.assertEqual(summary['selected'], [2, 3, 4])
        self.assertEqual(summary['excluded'], [1, 5, 6])
        self.assertEqual(summary['selected_label'], '2-4')
        self.assertEqual(summary['excluded_label'], '1, 5, 6')

    def test_describe_is_none_when_every_page_was_extracted(self):
        """No notice on the preview when nothing was left out."""
        data = {'page_selection': selection_summary('', [1, 2, 3], 3)}
        self.assertIsNone(describe_page_selection(data))

    def test_describe_reports_the_exclusions(self):
        data = {'page_selection': selection_summary('2-', [2, 3, 4], 4)}
        described = describe_page_selection(data)
        self.assertEqual(described['excluded_count'], 1)
        self.assertEqual(described['excluded_label'], '1')
        self.assertEqual(described['selected_label'], '2-4')
        self.assertEqual(described['selected_count'], 3)
        self.assertEqual(described['total'], 4)
        self.assertEqual(described['spec'], '2-')

    def test_describe_tolerates_a_payload_with_no_selection_recorded(self):
        """Sessions created before this field existed must still render."""
        self.assertIsNone(describe_page_selection({}))
        self.assertIsNone(describe_page_selection(None))


# ---------------------------------------------------------------------------
# PDF-backed helpers
# ---------------------------------------------------------------------------

class PdfPageCountTests(TestCase):

    def test_counts_from_bytes(self):
        self.assertEqual(pdf_page_count(_pdf_bytes(5)), 5)

    def test_counts_from_a_file_like_object_and_restores_the_position(self):
        import io

        handle = io.BytesIO(_pdf_bytes(3))
        self.assertEqual(pdf_page_count(handle), 3)
        self.assertEqual(handle.tell(), 0)
        # Still fully readable afterwards — the upload can go on to be stored.
        self.assertTrue(handle.read().startswith(b'%PDF'))


class CleanUploadSelectionTests(TestCase):

    def test_blank_spec_never_opens_the_pdf(self):
        """The default path must cost exactly what it did before the field existed."""
        with patch('worksheets.page_selection.pdf_page_count') as counter:
            spec, selected, total = clean_upload_selection('', b'not-a-pdf')
        counter.assert_not_called()
        self.assertEqual(spec, '')
        self.assertIsNone(selected)
        self.assertIsNone(total)

    def test_valid_spec_resolves_against_the_real_page_count(self):
        spec, selected, total = clean_upload_selection('2-', _pdf_bytes(4))
        self.assertEqual(spec, '2-')
        self.assertEqual(selected, [2, 3, 4])
        self.assertEqual(total, 4)

    def test_a_full_selection_is_normalised_back_to_blank(self):
        """"1-4" of a 4-page PDF is not an exclusion, so don't record one."""
        spec, selected, total = clean_upload_selection('1-4', _pdf_bytes(4))
        self.assertEqual(spec, '')
        self.assertEqual(selected, [1, 2, 3, 4])

    def test_out_of_range_spec_raises_for_the_view_to_show(self):
        with self.assertRaises(PageSelectionError) as ctx:
            clean_upload_selection('9-12', _pdf_bytes(4))
        self.assertIn('4 pages', str(ctx.exception))

    def test_unreadable_file_is_reported_rather_than_crashing(self):
        with self.assertRaises(PageSelectionError) as ctx:
            clean_upload_selection('2-', b'this is not a pdf at all')
        self.assertIn('couldn', str(ctx.exception).lower())


# ---------------------------------------------------------------------------
# The pipeline honours the selection
# ---------------------------------------------------------------------------

class ExtractWorksheetPagesSelectionTests(TestCase):

    def _open(self, page_count):
        import fitz
        return fitz.open(stream=_pdf_bytes(page_count), filetype='pdf')

    def test_only_selected_pages_are_rendered(self):
        doc = self._open(6)
        try:
            extracted = services.extract_worksheet_pages(doc, selected_pages=[2, 3, 5])
        finally:
            doc.close()

        self.assertEqual(len(extracted['pages']), 3)
        self.assertEqual(extracted['page_count'], 3)
        self.assertEqual(extracted['total_page_count'], 6)
        self.assertEqual(extracted['selected_pages'], [2, 3, 5])

    def test_page_numbers_stay_absolute(self):
        """Image bboxes and the re-crop modal key off the PDF's own page numbers."""
        doc = self._open(6)
        try:
            extracted = services.extract_worksheet_pages(doc, selected_pages=[4, 5])
        finally:
            doc.close()

        self.assertEqual([p['page_num'] for p in extracted['pages']], [4, 5])
        self.assertIn('page 4', extracted['pages'][0]['text'])
        self.assertIn('page 5', extracted['pages'][1]['text'])

    def test_none_renders_every_page(self):
        doc = self._open(3)
        try:
            extracted = services.extract_worksheet_pages(doc)
        finally:
            doc.close()

        self.assertEqual([p['page_num'] for p in extracted['pages']], [1, 2, 3])
        self.assertEqual(extracted['total_page_count'], 3)

    def test_out_of_range_numbers_are_ignored_not_crashed_on(self):
        """The view validates; this is the worker's belt-and-braces."""
        doc = self._open(3)
        try:
            extracted = services.extract_worksheet_pages(doc, selected_pages=[2, 9, 0])
        finally:
            doc.close()

        self.assertEqual([p['page_num'] for p in extracted['pages']], [2])


class ClassifyPageSelectionTests(TestCase):
    """The AI must only ever see the selected pages, and be told the true length."""

    def _extracted(self, page_nums, total):
        return {
            'pages': [{'page_num': n, 'text': f'page {n}', 'screenshot': 'x',
                       'screenshot_w': 10, 'screenshot_h': 10,
                       'pdf_w': 10, 'pdf_h': 10}
                      for n in page_nums],
            'page_count': len(page_nums),
            'total_page_count': total,
            'selected_pages': list(page_nums),
        }

    @patch('worksheets.services._get_anthropic_client')
    @patch('worksheets.services._build_system_prompt', return_value='sys')
    @patch('worksheets.services._classify_chunk_adaptive')
    def test_excluded_pages_are_never_sent(self, adaptive, _prompt, _client):
        adaptive.return_value = {'questions': [], 'usage': {}}
        services.classify_worksheet_questions(
            self._extracted([3, 4], 10), [], [])

        sent = adaptive.call_args.args[2]
        self.assertEqual([p['page_num'] for p in sent], [3, 4])

    @patch('worksheets.services._get_anthropic_client')
    @patch('worksheets.services._build_system_prompt', return_value='sys')
    @patch('worksheets.services._classify_chunk_adaptive')
    def test_the_prompt_quotes_the_pdfs_real_length(self, adaptive, _prompt, _client):
        """Page labels are absolute, so "part of a 10-page paper" must stay true."""
        adaptive.return_value = {'questions': [], 'usage': {}}
        services.classify_worksheet_questions(
            self._extracted([3, 4], 10), [], [])

        self.assertEqual(adaptive.call_args.args[3], 10)

    @patch('worksheets.services._get_anthropic_client')
    @patch('worksheets.services._build_system_prompt', return_value='sys')
    @patch('worksheets.services._classify_chunk_adaptive')
    def test_pages_dropped_by_the_page_cap_are_reported(self, adaptive, _prompt, _client):
        """The 40-page cap used to swallow the tail silently."""
        adaptive.return_value = {'questions': [], 'usage': {}}
        page_nums = list(range(1, services.WORKSHEET_PAGE_CAP + 4))
        result = services.classify_worksheet_questions(
            self._extracted(page_nums, len(page_nums)), [], [])

        over_cap = [s for s in result['skipped_pages']
                    if s['reason'] == services.PAGE_ROLE_OVER_CAP]
        self.assertEqual([s['page'] for s in over_cap], page_nums[services.WORKSHEET_PAGE_CAP:])


class ExtractAndClassifySelectionTests(TestCase):
    """The full worksheet pipeline entry point, which homework shares."""

    @patch('worksheets.services.render_question_images')
    @patch('worksheets.services.classify_worksheet_questions')
    def test_selection_is_applied_and_recorded(self, classify, render):
        import io

        classify.return_value = {'questions': []}
        render.side_effect = lambda doc, pages, result, progress=None: (result, {})

        output = services.extract_and_classify_worksheet(
            io.BytesIO(_pdf_bytes(6)), [], [], page_selection='2-4',
        )

        # Only the selected pages were rendered and handed to classification…
        sent_pages = classify.call_args.args[0]
        self.assertEqual([p['page_num'] for p in sent_pages['pages']], [2, 3, 4])
        # …and only those are billed.
        self.assertEqual(output['page_count'], 3)

        summary = output['result']['page_selection']
        self.assertEqual(summary['spec'], '2-4')
        self.assertEqual(summary['selected'], [2, 3, 4])
        self.assertEqual(summary['excluded'], [1, 5, 6])
        self.assertEqual(summary['total'], 6)

    @patch('worksheets.services.render_question_images')
    @patch('worksheets.services.classify_worksheet_questions')
    def test_no_selection_extracts_everything(self, classify, render):
        import io

        classify.return_value = {'questions': []}
        render.side_effect = lambda doc, pages, result, progress=None: (result, {})

        output = services.extract_and_classify_worksheet(
            io.BytesIO(_pdf_bytes(4)), [], [],
        )

        self.assertEqual(output['page_count'], 4)
        self.assertEqual(output['result']['page_selection']['excluded'], [])

    @patch('worksheets.services.render_question_images')
    @patch('worksheets.services.classify_worksheet_questions')
    def test_a_bad_spec_fails_before_any_ai_call(self, classify, _render):
        import io

        with self.assertRaises(PageSelectionError):
            services.extract_and_classify_worksheet(
                io.BytesIO(_pdf_bytes(4)), [], [], page_selection='9-12',
            )
        classify.assert_not_called()


# ---------------------------------------------------------------------------
# ai_import shares the same parser
# ---------------------------------------------------------------------------

class AIImportExtractSelectionTests(TestCase):

    def test_only_selected_pages_are_extracted(self):
        import io

        from ai_import.services import extract_pdf_content

        extracted = extract_pdf_content(
            io.BytesIO(_pdf_bytes(5)), page_selection='2-3',
        )

        self.assertEqual([p['page_num'] for p in extracted['pages']], [2, 3])
        self.assertEqual(extracted['page_count'], 2)
        self.assertEqual(extracted['total_page_count'], 5)
        self.assertEqual(extracted['page_selection']['excluded'], [1, 4, 5])
        # The concatenated text must not carry an excluded page's content.
        self.assertNotIn('page 1', extracted['all_text'])
        self.assertIn('page 2', extracted['all_text'])

    def test_no_selection_extracts_everything(self):
        import io

        from ai_import.services import extract_pdf_content

        extracted = extract_pdf_content(io.BytesIO(_pdf_bytes(3)))
        self.assertEqual([p['page_num'] for p in extracted['pages']], [1, 2, 3])
        self.assertEqual(extracted['page_selection']['excluded'], [])

    def test_bad_spec_raises(self):
        import io

        from ai_import.services import extract_pdf_content

        with self.assertRaises(PageSelectionError):
            extract_pdf_content(io.BytesIO(_pdf_bytes(3)), page_selection='7')
