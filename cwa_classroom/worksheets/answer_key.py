"""Read a paper's answer key and apply it to the questions extracted from it.

Exam papers ship the official answers in the back: "44  C  6:45pm to 7pm is 15
minutes…". Those pages carry no questions, so they are skipped before
classification (see services.detect_page_role) — but their content is the best
answer data in the document. The AI answers the questions itself, and where it
disagrees with the paper the paper wins.

Two rules keep this honest:

* The key is authoritative for the ANSWER, never for the question. It only
  re-points which option is correct and fills an empty explanation with the
  paper's working.
* A key that disagrees with the AI means one of the two misread the page. The
  key is applied, and the question is flagged ``needs_review`` so the teacher
  sees the disagreement rather than inheriting it silently. Agreement needs no
  flag.
"""
import logging
import re

logger = logging.getLogger(__name__)

# "44  C  working…" on one line.
_INLINE_ROW_RE = re.compile(r'^(\d{1,3})[ \t]+([A-D])\b[ \t]*(.*)$')
# The number alone on its line (the letter is on the next one).
_NUMBER_ONLY_RE = re.compile(r'^(\d{1,3})$')
_LETTER_ONLY_RE = re.compile(r'^([A-D])$')

# Question types whose correct answer is one of a list of options, so a letter
# from the key can select it. Anything else only gets the working text.
_OPTION_TYPES = {'multiple_choice', 'true_false'}


def parse_answer_key(text):
    """{question_number: {'letter': 'C', 'working': '…'}} from an answer-key page.

    Handles both layouts seen in real papers: the number and letter stacked on
    their own lines (what PyMuPDF usually returns), and both on one line. Text
    following a row, up to the next row, is that answer's working.
    """
    rows = {}
    lines = [line.strip() for line in (text or '').splitlines()]
    current = None

    index = 0
    while index < len(lines):
        line = lines[index]

        inline = _INLINE_ROW_RE.match(line)
        stacked_number = _NUMBER_ONLY_RE.match(line)
        stacked_letter = (_LETTER_ONLY_RE.match(lines[index + 1])
                          if stacked_number and index + 1 < len(lines) else None)

        if inline:
            current = {'letter': inline.group(2), 'working': []}
            if inline.group(3):
                current['working'].append(inline.group(3))
            rows[int(inline.group(1))] = current
            index += 1
            continue

        if stacked_number and stacked_letter:
            current = {'letter': stacked_letter.group(1), 'working': []}
            rows[int(stacked_number.group(1))] = current
            index += 2
            continue

        if current is not None and line:
            current['working'].append(line)
        index += 1

    return {number: {'letter': row['letter'],
                     'working': ' '.join(row['working']).strip()}
            for number, row in rows.items()}


def _correct_indexes(answers):
    return [i for i, answer in enumerate(answers) if answer.get('is_correct')]


def _apply_row(question, row):
    """Apply one key row to one question. Returns 'agreed', 'corrected' or None.

    None means the row could not be applied to this question's answer — a
    written-answer question, or options that don't reach the key's letter.
    """
    working = row.get('working') or ''
    if working and not (question.get('explanation') or '').strip():
        question['explanation'] = working

    answers = question.get('answers') or []
    index = ord(row['letter']) - ord('A')
    if question.get('question_type') not in _OPTION_TYPES or not 0 <= index < len(answers):
        return None

    already_correct = _correct_indexes(answers)
    for position, answer in enumerate(answers):
        answer['is_correct'] = position == index
    question['answer_source'] = 'answer_key'

    if already_correct == [index]:
        return 'agreed'

    # The AI and the paper disagree. The paper wins — but one of them misread
    # this question, and if it was the AI's option ORDER that slipped then the
    # key's letter now points at the wrong text. The teacher gets to see that.
    question['needs_review'] = True
    question['review_reason'] = (
        f"The paper's answer key says {row['letter']}. The AI had chosen "
        + (f'option {chr(ord("A") + already_correct[0])}' if len(already_correct) == 1
           else 'a different answer')
        + ' — the key has been applied, please check it matches the option text.'
    )
    return 'corrected'


def apply_answer_key(questions, key_pages):
    """Apply the answer key on *key_pages* to *questions*, in place.

    ``key_pages`` are the extracted page dicts detected as answer keys (each
    needs 'page_num' and 'text').

    Returns a summary dict for the preview — what was applied, what disagreed,
    and what could not be matched — so nothing about this is invisible.
    """
    rows = {}
    for page in key_pages:
        rows.update(parse_answer_key(page.get('text', '')))

    summary = {
        'pages': [page['page_num'] for page in key_pages],
        'rows_found': len(rows),
        'agreed': 0,
        'corrected': 0,
        'explanation_only': 0,
        'unmatched_rows': [],
        'questions_without_number': 0,
    }
    if not rows:
        return summary

    matched_numbers = set()
    for question in questions:
        number = question.get('source_number')
        if not number:
            summary['questions_without_number'] += 1
            continue
        row = rows.get(number)
        if not row:
            continue
        matched_numbers.add(number)
        outcome = _apply_row(question, row)
        if outcome == 'agreed':
            summary['agreed'] += 1
        elif outcome == 'corrected':
            summary['corrected'] += 1
        else:
            summary['explanation_only'] += 1

    summary['unmatched_rows'] = sorted(set(rows) - matched_numbers)
    summary['applied'] = summary['agreed'] + summary['corrected']
    logger.info(
        'Answer key on page(s) %s: %s rows, %s applied (%s corrected the AI), '
        '%s working-only, %s rows with no question, %s questions unnumbered',
        summary['pages'], summary['rows_found'], summary['applied'],
        summary['corrected'], summary['explanation_only'],
        len(summary['unmatched_rows']), summary['questions_without_number'],
    )
    return summary
