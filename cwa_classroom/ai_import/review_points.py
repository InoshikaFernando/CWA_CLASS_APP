"""Turn a flagged question's ``review_reason`` into *what to check, and where*.

Every import guard that routes a question to the teacher writes a prose
``review_reason`` — "Image check: the crop cuts off part of the figure…",
"Second-opinion check disagreed: verifier answered "4" vs "5"." — and the three
PDF preview screens showed it as the ``title=`` tooltip of a small "⚠ Review"
badge. The reason was therefore invisible until you hovered exactly the right
10px badge, so in practice a flagged question meant re-reading the whole
question to find what the verifier disliked.

This module splits that reason into **review points**: one short piece of
advice, each tagged with the *field* it is about (the answer, the options, the
image, the explanation…). The preview renders them as a visible strip with a
chip per point, and the chip scrolls the teacher straight to that field.

Nothing here re-decides whether a question needs review — ``needs_review`` and
``review_reason`` stay exactly as the guards wrote them. This only reads them,
so a reason stored on a session weeks ago is understood just as well as one
written by today's guards.
"""
import re

# Field key -> (chip label, what the chip means). The key is also the
# ``data-review-field`` anchor the preview templates put on that field, so the
# chip can scroll to it. Keep the two in step.
FIELD_LABELS = {
    'answer': 'Answer',
    'options': 'Options',
    'image': 'Image',
    'explanation': 'Explanation',
    'type': 'Question type',
    'question': 'Question',
}

# The field each reason is about, worked out from the guards' own wording.
# ORDER MATTERS — the first rule that matches wins, and the reasons deliberately
# name more than one field ("the key has been applied, please check it matches
# the option text" is about the options even though it says "answer key"). The
# order below is most-specific-instruction first.
_RULES = (
    ('explanation', re.compile(r'\bexplanations?\b', re.I)),
    ('options', re.compile(r'\boptions?\b', re.I)),
    ('answer', re.compile(
        r'\banswers?\b|\banswered\b|\banswer key\b'
        r'|\bcount\b[^.]*\bconfirm\b|\bconfirm\b[^.]*\bcount\b', re.I)),
    ('image', re.compile(
        r'\bimages?\b|\bfigures?\b|\bdiagrams?\b|\bcrops?\b|\bre-crop\b'
        r'|\bphotos?\b|\bpictures?\b|\bshapes?\b|\bgraphs?\b', re.I)),
    ('type', re.compile(r'\bclassified this as\b|\bquestion type\b', re.I)),
)

# What the badge has always said when a guard flagged a question without
# recording why. Kept verbatim so the strip never reads as less certain than
# the tooltip it replaces.
DEFAULT_REASON = (
    'The system could not determine this answer with confidence — '
    'please double-check it.'
)

# A sentence break: end punctuation, space, then the start of a new sentence.
_SENTENCE_BREAK = re.compile(r'(?<=[.!?])\s+(?=["“(]?[A-Z])')

# Abbreviations whose full stop is not the end of a sentence. The guards write
# 'e.g. "this shape"', which otherwise splits mid-reason.
_ABBREVIATIONS = ('e.g.', 'i.e.', 'vs.', 'etc.', 'approx.', 'No.', 'Fig.')


def classify_reason(text):
    """The field key one piece of advice is about, or ``None`` when it names no
    field at all (a bare "Check it before importing.")."""
    for field, pattern in _RULES:
        if pattern.search(text or ''):
            return field
    return None


def _sentences(text):
    """``text`` split into sentences, keeping abbreviations intact."""
    parts, start = [], 0
    for match in _SENTENCE_BREAK.finditer(text):
        head = text[start:match.start()]
        if any(head.rstrip().endswith(a) for a in _ABBREVIATIONS):
            continue
        parts.append(head.strip())
        start = match.end()
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return [p for p in parts if p]


def review_points(question):
    """The review advice for one question, as ``[{field, label, text}, ...]``.

    Empty for a question that is not flagged. A flagged question always yields
    at least one point, falling back to the badge's long-standing wording when
    the guard recorded no reason.

    Several guards can flag the same question, and they join their reasons into
    one string, so the reason is split back into sentences and each is tagged
    with the field it is about. Neighbouring sentences about the *same* field
    are joined again — a finding and the instruction that follows it ("…no
    image was attached. Crop or add the correct image.") are one point, not
    two — and a sentence that names no field of its own belongs to the point
    before it.
    """
    if not isinstance(question, dict) or not question.get('needs_review'):
        return []

    reason = (question.get('review_reason') or '').strip() or DEFAULT_REASON

    points = []
    for sentence in _sentences(reason) or [reason]:
        field = classify_reason(sentence)
        if points and (field is None or field == points[-1]['field']):
            points[-1]['text'] += ' ' + sentence
            continue
        points.append({'field': field or 'question', 'text': sentence})

    for point in points:
        point['label'] = FIELD_LABELS[point['field']]
    return points
