"""Records the interactive maths question types as a screen capture.

This is the marketing capture: one student, one homework carrying every
question type this app has that a worksheet PDF cannot do — long division with
its working ladder, the prime-factor ladder, long multiplication with partial
products, a draggable protractor, a Cartesian plane you tap points onto, a
symmetry grid, a number line, a table of values, a sketched parabola — worked
through at human speed with the browser recording.

It is a REAL test, not a screen-scrape: every answer it types is the correct
one and the run asserts the submission came back 100%. A widget that stops
mounting fails this test rather than quietly producing a video of a student
filling in a box that grades wrong — which is the one bug a marketing capture
could otherwise ship.

Opt-in, because a 2-minute recording has no business in the CI budget::

    CWA_DEMO_VIDEO=1 pytest ui_tests/maths/test_question_showcase.py -n 0

or, with the transcode to MP4 and a sensible default output directory::

    ./scripts/render_question_showcase.sh

Knobs (all environment variables, so no pytest option is added — the ui_core
path filter watches ui_tests/*.py and adding one would run all fifteen UI
groups on every change to this file):

    CWA_DEMO_VIDEO=1     run it at all (otherwise skipped)
    CWA_DEMO_PACE=0.4    multiply every wait — 0.4 is a fast rehearsal cut
    CWA_DEMO_OUT=<dir>   where the .webm lands (default: <repo>/artifacts/demo)
"""
from __future__ import annotations

import os
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from django.utils import timezone
from playwright.sync_api import expect

from ..conftest import TEST_PASSWORD
from .showcase import Showcase, ensure_video_encoder

pytestmark = pytest.mark.skipif(
    not os.environ.get("CWA_DEMO_VIDEO"),
    reason="marketing capture — set CWA_DEMO_VIDEO=1 (see scripts/render_question_showcase.sh)",
)

PACE = float(os.environ.get("CWA_DEMO_PACE", "1"))
REPO_ROOT = Path(__file__).resolve().parents[3]
OUT_DIR = Path(os.environ.get("CWA_DEMO_OUT") or REPO_ROOT / "artifacts" / "demo")

VIEWPORT = {"width": 1280, "height": 720}


# ═══════════════════════════════════════════════════════════════════════════
# The storyboard — one scene per question type, in the order they are worked.
#
# Each scene builds its question and then plays it: the `act` gets the capture
# driver, the question, and the card it was rendered into, and fills the answer
# in the order a child actually would (a long-division quotient digit, then the
# subtraction under it, then the digit brought down).
# ═══════════════════════════════════════════════════════════════════════════

def _build_long_division(Question, level, topic):
    return Question.objects.create(
        level=level, topic=topic,
        question_text="Divide 857 by 4. Show your working.",
        question_type=Question.LONG_DIVISION,
        dividend=857, divisor=4, difficulty=2, points=1,
    )


def _act_long_division(sc, q, card):
    quotient = card.locator(f'[data-ld-q="{q.pk}"]')
    # The scratch rows carry no data attribute — they are working, never marked.
    scratch = card.locator(
        f'[data-ld-wrap="{q.pk}"] input:not([data-ld-q]):not([data-ld-r])')
    cols = len(str(q.dividend))          # one scratch column per dividend digit

    def working(row, col):
        return scratch.nth(row * cols + col)

    # The ladder, written the way it is taught: each product goes UNDER the
    # digits it came from, a multi-digit product straddles the columns it
    # occupies (16 is a 1 in the tens column and a 6 in the units — not "16"
    # crammed into one cell), and each brought-down digit is written out.
    #
    #       2 1 4
    #   4 ) 8 5 7
    #       8          2 x 4
    #       0 5        8 - 8, bring down the 5
    #         4        1 x 4
    #         1 7      5 - 4, bring down the 7
    #       . 1 6      4 x 4, across the tens and units columns
    #           1      17 - 16 — the remainder
    #
    # 8 ÷ 4 = 2, nothing left over; bring down the 5.
    sc.write(quotient.nth(0), "2")
    sc.write(working(0, 0), "8")
    sc.write(working(1, 0), "0")
    sc.write(working(1, 1), "5")
    # 5 ÷ 4 = 1 remainder 1; bring down the 7.
    sc.write(quotient.nth(1), "1")
    sc.write(working(2, 1), "4")
    sc.write(working(3, 1), "1")
    sc.write(working(3, 2), "7")
    # 17 ÷ 4 = 4 remainder 1.
    sc.write(quotient.nth(2), "4")
    sc.write(working(4, 1), "1")
    sc.write(working(4, 2), "6")
    sc.write(working(5, 2), "1")
    sc.write(card.locator(f'[data-ld-r="{q.pk}"]'), "1")


