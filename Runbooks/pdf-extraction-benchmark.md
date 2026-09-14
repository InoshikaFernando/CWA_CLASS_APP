# Runbook — benchmarking PDF extraction

**When to use it:** you changed extraction logic (cropping, page-role
detection, chunking, prompts, the answer-key reader) and want to know whether
it got better or worse on real papers.

This is **not** part of CI. Real papers are large and gitignored, and `--live`
spends tokens, so nothing here runs on a daily PR. Run it by hand, before and
after your change.

---

## 1. Build a corpus (once)

A directory of real PDFs — the messier the better. Keep it **outside the repo**
(or under `media/`, which is gitignored); do not commit papers.

```bash
mkdir -p ~/pdf-corpus
# copy in real uploads: exam papers with answer sheets/keys, scanned worksheets,
# shape charts, anything that has previously extracted badly
```

Worth having in there:

| Paper | Exercises |
|-------|-----------|
| A full exam paper (bubble sheet + questions + answer key) | page-role detection, answer-key matching, chunking |
| A paper with many embedded photos | the figure-crop path — this is what once aborted the worker |
| A scanned/raster-only paper | the fallback crop path (no vector drawings to snap to) |
| A paper with sideways / rotated pages (a landscape scan with `/Rotate 270`) | rotated-page geometry — drawings, text and image placements are reported unrotated while crops are displayed (`worksheets/pdf_geometry.py`) |
| A paper longer than one classification chunk (5+ pages) | page attribution — the model must name real page numbers, not a page's position in its chunk (`worksheets/page_attribution.py`) |
| A shapes chart | name-the-shape mode, many small figures on one page |
| A very dense page (50+ items) | adaptive chunk splitting on `max_tokens` |

## 2. Record a baseline, before your change

```bash
cd cwa_classroom
python manage.py check_pdf_extraction --corpus ~/pdf-corpus --save before.json
```

Free — no AI calls. Reports per paper: pages, pages that would be classified vs
skipped (and why), AI calls the paper would cost, answer-key rows read, figures
found, images rendered, their size, and phase timings.

## 3. Make your change, then compare

```bash
python manage.py check_pdf_extraction --corpus ~/pdf-corpus --baseline before.json
```

Output ends with a per-metric diff. Verdicts are deliberately narrow:

- **better / worse** only for metrics with a real direction — `images_rendered`,
  `key_rows`, `questions`, `answer_accuracy_pct` (higher is better);
  `ai_calls`, `tokens`, `cost_usd` (lower is better); and any new `errors`.
- **changed** for everything else — timings move with the machine, and
  `pages_classified` / `skipped` are improvements or regressions depending on
  what you were trying to do. That call is yours.

The command **exits non-zero if any paper failed to extract**, so it can gate a
release check as well as a review.

## 4. Scoring answer quality (spends tokens)

```bash
python manage.py check_pdf_extraction --corpus ~/pdf-corpus --live --save live-after.json
```

Runs the real pipeline. The headline metric is **`answer_accuracy_pct`**: for
papers carrying their own answer key, the share of the key's answers the AI got
right on its own, before the key overrode it. That is the number to move when
you change prompts or classification.

Also reported: questions extracted, questions with images, `needs_review`
count, tokens and estimated cost per paper.

Requires `ANTHROPIC_API_KEY`. Budget for it — a 24-page paper is ~5 Claude
calls.

## 4b. Checking a page selection (free)

Teachers can restrict an upload to certain pages (`docs/SPEC_PDF_PAGE_SELECTION.md`).
`--pages` runs the bench over just those pages, print-dialog style, so you can see
what a selection would actually send before spending tokens on it:

```bash
python manage.py check_pdf_extraction paper.pdf --pages "2-7, 9"
python manage.py check_pdf_extraction paper.pdf --pages "2-"      # skip a cover sheet
```

The report gains **`pages_selected`** whenever it differs from `pages`. Everything
else means the same thing, measured over the selection only — so `ai_calls` here is
what that teacher's upload would really cost. Works with `--live` too.

## 5. Reading the results

- **`errors` non-empty** — the paper failed to extract. Always a release
  blocker; this is the class of bug that leaves an upload session stuck in
  `processing` in production.
- **`images_rendered` fell** — questions lost their figures. Check
  `figures_found` too: if that fell as well, detection changed; if only
  `images_rendered` fell, the crop path is dropping figures.
- **`key_rows` fell to 0** — the answer-key detector stopped recognising a key,
  so the paper's own answers are no longer applied.
- **`ai_calls` rose** — the paper costs more to classify (usually chunk size, or
  a page-role detector no longer skipping something).

## Related

- `worksheets/benchmark.py` — the measurements themselves.
- `worksheets/tests/test_benchmark.py` — fast checks that the bench works; these
  *do* run in CI, on synthetic PDFs.
- `Runbooks/production-deployment.md` — deploying whatever you just improved.
