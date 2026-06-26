"""Display-only formatting filters for maths question/answer text.

These never mutate stored data — they only change how a value is *rendered*, so
grading (which folds the ASCII forms in maths.algebra_grading) is unaffected.
"""
import re

from django import template

register = template.Library()

# Map the characters that can appear in an exponent onto their Unicode
# superscript glyphs.  Letters are intentionally excluded: not every letter has
# a clean superscript, and the exponents we care about (scientific notation,
# units, indices) are numeric.
_SUPERSCRIPT = str.maketrans({
    '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
    '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
    '-': '⁻', '+': '⁺',
})

# "^5", "^-4", "**2" — a caret or double-star followed by an optional sign and
# one or more digits. Whitespace after the marker is tolerated ("10^ 5").
_EXPONENT_RE = re.compile(r'(?:\^|\*\*)\s*([+-]?\d+)')


@register.filter
def exponents(value):
    """Render caret/`**` exponents as Unicode superscripts for display.

    ``"2 × 10^5 × 9.8 × 10^-4"`` → ``"2 × 10⁵ × 9.8 × 10⁻⁴"``.

    Display-only: the stored text keeps the ASCII ``^`` form (which
    :func:`maths.algebra_grading.fold_exponents` collapses), so this never
    changes how a typed answer is matched. Returns a plain ``str`` so Django
    autoescaping still applies to the surrounding question text.
    """
    if not value:
        return value
    return _EXPONENT_RE.sub(
        lambda m: m.group(1).translate(_SUPERSCRIPT), str(value),
    )