def _build_prime_factorization(Question, level, topic):
    return Question.objects.create(
        level=level, topic=topic,
        question_text="Write 60 as a product of its prime factors.",
        question_type=Question.PRIME_FACTORIZATION,
        target_number=60, difficulty=2, points=1,
    )


def _act_prime_factorization(sc, q, card):
    primes = card.locator(f'[data-pf-p="{q.pk}"]')
    rungs = card.locator(f'[data-pf-wrap="{q.pk}"] input:not([data-pf-p])')
    for step, (prime, rung) in enumerate(
            [("2", "30"), ("2", "15"), ("3", "5")]):
        sc.write(primes.nth(step), prime)
        sc.write(rungs.nth(step), rung)
    sc.write(primes.nth(3), "5")
    # The running product echoes back as 2 × 2 × 3 × 5 — hold on it.
    sc.point_at(card.locator(f'[data-pf-preview="{q.pk}"]'), hold=1.2)


def _build_column_operation(Question, level, topic):
    return Question.objects.create(
        level=level, topic=topic,
        question_text="Work out 23 × 64 using column multiplication.",
        question_type=Question.COLUMN_OPERATION,
        operands=[23, 64], operator="*", difficulty=2, points=1,
    )


def _act_column_operation(sc, q, card):
    """Work 23 x 64 the way it is taught, carry included.

    Two things the first cut of this got wrong. It filled every row LEFT to
    right, when column arithmetic is worked from the units column leftwards —
    that is the method. And it never touched the amber carry row, even though
    the widget renders one, the hint above it says to use it, and both partial
    products here genuinely carry:

          . 1 .        the carry, above the tens column
            2 3
        x   6 4
        ─────────
            9 2        3x4 = 12 → write 2, carry 1;  2x4 = 8 + 1 = 9
          1 3 8        3x6 = 18 → write 8, carry 1;  2x6 = 12 + 1 = 13
        ─────────
          1 4 7 2

    A carry belongs to the ROW being worked, and is rubbed out before the next
    one starts. Both carries here happen to be a 1 above the same column, and
    an earlier cut leaned on that to leave the first one standing through the
    second row — which is not how it is taught and does not read as one either:
    a digit left over from x4 sitting above the working for x6 looks like part
    of the x6. So the box is erased when the first partial is finished, and the
    second carry is written fresh out of 3 x 6 = 18.

    The carry cells are the only inputs in the widget with no data attribute:
    they are scratch, like the partial rows, and only the blue answer row is
    marked.
    """
    carry = card.locator(
        f'[data-ca-wrap="{q.pk}"] input:not([data-ca-partial]):not([data-ca-answer])')
    partial = card.locator(f'[data-ca-partial="{q.pk}"]')
    tens_carry = carry.nth(2)

    # 23 x 4: units first, then the carry it produced, then the tens.
    sc.write(partial.nth(3), "2")       # 3 x 4 = 12, write the 2
    sc.write(tens_carry, "1")           # ...carry the 1
    sc.write(partial.nth(2), "9")       # 2 x 4 = 8, + the 1 carried = 9

    # Done with that row, so the carry goes. A fresh one comes out of 3 x 6.
    sc.erase(tens_carry)
    sc.write(partial.nth(6), "8")       # 3 x 6 = 18, write the 8
    sc.write(tens_carry, "1")           # ...carry the 1, this time from x6
    sc.write(partial.nth(5), "3")       # 2 x 6 = 12, + the 1 carried = 13
    sc.write(partial.nth(4), "1")

    answer = card.locator(f'[data-ca-answer="{q.pk}"]')
    for index, digit in reversed(list(enumerate("1472"))):
        sc.write(answer.nth(index), digit)


