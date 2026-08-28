"""Tests for ``topic_doctor`` — the topic-tree report and its two fixes.

The command exists because importers disagree about how they create topics, and
one of them (the homework PDF path) files a question on
``Topic.objects.filter(subject=subject).first()`` when it cannot match the name
it was given. That row is a strand, and the student year page lists sub-topics
only — so the question is offered by no topic quiz. These tests pin that the
report finds that case, and that both fixes refuse anything which would move
questions out of their subject or make the tree three levels deep.
"""
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from accounts.models import CustomUser
from classroom.models import Level, School, Subject, Topic
from maths.models import Question


@pytest.fixture
def tree(db):
    maths = Subject.objects.create(name='Mathematics', slug='mathematics', school=None)
    coding = Subject.objects.create(name='Coding', slug='coding', school=None)
    level = Level.objects.create(level_number=1, display_name='Year 1', school=None)
    level7 = Level.objects.create(level_number=7, display_name='Year 7', school=None)
    facts = Level.objects.create(level_number=100, display_name='Addition L1', school=None)
    admin = CustomUser.objects.create_user('td_admin', 'td@example.com', 'pass1234')
    school = School.objects.create(name='S', slug='s-td', admin=admin)

    number = Topic.objects.create(subject=maths, name='Number', slug='number-td')
    addition = Topic.objects.create(subject=maths, name='Addition', slug='add-td',
                                    parent=number)
    # The duplicate-name case: two rows called "Addition" under one subject.
    addition_dupe = Topic.objects.create(subject=maths, name='Addition',
                                         slug='add2-td', parent=number)
    orphan = Topic.objects.create(subject=maths, name='Subtraction', slug='sub-td')
    other_subject_topic = Topic.objects.create(subject=coding, name='Loops',
                                               slug='loops-td')

    def q(topic, level_obj=None, text='x'):
        return Question.objects.create(
            school=school, level=level_obj or level, topic=topic,
            question_text=text, question_type='short_answer',
            difficulty=1, points=1)

    return {'maths': maths, 'coding': coding, 'number': number,
            'addition': addition, 'addition_dupe': addition_dupe,
            'orphan': orphan, 'other': other_subject_topic,
            'level': level, 'level7': level7, 'facts': facts, 'q': q,
            'school': school}


def run(**kwargs):
    out = StringIO()
    call_command('topic_doctor', stdout=out, stderr=out, **kwargs)
    return out.getvalue()


# ── the report ────────────────────────────────────────────────────────────
def test_reports_a_strand_holding_questions(tree):
    tree['q'](tree['number'], text='filed on the strand')
    tree['q'](tree['addition'], text='filed properly')

    out = run()

    assert 'TOP-LEVEL-HOLDS-QUESTIONS' in out
    assert 'Number' in out
    assert 'no topic quiz' in out


def test_a_strand_without_questions_is_not_flagged_as_stranded(tree):
    tree['q'](tree['addition'])

    out = run(only='TOP-LEVEL-HOLDS-QUESTIONS')

    assert 'TOP-LEVEL-HOLDS-QUESTIONS' not in out


def test_the_report_names_the_years_the_stranded_questions_sit_at(tree):
    tree['q'](tree['number'], text='a')
    tree['q'](tree['number'], level_obj=tree['level7'], text='b')

    out = run()

    assert 'Y1:1' in out and 'Y7:1' in out


def test_reports_duplicate_names(tree):
    out = run()
    assert 'DUPLICATE-NAME' in out
    assert "'Addition'" in out


def test_report_writes_nothing(tree):
    tree['q'](tree['number'])
    before = list(Topic.objects.order_by('id').values_list('id', 'parent_id'))

    run()

    assert list(Topic.objects.order_by('id').values_list('id', 'parent_id')) == before


def test_only_filters_to_one_code(tree):
    tree['q'](tree['number'])
    out = run(only='DUPLICATE-NAME')
    assert 'DUPLICATE-NAME' in out
    assert 'TOP-LEVEL-HOLDS-QUESTIONS' not in out


def test_subject_filter_scopes_the_report(tree):
    tree['q'](tree['other'])          # a stranded row in Coding
    out = run(subject='mathematics')
    assert 'Loops' not in out


def test_an_unknown_subject_is_rejected(tree):
    with pytest.raises(CommandError):
        run(subject='astrophysics')


# ── merge ─────────────────────────────────────────────────────────────────
def test_merge_repoints_questions_and_deletes_the_absorbed_row(tree):
    keeper = tree['q'](tree['addition'], text='keep side')
    moved = tree['q'](tree['addition_dupe'], text='absorbed side')

    run(keep=tree['addition'].id, absorb=str(tree['addition_dupe'].id))

    moved.refresh_from_db()
    assert moved.topic_id == tree['addition'].id
    assert not Topic.objects.filter(pk=tree['addition_dupe'].id).exists()
    keeper.refresh_from_db()
    assert keeper.topic_id == tree['addition'].id


