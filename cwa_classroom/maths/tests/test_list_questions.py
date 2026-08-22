"""Tests for the ``list_questions`` command.

The command exists to answer "why does Year 4 Number Patterns only show one
question?", so the cases below are the shapes that cause that: the same topic
name split across two topic rows, questions parked at another year, and a topic
row that carries questions but is not linked to the year.
"""
import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from accounts.models import CustomUser
from classroom.models import Level, School, Subject, Topic
from maths.models import Question


@pytest.fixture
def bank(db):
    subject = Subject.objects.create(name='Mathematics', slug='mathematics', school=None)
    levels = {n: Level.objects.create(level_number=n, display_name=f'Year {n}', school=None)
              for n in (3, 4, 5)}
    admin = CustomUser.objects.create_user('lq_admin', 'lq@example.com', 'pass1234')
    school = School.objects.create(name='Maths Hub', slug='maths-hub-lq', admin=admin)

    number = Topic.objects.create(subject=subject, name='Number and Algebra', slug='number-algebra')
    patterns = Topic.objects.create(subject=subject, name='Patterns and Relationships',
                                    slug='patterns-relationships')
    # The same human name under two different strands — separate rows, because
    # import_global_questions matches topics on (name, parent).
    np_under_number = Topic.objects.create(subject=subject, name='Number Patterns',
                                           slug='number-patterns', parent=number)
    np_under_patterns = Topic.objects.create(subject=subject, name='Number Patterns',
                                             slug='number-patterns-2', parent=patterns)
    fractions = Topic.objects.create(subject=subject, name='Fractions', slug='fractions',
                                     parent=number)
    for topic in (np_under_number, np_under_patterns, fractions):
        topic.levels.add(levels[4])

    def q(level_num, topic, school_obj=None, text='pattern q',
          question_type='multiple_choice'):
        return Question.objects.create(
            school=school_obj, level=levels[level_num], topic=topic,
            question_text=text, question_type=question_type,
            difficulty=1, points=1)

    return {
        'subject': subject, 'levels': levels, 'school': school,
        'number': number, 'patterns': patterns, 'fractions': fractions,
        'np_a': np_under_number, 'np_b': np_under_patterns, 'q': q,
    }


def run(*args, **kwargs):
    out = StringIO()
    call_command('list_questions', *args, stdout=out, **kwargs)
    return out.getvalue()


def test_lists_every_topic_row_sharing_the_name(bank):
    """The quiz sees one topic row; the command must see them all."""
    q = bank['q']
    q(4, bank['np_a'], text='What comes next: 2, 4, 6, __?')
    for i in range(5):
        q(4, bank['np_b'], text=f'Continue the sequence {i}')

    out = run('--year', '4', '--topic', 'number patterns')

    assert '6 question(s) matched.' in out
    assert 'Number and Algebra › Number Patterns' in out
    assert 'Patterns and Relationships › Number Patterns' in out
    assert 'What comes next: 2, 4, 6, __?' in out


def test_other_years_are_reported_not_hidden(bank):
    """Questions parked at Y3/Y5 explain a thin Y4 — say so rather than 0."""
    q = bank['q']
    q(4, bank['np_a'])
    q(3, bank['np_a'])
    q(5, bank['np_b'])
    q(5, bank['np_b'])

    out = run('--year', '4', '--topic', 'number patterns')

    assert '1 question(s) matched.' in out
    assert 'Y3: 1' in out and 'Y5: 2' in out


def test_flags_topic_row_not_linked_to_the_year(bank):
    """A row holding questions but unlinked never reaches the year's picker."""
    q = bank['q']
    bank['np_b'].levels.remove(bank['levels'][4])
    q(4, bank['np_b'])

    out = run('--year', '4', '--topic', 'number patterns')

    assert 'NOT linked to Year 4' in out


