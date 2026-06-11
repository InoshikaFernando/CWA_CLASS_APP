# Year 8 Maths — Question Sets

Generated from **"Year 8 Mid Year Exam"** + the **"Theme 8 Revision"** sheet,
in the upload format consumed by `MathsQuestionParser`
(`cwa_classroom/classroom/upload_services.py`).

## How to use

Upload either the `.json` directly, or the `.zip` (which contains
`questions.json`) via the classroom question-upload screen. `year_level` is
set to `8`, so a Level with `level_number = 8` must exist.

## Files (one per topic, 40 questions total)

| Topic | Strand | Qs | File |
|-------|--------|----|------|
| Rounding and Decimals | Number | 5 | `rounding_and_decimals_year8.{json,zip}` |
| Ratio and Proportion | Number | 2 | `ratio_and_proportion_year8.{json,zip}` |
| Rearranging Formulae | Algebra | 8 | `rearranging_formulae_year8.{json,zip}` |
| Solving Linear Equations | Algebra | 13 | `solving_linear_equations_year8.{json,zip}` |
| Forming and Solving Equations | Algebra | 6 | `forming_and_solving_equations_year8.{json,zip}` |
| Expanding Brackets | Algebra | 4 | `expanding_brackets_year8.{json,zip}` |
| Angles | Geometry | 2 | `angles_year8.{json,zip}` |

All questions are `multiple_choice` with exactly one correct answer. Distractors
were chosen so none is mathematically equal to the correct answer (no `1/2`
next to `2/4`, no `1.130` next to `1.13`). Answers were checked against the
revision sheet's answer key where one was provided.

## Not converted (depend on diagrams/figures not in the text)

These exam/revision items need a graph, grid or labelled figure that cannot be
represented faithfully without the image, so they were left out:

- Gradient and equation of a straight line (from a graph)
- Charlie's race — fastest / average speed (distance–time graph)
- Right-angled triangle "find x" (no side lengths given in text)
- Area of a circle / surface area of a half-cylinder (no dimensions in text)
- "Measure EF / angles / perimeter" construction task
- "Find x" and "find the angle labelled" figures
- Rotations on a coordinate grid

If you can supply the figures (as images), these can be added with the `image`
field and bundled into the ZIPs.

## Regenerating

```
python3 imports/year8/_generate.py
```