def test_merge_dry_run_writes_nothing(tree):
    moved = tree['q'](tree['addition_dupe'])

    run(keep=tree['addition'].id, absorb=str(tree['addition_dupe'].id), dry_run=True)

    moved.refresh_from_db()
    assert moved.topic_id == tree['addition_dupe'].id
    assert Topic.objects.filter(pk=tree['addition_dupe'].id).exists()


def test_merge_across_subjects_is_refused(tree):
    with pytest.raises(CommandError):
        run(keep=tree['addition'].id, absorb=str(tree['other'].id))
    assert Topic.objects.filter(pk=tree['other'].id).exists()


def test_merging_a_parent_into_its_own_child_is_refused(tree):
    with pytest.raises(CommandError):
        run(keep=tree['addition'].id, absorb=str(tree['number'].id))
    assert Topic.objects.filter(pk=tree['number'].id).exists()


def test_merge_needs_both_sides(tree):
    with pytest.raises(CommandError):
        run(keep=tree['addition'].id)


def test_a_malformed_absorb_list_is_rejected(tree):
    with pytest.raises(CommandError):
        run(keep=tree['addition'].id, absorb='not-an-id')


# ── reparent ──────────────────────────────────────────────────────────────
def test_reparent_moves_a_parentless_topic_under_a_strand(tree):
    run(reparent=tree['orphan'].id, under=tree['number'].id)

    tree['orphan'].refresh_from_db()
    assert tree['orphan'].parent_id == tree['number'].id


def test_reparent_dry_run_writes_nothing(tree):
    run(reparent=tree['orphan'].id, under=tree['number'].id, dry_run=True)

    tree['orphan'].refresh_from_db()
    assert tree['orphan'].parent_id is None


def test_reparent_under_zero_promotes_to_a_strand(tree):
    run(reparent=tree['addition'].id, under=0)

    tree['addition'].refresh_from_db()
    assert tree['addition'].parent_id is None


def test_reparent_that_would_make_a_third_level_is_refused(tree):
    """'Addition' is already a sub-topic; nothing may nest under it."""
    with pytest.raises(CommandError):
        run(reparent=tree['orphan'].id, under=tree['addition'].id)

    tree['orphan'].refresh_from_db()
    assert tree['orphan'].parent_id is None


def test_reparenting_a_row_that_has_subtopics_is_refused(tree):
    with pytest.raises(CommandError):
        run(reparent=tree['number'].id, under=tree['orphan'].id)

    tree['number'].refresh_from_db()
    assert tree['number'].parent_id is None


def test_reparent_across_subjects_is_refused(tree):
    with pytest.raises(CommandError):
        run(reparent=tree['orphan'].id, under=tree['other'].id)

    tree['orphan'].refresh_from_db()
    assert tree['orphan'].parent_id is None


def test_reparent_needs_a_target(tree):
    with pytest.raises(CommandError):
        run(reparent=tree['orphan'].id)


def test_merge_and_reparent_together_are_refused(tree):
    with pytest.raises(CommandError):
        run(keep=tree['addition'].id, absorb=str(tree['addition_dupe'].id),
            reparent=tree['orphan'].id, under=0)


def test_an_unknown_topic_id_is_rejected(tree):
    with pytest.raises(CommandError):
        run(reparent=999999, under=0)


# ── basic facts are meant to hang off a parentless row ────────────────────
def test_basic_facts_alone_is_not_reported_as_stranded(tree):
    """A parentless row holding only level>=100 questions is correct, not broken.

    maths.views builds the basic-facts page from Level.topics for levels >= 100,
    matching 'Addition', 'Subtraction', 'Multiplication', 'Division' and 'Place
    Value Facts' by name — so those questions are reached by their own UI. On
    the live bank, counting them made 1,160 correct rows look like a defect.
    """
    tree['q'](tree['orphan'], level_obj=tree['facts'], text='7 + 8')

    out = run(only='TOP-LEVEL-HOLDS-QUESTIONS')

    assert 'TOP-LEVEL-HOLDS-QUESTIONS' not in out


def test_a_row_with_both_counts_only_the_curriculum_questions(tree):
    tree['q'](tree['orphan'], text='stranded')
    for i in range(3):
        tree['q'](tree['orphan'], level_obj=tree['facts'], text=f'fact {i}')

    out = run(only='TOP-LEVEL-HOLDS-QUESTIONS')

    assert '1 curriculum question(s) directly' in out
    assert '+3 basic facts' in out
    assert '3 basic-facts question(s) on these rows are NOT' in out


def test_the_year_spread_excludes_basic_facts_levels(tree):
    tree['q'](tree['orphan'], text='stranded')
    tree['q'](tree['orphan'], level_obj=tree['facts'], text='fact')

    out = run(only='TOP-LEVEL-HOLDS-QUESTIONS')

    assert 'Y1:1' in out
    assert 'Y100' not in out