def _build_number_line(Question, level, topic):
    return Question.objects.create(
        level=level, topic=topic,
        question_text="Mark −3 on the number line.",
        question_type=Question.NUMBER_LINE, difficulty=1, points=1,
        number_line_spec={"min": -5, "max": 5, "step": 1,
                          "mode": "mark", "target": [-3]},
    )


def _act_number_line(sc, q, card):
    sc.click(card.locator('[data-nl-dot][data-value="-3"]'), settle=0.9)


def _build_fill_blank(Question, level, topic):
    return Question.objects.create(
        level=level, topic=topic,
        question_text="A triangle has ___ sides and ___ angles.",
        question_type=Question.FILL_BLANK, difficulty=1, points=1,
        blank_spec={"blanks": [{"answers": ["3", "three"]},
                               {"answers": ["3", "three"]}]},
    )


def _act_fill_blank(sc, q, card):
    gaps = card.locator("[data-fb-input]")
    sc.write(gaps.nth(0), "3")
    sc.write(gaps.nth(1), "3")


def _build_measure(Question, level, topic):
    return Question.objects.create(
        level=level, topic=topic,
        question_text="Measure angle a.",
        question_type=Question.MEASURE, difficulty=1, points=1,
        numeric_answer=Decimal("135"), answer_tolerance=Decimal("2"),
        answer_unit="°",
    )


# Read a viewBox point of the angle figure back as a viewport coordinate,
# through the SVG's own transform — so it stays right whatever the figure is
# scaled to.
_FIGURE_POINT_JS = """(svg, p) => {
    const pt = svg.createSVGPoint();
    pt.x = p[0]; pt.y = p[1];
    const s = pt.matrixTransform(svg.getScreenCTM());
    return {x: s.x, y: s.y};
}"""

#: Where the protractor is grabbed, relative to its centre mark. Inside the
#: translucent semicircle (radius 132) and clear of the baseline edge, where a
#: press can land outside the fill and grab nothing — and on the RIGHT half, so
#: the hand does not come to rest on top of the reading being demonstrated,
#: which for an obtuse angle is over on the left.
_PROTRACTOR_GRAB = (62, -46)


def _act_measure(sc, q, card):
    """Place the protractor the way it is meant to be used.

    Centre mark ON the vertex, baseline ALONG the arm the angle opens from —
    which is what makes the second arm fall across the 135 tick. This used to
    be two arbitrary drags (slide a bit, spin a bit), and it looked exactly
    like what it was: a protractor lying across the figure at no particular
    angle, next to a confident "135". The figure's own geometry is known, so
    the placement is computed from it instead of eyeballed.

    No rotation is needed and none is performed: ``angle_svg`` always draws the
    angle opening from a horizontal arm, and the protractor's baseline is
    horizontal at rest, so a correct placement is a pure translation. Spinning
    it would be a misuse, not a feature demo.
    """
    from maths.svg_geometry import angle_ray_points

    (vertex_x, vertex_y), _, _ = angle_ray_points(q.numeric_answer)
    vertex = sc.viewport_point(
        card.locator(".measure-figure svg"), _FIGURE_POINT_JS,
        [vertex_x, vertex_y])
    # The instrument anchor is a zero-size div sitting exactly on the
    # protractor's centre mark (see static/js/measure_tool.js), so its own box
    # IS the pivot.
    pivot = sc.viewport_point(
        card.locator(".measure-instrument"),
        "(el) => { const r = el.getBoundingClientRect();"
        "          return {x: r.left, y: r.top}; }")

    grab_dx, grab_dy = _PROTRACTOR_GRAB
    sc.drag_from(pivot["x"] + grab_dx, pivot["y"] + grab_dy,
                 vertex["x"] - pivot["x"], vertex["y"] - pivot["y"])

    # Move the hand off the instrument before the hold, so the frame the viewer
    # gets to study is the reading itself and not a cursor parked on it.
    answer = card.locator(f"input[name='answer_{q.pk}']")
    sc.point_at(answer, hold=0.3)
    sc.beat(1.6)        # hold: the second arm crosses the 135 tick
    sc.write(answer, "135")


