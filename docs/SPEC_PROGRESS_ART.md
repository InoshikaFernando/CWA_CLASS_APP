# Progress Art — a picture that draws itself as a student works

## Problem

A quiz, a homework paper and a worksheet all tell a child how far through they
are with a progress bar and a "7 of 20". That is information, not motivation.
It is also flat: a 15-question quiz and a 120-question holiday paper give the
same bar, so the long paper feels endless and the short one feels
disproportionately rewarded.

Homework and worksheets add a second problem. Both are explicitly designed to be
put down and picked up again days later, and nothing about the existing progress
display carries any sense of accumulated work across those sittings — reopening
a half-done paper looks the same as starting one.

## Goal

A hidden line drawing that starts as a single dot and gains ink with every
question the student finishes, completing on the last one.

- **Scales with the exercise.** More questions → a more detailed picture, and
  each answer draws a proportionate share of it.
- **Suits the student.** A Year 8 does not get a Year 1's balloon.
- **Resumes.** Save a homework half-done, come back tomorrow, and the drawing
  continues exactly where it stopped — same picture, same amount drawn.

## Design

### The reveal is length-based, not stroke-based

A picture is an ordered list of SVG paths. The browser measures the **total path
length** of all of them and reveals `done / total` of that length using
`stroke-dashoffset`.

This is the decision everything else follows from. Because the budget is a
length rather than a count of strokes, one picture serves any question count
without anything having to divide evenly: a 111-stroke city skyline spread over
100 homework questions draws roughly a stroke per answer, and the same skyline
over 15 questions draws seven at a time. No picture needs a matching question
count, and no question count can produce a "nothing visibly happened" answer.

Stroke order is drawing order, so every picture is authored subject-first and
background-last — a student who stops half way still recognises what they are
making.

### Two dimensions choose the picture

| Dimension | Set by | Why it exists |
|-----------|--------|---------------|
| **Tier** | question count | Ink proportional to effort. Finishing 120 questions and being handed the same eight-stroke balloon a 10-question quiz gives would feel cheap. |
| **Band** | year level | A Year 8 has *earned* a simple picture after a short quiz, but a balloon reads as babyish. They get the mountain lake instead. |

```
Tier    questions   example pictures                strokes
simple  1–12        balloon, fish, kite,            19–32
                    mountain lake, sailing boat
medium  13–30       rocket, wind-up robot, dino     27–34
rich    31–79       castle, under the sea,          50–61
                    the treehouse
epic    80+         city at night, space station    70–111

Band    years   pictures
junior  1–4     balloon, fish, kite, dino, treehouse
senior  5–8     mountain lake
any     both    sailboat, rocket, robot, castle, underwater, city, space
```

A level that is not a curriculum year (basic facts ≥ 100, school-custom ≥ 200)
says nothing about a student's age, so it does not narrow the choice at all.
Every tier holds at least one picture for each band — `tests_progress_art`
fails the build otherwise, because without that the band filter would silently
fall back to the whole tier and hand the Year 8 a balloon anyway.

### Progress is derived; only the choice of picture is stored

This is what makes "finish it tomorrow" work with almost no new state.

- **How much is drawn** is counted, on every page load, from what the student
  has already answered — the saved homework draft, the worksheet's answer rows,
  the quiz's session counter. It therefore cannot drift from the answers, and
  resuming needs no special case: the count is simply right again.
- **Which picture** is stored — on `HomeworkDraft.art_picture_key` and
  `WorksheetSubmission.art_picture_key`. It is the one thing that cannot be
  safely re-derived: adding a picture to the catalogue would otherwise reshuffle
  a deterministic pick and swap the drawing under a student mid-paper.

A quiz is a single sitting, so it stores nothing — the picture is seeded on the
quiz session id, which keeps it stable across a reload and gives the next quiz a
new one.

The stored key **always wins** over a fresh pick, even if the paper's question
count has since changed tier or the student's year would now band differently.
Keeping the drawing a student is half-way through matters more than getting the
tier exactly right for them.

### Two ways the page drives the panel

| Page shape | Mechanism |
|------------|-----------|
| One question at a time (topic quiz, worksheet session) | The server's `done` is already correct on every load. The topic quiz also calls `ProgressArt.set(n)` as each answer is graded, so the picture grows *with* the feedback rather than when the next question loads. |
| Every question on one page (homework take, mixed quiz) | Each question block carries `data-pa-group`, and the renderer counts the answered ones live as the student types. |

Group counting re-examines **only the block the student just touched**, seeding
the rest from the server's view. That is not an optimisation: a coding question's
textarea arrives pre-filled with starter code, and a naive "is this field
non-empty?" sweep would count it as answered on page load and give away part of
the picture for nothing.

The same care applies to the construction widgets (draw-on-grid, shape-select,
number line), which autosave an empty JSON skeleton — `{"segments": []}` —
before anything is drawn. `classroom.progress_art.answer_is_present()` rejects
those, and `static/js/progress_art.js` mirrors the rule exactly; if the two ever
disagreed the drawing would jump the moment a page reloaded.

## Files

| File | Role |
|------|------|
| `cwa_classroom/classroom/progress_art.py` | The picture catalogue (paths built from motif helpers), tier/band rules, `pick` / `resolve` / `context`. |
| `cwa_classroom/static/js/progress_art.js` | The renderer: measures, reveals, animates, counts answer groups. |
| `cwa_classroom/templates/partials/_progress_art.html` | The shared panel. Renders **nothing** without a `progress_art` context dict, so a page that has not opted in is unaffected. |
| `classroom/subject_registry.py` → `answer_field_names()` | Lets the homework take page work out which questions a saved draft has answered without grading anything. Default is the maths convention; `coding` overrides it. |

## Adding a picture

1. Write a `_picture_<name>()` builder in `progress_art.py` returning strokes in
   drawing order. Compose from the motif helpers (`_star`, `_cloud`, `_tree`,
   `_building`, `_window_grid`, …) rather than plotting every point — that is
   how the rich and epic scenes reach 50–110 strokes and stay readable.
2. **Open with `_dot()`.** The renderer shows stroke zero for free, before any
   question is answered, so the panel reads as "your picture starts here"
   instead of an empty box — and the first answer then produces a visible line.
   A picture that opened with a long outline would break both.
3. Register it in `PICTURES` with its tier and band.
4. `classroom/tests/test_progress_art.py` checks the invariants automatically:
   the opening dot, every stroke on-canvas, detail matching the tier, and both
   bands still served in every tier.

## Not included

- **The panel is not sticky.** On the homework take page it sits above the
  questions and scrolls away. A compact pinned version would keep the reward in
  view on a 100-question paper; it needs a design that does not eat a third of a
  phone screen.
- **No colouring-in.** The finished drawing recolours to green and pops once.
  Filling regions with colour as a second pass is the obvious next step.
- **Times-tables and basic-facts drills are not wired up.** They are speed
  drills answered in seconds; the panel is included in `base_quiz.html` and
  inert until a view supplies `progress_art`, so opting either one in later is a
  context dict and nothing else.
