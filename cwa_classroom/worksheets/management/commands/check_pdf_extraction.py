"""Bench PDF extraction over a corpus of real papers.

Run it, change the extraction logic, run it again with --baseline to see whether
the numbers moved the right way. Not part of the test suite: real papers are
large and gitignored, and --live spends tokens, so this never fires on a PR.

    # free — rendering, page roles, answer-key parsing, figure cropping
    python manage.py check_pdf_extraction --corpus ~/pdf-corpus --save before.json

    ...change the logic...

    python manage.py check_pdf_extraction --corpus ~/pdf-corpus --baseline before.json

    # spends tokens — full pipeline, scored against each paper's own answer key
    python manage.py check_pdf_extraction --corpus ~/pdf-corpus --live --save live.json

    # check what a teacher's page selection would actually extract (free)
    python manage.py check_pdf_extraction paper.pdf --pages "2-7, 9"

Full procedure: Runbooks/pdf-extraction-benchmark.md
"""
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from worksheets.benchmark import compare, measure_live, measure_offline


class Command(BaseCommand):
    help = 'Measure PDF extraction over a corpus of PDFs; compare against a baseline.'

    def add_arguments(self, parser):
        parser.add_argument(
            'pdfs', nargs='*',
            help='PDF paths to measure. Omit and use --corpus for a whole directory.')
        parser.add_argument(
            '--corpus', default=None,
            help='Directory of PDFs to measure (non-recursive).')
        parser.add_argument(
            '--live', action='store_true',
            help='Run the real AI pipeline and score answers against each paper’s '
                 'answer key. SPENDS TOKENS.')
        parser.add_argument(
            '--save', default=None,
            help='Write the report to this JSON file, to use as a later --baseline.')
        parser.add_argument(
            '--baseline', default=None,
            help='Compare this run against a previously saved report.')
        parser.add_argument(
            '--pages', default=None,
            help='Only extract these pages, print-dialog style ("2-7, 9", "2-"). '
                 'Applies to every PDF in the run. Omit for all pages.')

    def handle(self, *args, **options):
        pdfs = [Path(p) for p in options['pdfs']]
        if options['corpus']:
            corpus = Path(options['corpus']).expanduser()
            if not corpus.is_dir():
                raise CommandError(f'--corpus is not a directory: {corpus}')
            pdfs.extend(sorted(corpus.glob('*.pdf')))
        if not pdfs:
            raise CommandError(
                'No PDFs to measure. Pass paths, or --corpus DIR with .pdf files in it.')

        missing = [p for p in pdfs if not p.is_file()]
        if missing:
            raise CommandError('Not found: ' + ', '.join(str(p) for p in missing))

        measure = measure_live if options['live'] else measure_offline
        if options['pages']:
            self.stdout.write(self.style.WARNING(
                f'--pages {options["pages"]}: only those pages will be extracted.'))
        if options['live']:
            self.stdout.write(self.style.WARNING(
                f'--live: running the real AI pipeline over {len(pdfs)} paper(s). '
                f'This spends tokens.'))

        report = {}
        for pdf in pdfs:
            self.stdout.write(f'· {pdf.name} … ', ending='')
            self.stdout.flush()
            result = measure(pdf, page_selection=options['pages'])
            report[pdf.name] = result
            if result['errors']:
                self.stdout.write(self.style.ERROR('FAILED'))
            else:
                self.stdout.write(self.style.SUCCESS('ok'))

        self._render(report)

        if options['save']:
            Path(options['save']).write_text(json.dumps(report, indent=2, sort_keys=True))
            self.stdout.write(f'\nSaved report → {options["save"]}')

        if options['baseline']:
            baseline_path = Path(options['baseline'])
            if not baseline_path.is_file():
                raise CommandError(f'--baseline not found: {baseline_path}')
            self._render_diff(json.loads(baseline_path.read_text()), report)

        # No silent pass: a paper that failed to extract is the headline.
        failed = [name for name, r in report.items() if r['errors']]
        if failed:
            raise CommandError(
                f'{len(failed)} paper(s) failed to extract: ' + ', '.join(failed))

    # -- output ------------------------------------------------------------

    def _render(self, report):
        self.stdout.write('')
        for name, result in report.items():
            self.stdout.write(self.style.MIGRATE_HEADING(name))
            for key, value in result.items():
                if key in ('mode', 'errors', 'skipped'):
                    continue
                self.stdout.write(f'    {key:22} {value}')
            skipped = result.get('skipped') or []
            if skipped:
                detail = ', '.join(f'p{s["page"]} ({s["reason"]})' for s in skipped)
                self.stdout.write(f'    {"skipped_pages":22} {len(skipped)} — {detail}')
            for error in result['errors']:
                self.stdout.write(self.style.ERROR(f'    error                  {error}'))

    def _render_diff(self, baseline, current):
        rows = compare(baseline, current)
        self.stdout.write('\n' + self.style.MIGRATE_HEADING('vs baseline'))
        if not rows:
            self.stdout.write('    no change')
            return
        styles = {'better': self.style.SUCCESS, 'worse': self.style.ERROR}
        for paper, metric, before, after, verdict in rows:
            style = styles.get(verdict, lambda text: text)
            self.stdout.write(
                f'    {paper[:28]:30} {metric:22} '
                + style(f'{before} → {after}'))
        worse = sum(1 for row in rows if row[4] == 'worse')
        better = sum(1 for row in rows if row[4] == 'better')
        self.stdout.write(
            f'\n    {better} metric(s) improved, {worse} regressed '
            f'({len(rows) - better - worse} changed with no direction)')