def _build_shape_select(Question, level, topic):
    return Question.objects.create(
        level=level, topic=topic,
        question_text="Colour all the triangles.",
        question_type=Question.SHAPE_SELECT, difficulty=1, points=1,
        shape_spec={
            "target_type": "triangle",
            "viewbox": [680, 360],
            "shapes": [
                {"id": "s0", "type": "triangle", "cx": 90, "cy": 90, "size": 40, "rot": 0},
                {"id": "s1", "type": "circle", "cx": 250, "cy": 90, "size": 34, "rot": 0},
                {"id": "s2", "type": "triangle", "cx": 410, "cy": 90, "size": 38, "rot": 12},
                {"id": "s3", "type": "square", "cx": 570, "cy": 90, "size": 34, "rot": 0},
                {"id": "s4", "type": "triangle", "cx": 250, "cy": 250, "size": 40, "rot": -8},
            ],
        },
    )


def _act_shape_select(sc, q, card):
    for shape_id in ("s0", "s2", "s4"):
        sc.click(card.locator(f'[data-shape-id="{shape_id}"]'), settle=0.55)


def _build_draw_on_grid(Question, level, topic):
    return Question.objects.create(
        level=level, topic=topic,
        question_text="Draw the line of symmetry.",
        question_type=Question.DRAW_ON_GRID, difficulty=2, points=1,
        grid_spec={
            "grid": {"cols": 9, "rows": 9},
            "shape": {"type": "polygon",
                      "points": [[2, 3], [6, 3], [6, 5], [2, 5]]},
            "mode": "segments",
            "target": {"segments": [{"x1": 4, "y1": 0, "x2": 4, "y2": 8}]},
            "allow_extra": False,
        },
    )


def _act_draw_on_grid(sc, q, card):
    for gx, gy in ((4, 0), (4, 8)):
        sc.click(card.locator(f'[data-dog-dot="{q.pk}"][data-gx="{gx}"][data-gy="{gy}"]'),
                 settle=0.6)


_PLANE_BOUNDS = {"xmin": -5, "xmax": 5, "ymin": -5, "ymax": 5}


def _build_plot_points(Question, level, topic):
    return Question.objects.create(
        level=level, topic=topic,
        question_text="Plot (3, −2) and (1, 4).",
        question_type=Question.PLOT_POINTS, difficulty=1, points=1,
        plane_spec={"bounds": _PLANE_BOUNDS, "mode": "points",
                    "target": {"points": [[3, -2], [1, 4]]},
                    "allow_extra": False},
    )


def _act_plot_points(sc, q, card):
    for gx, gy in ((3, -2), (1, 4)):
        sc.click(card.locator(f'[data-pl-dot="{q.pk}"][data-gx="{gx}"][data-gy="{gy}"]'),
                 settle=0.6)
    sc.point_at(card.locator(f'[data-pl-readout="{q.pk}"]'), hold=1.1)