def test_scope_filters_global_and_school(bank):
    q = bank['q']
    q(4, bank['np_a'], text='global one')
    q(4, bank['np_a'], school_obj=bank['school'], text='school one')

    both = run('--year', '4', '--topic', 'number patterns')
    glob = run('--year', '4', '--topic', 'number patterns', '--scope', 'global')
    local = run('--year', '4', '--topic', 'number patterns', '--scope', 'school')
    by_school = run('--year', '4', '--topic', 'number patterns',
                    '--school', bank['school'].slug)

    assert '2 question(s) matched.' in both
    assert '1 question(s) matched.' in glob and 'global one' in glob
    assert 'school one' not in glob
    assert '1 question(s) matched.' in local and 'school one' in local
    assert '1 question(s) matched.' in by_school and 'school one' in by_school


def test_parent_strand_name_matches_its_subtopics(bank):
    """Searching the strand finds the questions hanging under it."""
    q = bank['q']
    q(4, bank['np_a'], text='under number and algebra')
    q(4, bank['fractions'], text='a fraction')

    out = run('--year', '4', '--topic', 'Number and Algebra')

    assert '2 question(s) matched.' in out
    assert 'a fraction' in out


def test_exact_topic_narrows_the_match(bank):
    q = bank['q']
    q(4, bank['np_a'], text='pattern')
    q(4, bank['fractions'], text='fraction')

    loose = run('--year', '4', '--topic', 'Number')
    exact = run('--year', '4', '--topic', 'Number Patterns', '--exact-topic')

    assert '2 question(s) matched.' in loose   # strand match pulls in Fractions
    assert '1 question(s) matched.' in exact


def test_unknown_topic_is_an_error_not_an_empty_list(bank):
    with pytest.raises(CommandError) as exc:
        call_command('list_questions', '--year', '4', '--topic', 'zzz nothing')
    assert 'No topic matches' in str(exc.value)


def test_unknown_year_is_an_error(bank):
    with pytest.raises(CommandError) as exc:
        call_command('list_questions', '--year', '99')
    assert 'No Level with level_number=99' in str(exc.value)


def test_empty_result_explains_itself(bank):
    out = run('--year', '4', '--topic', 'number patterns')
    assert '0 question(s) matched.' in out
    assert 'Nothing matched' in out


def test_limit_reports_what_it_hid(bank):
    q = bank['q']
    for i in range(5):
        q(4, bank['np_a'], text=f'q{i}')

    out = run('--year', '4', '--topic', 'number patterns', '--limit', '2')

    assert '5 question(s) matched.' in out
    assert '3 more row(s) not shown' in out


def test_counts_only_omits_the_rows(bank):
    bank['q'](4, bank['np_a'], text='a very distinctive stem')
    out = run('--year', '4', '--topic', 'number patterns', '--counts-only')
    assert '1 question(s) matched.' in out
    assert 'a very distinctive stem' not in out


def test_json_format_carries_the_breakdown(bank):
    q = bank['q']
    q(4, bank['np_a'], text='one')
    q(4, bank['np_b'], text='two')

    payload = json.loads(run('--year', '4', '--topic', 'number patterns',
                             '--format', 'json'))

    assert payload['total'] == 2
    assert {b['count'] for b in payload['breakdown']} == {1}
    assert len(payload['breakdown']) == 2
    assert {r['question_text'] for r in payload['questions']} == {'one', 'two'}
    assert payload['filters']['year'] == 4


def test_csv_output_to_file(bank, tmp_path):
    bank['q'](4, bank['np_a'], text='csv me')
    path = tmp_path / 'out.csv'

    run('--year', '4', '--topic', 'number patterns', '--format', 'csv',
        '-o', str(path))

    text = path.read_text(encoding='utf-8')
    assert 'question_text' in text.splitlines()[0]
    assert 'csv me' in text


def test_type_filter(bank):
    q = bank['q']
    q(4, bank['np_a'], text='mc', question_type='multiple_choice')
    q(4, bank['np_a'], text='sa', question_type='short_answer')

    out = run('--year', '4', '--topic', 'number patterns',
              '--type', 'short_answer')

    assert '1 question(s) matched.' in out
    assert 'sa' in out


def test_year_is_optional(bank):
    q = bank['q']
    q(3, bank['np_a'])
    q(4, bank['np_a'])
    q(5, bank['np_b'])

    out = run('--topic', 'number patterns')

    assert '3 question(s) matched.' in out
