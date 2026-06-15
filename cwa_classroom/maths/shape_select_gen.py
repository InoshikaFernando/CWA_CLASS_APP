"""Procedural scene generator for the ``shape_select`` question type.

Pure and deterministic: given a ``seed``, :func:`generate_shape_scene` returns
the identical ``shape_spec`` every time, so a seeded question always draws the
same figure (consistent across attempts and review). The generator is the
*authoring* tool — it produces an explicit, self-contained ``shape_spec`` that
is then stored on the ``Question`` and graded server-side by
``maths.geometry_grading.grade_shape_select``, exactly like a hand-authored
``draw_on_grid`` ``grid_spec``. Storing the expanded scene (not just the seed)
keeps grading independent of any RNG-implementation drift.
"""
import random

from maths.geometry_grading import SHAPE_TYPES, validate_shape_spec

DEFAULT_WIDTH = 680
DEFAULT_HEIGHT = 400


def generate_shape_scene(target_type='triangle', target_count=3, total_shapes=14,
                         *, seed, cols=5, distractors=None,
                         width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    """Return a validated ``shape_spec`` scattering ``total_shapes`` shapes on a
    grid, exactly ``target_count`` of which are ``target_type`` (the rest random
    distractors).

    Deterministic in ``seed`` — uses ``random.Random(seed)``, never the global
    RNG, so generation is reproducible and side-effect-free. The result is run
    through :func:`validate_shape_spec`, so a bad argument combination fails
    loudly here rather than at question-save time.
    """
    if target_type not in SHAPE_TYPES:
        raise ValueError(f'target_type must be one of {SHAPE_TYPES}.')
    if not 1 <= target_count <= total_shapes:
        raise ValueError('target_count must be between 1 and total_shapes.')
    if cols < 1:
        raise ValueError('cols must be a positive integer.')
    pool = [t for t in (distractors or SHAPE_TYPES) if t != target_type]
    if not pool:
        raise ValueError('Need at least one distractor type different from target_type.')

    rng = random.Random(seed)
    rows = -(-total_shapes // cols)  # ceil division
    cell_w = width / cols
    cell_h = height / rows

    cells = list(range(total_shapes))
    target_cells = set(rng.sample(cells, target_count))

    shapes = []
    for i in cells:
        r, c = divmod(i, cols)
        base_x = c * cell_w + cell_w / 2
        base_y = r * cell_h + cell_h / 2
        cx = base_x + (rng.random() - 0.5) * cell_w * 0.22
        cy = base_y + (rng.random() - 0.5) * cell_h * 0.22
        size = round(27 + rng.random() * 13, 1)
        rot = round((rng.random() - 0.5) * 42, 1)
        stype = target_type if i in target_cells else rng.choice(pool)
        shapes.append({
            'id': f's{i}', 'type': stype,
            'cx': round(cx, 1), 'cy': round(cy, 1),
            'size': size, 'rot': rot,
        })

    spec = {
        'target_type': target_type,
        'viewbox': [width, height],
        'seed': seed,
        'shapes': shapes,
    }
    validate_shape_spec(spec)
    return spec