def _build_plot_line(Question, level, topic):
    return Question.objects.create(
        level=level, topic=topic,
        question_text="Plot (\u22122, 1), (0, 4) and (3, 1) and join them into a triangle.",
        question_type=Question.PLOT_LINE, difficulty=2, points=1,
        plane_spec={"bounds": _PLANE_BOUNDS, "mode": "segments",
                    "target": {"segments": [
                        {"x1": -2, "y1": 1, "x2": 0, "y2": 4},
                        {"x1": 0, "y1": 4, "x2": 3, "y2": 1},
                        {"x1": 3, "y1": 1, "x2": -2, "y2": 1},   # the closing side
                    ]}},
    )


def _act_plot_line(sc, q, card):
    """Three taps to lay the sides, a fourth on the first point to close it.

    The closing tap only does anything because the question's own answer is a
    ring; on an open "join them in order" question the widget leaves the first
    point alone, so a child cannot add a side that was never asked for.
    """
    for gx, gy in ((-2, 1), (0, 4), (3, 1)):
        sc.click(card.locator(f'[data-pl-dot="{q.pk}"][data-gx="{gx}"][data-gy="{gy}"]'),
                 settle=0.6)
    sc.click(card.locator(f'[data-pl-dot="{q.pk}"][data-gx="-2"][data-gy="1"]'),
             settle=0.5)
    sc.point_at(card.locator(f'[data-pl-readout="{q.pk}"]'), hold=1.2)


def _build_read_graph(Question, level, topic):
    return Question.objects.create(
        level=level, topic=topic,
        question_text="How far had the car travelled after 40 minutes?",
        question_type=Question.READ_GRAPH, difficulty=2, points=1,
        graph_spec={
            "title": "Grand Prix Race",
            "x_axis": {"label": "Time", "unit": "min", "min": 0, "max": 110, "step": 10},
            "y_axis": {"label": "Distance", "unit": "km", "min": 0, "max": 320, "step": 65},
            "series": [{"points": [[20, 65], [40, 130], [60, 200],
                                   [80, 260], [100, 305]]}],
        },
        numeric_answer=Decimal("130"), answer_tolerance=Decimal("5"),
        answer_unit="km",
    )


def _act_read_graph(sc, q, card):
    sc.write(card.locator(f"input[name='answer_{q.pk}']"), "130")


def _build_table_of_values(Question, level, topic):
    return Question.objects.create(
        level=level, topic=topic,
        question_text="Complete the table of values for y = 2x + 1.",
        question_type=Question.TABLE_OF_VALUES, difficulty=2, points=1,
        table_spec={
            "headers": ["x", "y"],
            "rows": [
                [{"given": "-2"}, {"answer": "-3"}],
                [{"given": "-1"}, {"answer": "-1"}],
                [{"given": "0"}, {"answer": "1"}],
                [{"given": "1"}, {"answer": "3"}],
                [{"given": "2"}, {"answer": "5"}],
            ],
        },
    )


def _act_table_of_values(sc, q, card):
    for row, value in enumerate(("-3", "-1", "1", "3", "5")):
        sc.write(card.locator(f'[data-tv-cell][data-rc="{row},1"]'), value,
                 delay=85, settle=0.25)


def _build_sketch_graph(Question, level, topic):
    return Question.objects.create(
        level=level, topic=topic,
        question_text=(
            "Sketch y = x² + x − 2, then give the vertex, the x-axis and "
            "y-axis intercepts and the equation of the axis of symmetry."
        ),
        question_type=Question.SKETCH_GRAPH, difficulty=3, points=4,
        sketch_spec={
            "equation": "y = x^2 + x - 2",
            "bounds": {"xmin": -6, "xmax": 6, "ymin": -4, "ymax": 8},
            "curve": {"type": "quadratic", "a": 1, "b": 1, "c": -2},
            "features": [
                {"kind": "vertex", "points": [[-0.5, -2.25]]},
                {"kind": "x_intercept", "points": [[-2, 0], [1, 0]]},
                {"kind": "y_intercept", "points": [[0, -2]]},
                {"kind": "axis_of_symmetry", "value": -0.5},
            ],
        },
    )


