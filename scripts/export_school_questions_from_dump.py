"""Offline export: pull one school's maths questions out of a prod MySQL dump
and emit a rich, reviewable JSON grouped by year / title / sub-title.

This is the *offline twin* of `manage.py export_school_questions` (which reads
the live DB). Both emit the SAME schema, consumed by
`manage.py import_global_questions`.

Usage:
    python export_school_questions_from_dump.py <dump.sql> <school_id> <out.json>
"""
import json
import re
import sys
from collections import defaultdict

# maths.Question types that the importer carries with full fidelity.
ALL_TYPES = {
    'multiple_choice', 'true_false', 'short_answer', 'fill_blank', 'calculation',
    'extended_answer', 'long_division', 'prime_factorization', 'column_operation',
    'measure', 'draw_on_grid', 'shape_select',
}

ESC = {"'": "'", '"': '"', 'n': '\n', 'r': '\r', 't': '\t', '\\': '\\', '0': '\x00'}


def _read(path):
    # Dump is mostly UTF-8 but carries a few stray latin-1 '×' bytes (0xD7) in
    # the times-table topic names. Decode tolerantly, then repair "(3�)" -> "(3×)".
    with open(path, 'rb') as f:
        text = f.read().decode('utf-8', errors='replace')
    return re.sub(r'(\d)�', r'\1×', text)


def _parse_string(s, i, n):
    out = []
    while i < n:
        c = s[i]
        if c == '\\' and i + 1 < n:
            out.append(ESC.get(s[i + 1], s[i + 1])); i += 2
        elif c == "'":
            if i + 1 < n and s[i + 1] == "'":
                out.append("'"); i += 2
            else:
                i += 1; break
        else:
            out.append(c); i += 1
    return ''.join(out), i


def _coerce(raw):
    if not raw or raw.upper() == 'NULL':
        return None
    try:
        return int(raw)
    except ValueError:
        try:
            return float(raw)
        except ValueError:
            return raw


def _parse_row(s, i, n):
    vals = []
    while i < n:
        while i < n and s[i] == ' ':
            i += 1
        if i >= n:
            break
        if s[i] == ')':
            i += 1; break
        if s[i] == ',':
            i += 1; continue
        if s[i] == "'":
            v, i = _parse_string(s, i + 1, n); vals.append(v)
        elif s[i:i + 4].upper() == 'NULL':
            vals.append(None); i += 4
        else:
            j = i
            while j < n and s[j] not in (',', ')'):
                j += 1
            vals.append(_coerce(s[i:j].strip())); i = j
    return vals, i


def parse_table(content, name):
    rows = []
    for m in re.finditer(r"INSERT INTO `" + re.escape(name) + r"` VALUES\s+(.*?);\s*\n",
                         content, re.DOTALL):
        vs = m.group(1); i, n = 0, len(vs)
        while i < n:
            while i < n and vs[i] in ' \t\n\r,':
                i += 1
            if i >= n:
                break
            if vs[i] != '(':
                i += 1; continue
            i += 1; row, i = _parse_row(vs, i, n); rows.append(tuple(row))
    return rows


def cols(content, name):
    m = re.search(r"CREATE TABLE `" + name + r"` \((.*?)\n\) ENGINE", content, re.DOTALL)
    return [c for c in re.findall(r"^\s+`([^`]+)`", m.group(1), re.M)]


def table(content, name):
    c = cols(content, name)
    return [dict(zip(c, r)) for r in parse_table(content, name)]


def _json_field(v):
    """json columns arrive as a string ('[90, 82]') or None — re-parse them."""
    if v is None or v == '':
        return None
    if isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v)
    except (ValueError, TypeError):
        return v


def build(dump_path, school_id):
    content = _read(dump_path)
    schools = {r['id']: r['name'] for r in table(content, 'classroom_school')}
    levels = {r['id']: r for r in table(content, 'classroom_level')}
    topics = {r['id']: r for r in table(content, 'classroom_topic')}
    questions = [q for q in table(content, 'maths_question') if q['school_id'] == school_id]
    answers_by_q = defaultdict(list)
    for a in table(content, 'maths_answer'):
        answers_by_q[a['question_id']].append(a)

    def year_of(q):
        lv = levels.get(q['level_id'])
        return (lv['display_name'], lv['level_number']) if lv else (f"level_{q['level_id']}", None)

    def title_sub(q):
        t = topics.get(q['topic_id'])
        if not t:
            return ('(no topic)', '')
        if t['parent_id'] and t['parent_id'] in topics:
            return (topics[t['parent_id']]['name'], t['name'])
        return (t['name'], '')

    grouped = defaultdict(list)
    for q in questions:
        (year, level_number) = year_of(q)
        title, subtitle = title_sub(q)
        ans = sorted(answers_by_q.get(q['id'], []), key=lambda a: (a['order'] or 0, a['id']))
        grouped[(level_number, year, title, subtitle)].append({
            'source_id': q['id'],
            'question_text': q['question_text'] or '',
            'question_type': q['question_type'] or 'multiple_choice',
            'difficulty': q['difficulty'] if q['difficulty'] is not None else 1,
            'points': q['points'] if q['points'] is not None else 1,
            'explanation': q['explanation'] or '',
            'image': q['image'] or None,
            'video': q['video'] or None,
            'validation_type': q['validation_type'] or 'auto',
            'answer_format': q['answer_format'] or 'text',
            'grading_rubric': q['grading_rubric'] or '',
            'dividend': q['dividend'],
            'divisor': q['divisor'],
            'target_number': q['target_number'],
            'operands': _json_field(q['operands']),
            'operator': q['operator'] or '',
            'numeric_answer': q['numeric_answer'],
            'answer_tolerance': q['answer_tolerance'],
            'answer_unit': q['answer_unit'] or '',
            'grid_spec': _json_field(q['grid_spec']),
            'shape_spec': _json_field(q['shape_spec']),
            'answers': [
                {
                    'answer_text': a['answer_text'] or '',
                    'is_correct': bool(a['is_correct']),
                    'order': a['order'] or 0,
                    'answer_image': a['answer_image'] or None,
                }
                for a in ans
            ],
        })

    groups = []
    for (level_number, year, title, subtitle) in sorted(grouped):
        groups.append({
            'year': year,
            'level_number': level_number,
            'title': title,
            'subtitle': subtitle,
            'questions': grouped[(level_number, year, title, subtitle)],
        })

    return {
        'meta': {
            'source_school_id': school_id,
            'source_school': schools.get(school_id, str(school_id)),
            'generated_from': dump_path.replace('\\', '/').split('/')[-1],
            'question_count': len(questions),
            'group_count': len(groups),
        },
        'groups': groups,
    }


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        sys.exit(1)
    dump_path, school_id, out_path = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    data = build(dump_path, school_id)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    # Summary
    m = data['meta']
    print(f"Exported {m['question_count']} questions in {m['group_count']} groups "
          f"from school {m['source_school_id']} ({m['source_school']}) -> {out_path}")
    types = defaultdict(int)
    imgs = 0
    unsupported = 0
    for g in data['groups']:
        for q in g['questions']:
            types[q['question_type']] += 1
            if q['image']:
                imgs += 1
            if q['question_type'] not in ALL_TYPES:
                unsupported += 1
    print("  types:", dict(sorted(types.items(), key=lambda kv: -kv[1])))
    print(f"  with image: {imgs}")
    if unsupported:
        print(f"  WARNING: {unsupported} questions of an unknown type")


if __name__ == '__main__':
    main()