def _act_sketch_graph(sc, q, card):
    for gx, gy in ((-2, 0), (-1, -2), (1, 0)):
        sc.click(card.locator(f"[data-sk-dot][data-gx='{gx}'][data-gy='{gy}']"),
                 settle=0.5)
    for kind, value in (
        ("vertex", "(-0.5, -2.25)"),
        ("x_intercept", "(-2, 0), (1, 0)"),
        ("y_intercept", "(0, -2)"),
        ("axis_of_symmetry", "x = -0.5"),
    ):
        sc.write(card.locator(f"[data-sk-feature][data-kind='{kind}']"), value,
                 delay=55, settle=0.25)


#: (title, subtitle, build, act) — the running order of the capture.
SCENES = [
    ("Long Division",
     "Quotient, working rows and remainder. Every part marked automatically.",
     _build_long_division, _act_long_division),
    ("Prime Factorisation",
     "The factor ladder children are taught on paper, checked as they climb it.",
     _build_prime_factorization, _act_prime_factorization),
    ("Long Multiplication",
     "Partial products, a row to carry into, and the answer. All of the working.",
     _build_column_operation, _act_column_operation),
    ("Number Line",
     "Tap the tick. Negatives, fractions and decimals all on the same scale.",
     _build_number_line, _act_number_line),
    ("Fill in the Blanks",
     "Gaps sit inside the sentence, and each one is marked on its own.",
     _build_fill_blank, _act_fill_blank),
    ("Measure an Angle",
     "Line the protractor up on the vertex and read it off. Graded to a tolerance.",
     _build_measure, _act_measure),
    ("Find the Shapes",
     "Tap every triangle to colour it. A shape hunt that marks itself.",
     _build_shape_select, _act_shape_select),
    ("Lines of Symmetry",
     "Draw straight onto the grid. The line is compared to the answer, not eyeballed.",
     _build_draw_on_grid, _act_draw_on_grid),
    ("Plot Points",
     "A real Cartesian plane. Tap a lattice point to plot it, tap again to undo.",
     _build_plot_points, _act_plot_points),
    ("Plot a Line",
     "The sides join themselves up as they land. Tap the first point to close the shape.",
     _build_plot_line, _act_plot_line),
    ("Read a Graph",
     "Read the value off the axes. Marked within a tolerance, like a real reading.",
     _build_read_graph, _act_read_graph),
    ("Table of Values",
     "Fill the table cell by cell. Four right out of five earns four fifths.",
     _build_table_of_values, _act_table_of_values),
    ("Sketch a Graph",
     "Plot the parabola and name its vertex, intercepts and axis of symmetry.",
     _build_sketch_graph, _act_sketch_graph),
]


@pytest.fixture
def showcase_homework(db, classroom, teacher_user, topic, level):
    """One homework carrying every scene's question, in running order."""
    from homework.models import Homework, HomeworkQuestion
    from maths.models import Question

    questions = [build(Question, level, topic) for _, _, build, _ in SCENES]
    homework = Homework.objects.create(
        classroom=classroom, created_by=teacher_user,
        title="Maths Question Types",
        homework_type="topic", num_questions=len(questions),
        due_date=timezone.now() + timedelta(days=3), max_attempts=3,
    )
    homework.topics.add(topic)
    for order, question in enumerate(questions):
        HomeworkQuestion.objects.create(
            homework=homework, question=question, order=order)
    return homework, questions


def _sign_in_and_open(sc, destination, user):
    """Log in on camera and land on ``destination``.

    Asks for the homework while signed out and lets the login-required redirect
    supply the login page, rather than navigating to it by URL. Two reasons:
    it is the journey a child actually takes (tap the homework, sign in, you are
    on it), and it keeps this file free of an ``/accounts/`` literal — the CI
    path filter for the maths UI group is derived from the URLs its tests name,
    so hard-coding one here would make every accounts change run all thirteen
    of these question-type suites.

    ``conftest.do_login`` is not used for the same shot because it sets a
    1280×800 viewport, which would letterbox a 720p capture halfway through the
    opening.
    """
    page = sc.page
    page.goto(destination)
    page.wait_for_load_state("domcontentloaded")
    username = page.locator("#id_username")
    assert username.count(), (
        "expected the login-required redirect to land on the sign-in form; "
        f"got {page.url}")
    sc.caption("Wizards Learning Hub",
               "Maths question types a worksheet cannot do.", hold=2.2)
    sc.write(username, user.username, delay=85)
    sc.write(page.locator("#id_password"), TEST_PASSWORD, delay=55)
    sc.caption_off()
    sc.click(page.locator("button[type='submit'], input[type='submit']").first)
    page.wait_for_url(lambda url: "login" not in url, timeout=15_000)
    page.wait_for_load_state("networkidle")


@pytest.mark.django_db(transaction=True)
def test_records_the_question_type_showcase(
    browser, live_server, enrolled_student, showcase_homework,
):
    homework, questions = showcase_homework
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ensure_video_encoder()

    context = browser.new_context(
        viewport=VIEWPORT,
        record_video_dir=str(OUT_DIR / "_raw"),
        record_video_size=VIEWPORT,
    )
    page = context.new_page()
    sc = Showcase(page, pace=PACE).install()

    try:
        _sign_in_and_open(
            sc, f"{live_server.url}/homework/{homework.pk}/take/",
            enrolled_student)
        sc.caption(homework.title,
                   f"{len(questions)} question types, one paper.", hold=2.4)
        sc.caption_off()

        cards = page.locator("#hw-form .space-y-6 > div")
        expect(cards).to_have_count(len(questions))

        for index, ((title, subtitle, _, act), question) in enumerate(
                zip(SCENES, questions)):
            card = cards.nth(index)
            sc.chip(f"{index + 1} / {len(SCENES)}")
            sc.spotlight(card)
            sc.caption(title, subtitle, hold=1.9)
            act(sc, question, card)
            sc.beat(0.7)
            sc.caption_off()

        sc.chip("")
        submit = page.get_by_role("button", name="Submit Homework")
        sc.caption("Marked the moment it is handed in",
                   "Every one of these is graded automatically, working and all.",
                   hold=2.2)
        sc.point_at(submit)
        with page.expect_navigation():
            submit.click()
        page.wait_for_load_state("networkidle")

        sc.caption("Wizards Learning Hub",
                   "wizardslearninghub.co.nz", hold=3.4)

        # The capture is only worth shipping if the answers it typed were right.
        expect(page.locator("body")).to_contain_text("100%")
        sc.beat(1.2)
    finally:
        page.close()
        context.close()

    destination = OUT_DIR / "question-types-showcase.webm"
    page.video.save_as(str(destination))
    page.video.delete()
    raw = OUT_DIR / "_raw"
    if raw.is_dir() and not any(raw.iterdir()):
        raw.rmdir()
    print(f"\nCapture written to {destination}")

    from homework.models import HomeworkStudentAnswer, HomeworkSubmission

    submission = HomeworkSubmission.objects.filter(
        homework=homework, student=enrolled_student).first()
    assert submission is not None, "the homework was never submitted"
    wrong = list(
        HomeworkStudentAnswer.objects
        .filter(submission=submission, is_correct=False)
        .values_list("question__question_type", flat=True)
    )
    assert not wrong, (
        f"the capture shows a student typing the RIGHT answer and being marked "
        f"wrong on: {wrong}. The video is unusable until that is fixed."
    )
    assert destination.stat().st_size > 0, "the recording came out empty"
