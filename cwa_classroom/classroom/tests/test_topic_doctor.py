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
            'level': level, 'level7': level7, 'q': q, 'school': school}


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


def test_reports_near_duplicate_names(tree):
    Topic.objects.create(subject=tree['maths'], name='Place Value',
                         slug='pv-td', parent=tree['number'])
    Topic.objects.create(subject=tree['maths'], name='Place Values',
                         slug='pvs-td', parent=tree['number'])

    out = run()
    assert 'NEAR-DUPLICATE-NAME' in out
    assert 'place value | place values' in out


def test_a_near_duplicate_group_names_what_each_row_holds(tree):
    ratio = Topic.objects.create(subject=tree['maths'], name='Ratio & Proportion',
                                 slug='rp1-td', parent=tree['number'])
    Topic.objects.create(subject=tree['maths'], name='Ratio and Proportion',
                         slug='rp2-td', parent=tree['number'])
    tree['q'](ratio)

    out = run(only='NEAR-DUPLICATE-NAME')
    assert f'[{ratio.id:>6}]' in out
    assert '1 questions' in out


def test_a_tidy_tree_reports_no_near_duplicates(tree):
    out = run()
    # "Addition"/"Addition" is an exact clash, already DUPLICATE-NAME.
    assert 'NEAR-DUPLICATE-NAME' not in out


def test_near_duplicates_are_reported_without_changing_anything(tree):
    Topic.objects.create(subject=tree['maths'], name='Fraction', slug='f1-td',
                         parent=tree['number'])
    Topic.objects.create(subject=tree['maths'], name='Fractions', slug='f2-td',
                         parent=tree['number'])
    before = Topic.objects.count()

    run()

    assert Topic.objects.count() == before


# ── --list ────────────────────────────────────────────────────────────────
def test_list_prints_subtopics_under_their_strand(tree):
    out = run(list_tree=True)
    number_at = out.index('Number')
    addition_at = out.index('Addition')
    assert number_at < addition_at
    assert '    [' in out          # sub-topics are indented under the strand
    # Under its own strand, not swept into the no-strand bucket.
    assert 'under no strand of this subject' not in out


def test_list_names_every_subject(tree):
    out = run(list_tree=True)
    assert 'Mathematics' in out
    assert 'Coding' in out


def test_list_can_be_scoped_to_one_subject(tree):
    out = run(list_tree=True, subject='coding')
    assert 'Loops' in out
    assert 'Addition' not in out


def test_list_shows_a_row_whose_parent_sits_in_another_subject(tree):
    stray = Topic.objects.create(subject=tree['coding'], name='Recursion',
                                 slug='rec-td', parent=tree['number'])

    out = run(list_tree=True, subject='coding')
    assert 'Recursion' in out
    assert 'under no strand of this subject' in out
    assert str(stray.id) in out


def test_list_writes_nothing(tree):
    before = list(Topic.objects.order_by('id').values_list('id', 'parent_id'))

    run(list_tree=True)

    assert list(Topic.objects.order_by('id').values_list('id', 'parent_id')) == before


def test_list_skips_the_findings(tree):
    # --list is for reading the tree; the report is a separate run.
    out = run(list_tree=True)
    assert 'DUPLICATE-NAME' not in out


def test_list_says_a_row_is_three_levels_deep_rather_than_elsewhere(tree):
    # Number > Division > Division (10x): the parent is in THIS subject, one
    # level too deep. Calling it "elsewhere" sends a reader to another subject.
    division = Topic.objects.create(subject=tree['maths'], name='Division',
                                    slug='div-3l-td', parent=tree['number'])
    Topic.objects.create(subject=tree['maths'], name='Division (10x)',
                         slug='div10-3l-td', parent=division)

    out = run(list_tree=True, subject='mathematics')
    assert 'three levels deep' in out
    assert 'under no strand of this subject' in out


def test_list_says_which_subject_a_foreign_parent_belongs_to(tree):
    Topic.objects.create(subject=tree['coding'], name='Recursion',
                         slug='rec-fp-td', parent=tree['number'])

    out = run(list_tree=True, subject='coding')
    assert 'Mathematics' in out
    assert 'three levels deep' not in out


def test_reports_a_three_level_topic(tree):
    division = Topic.objects.create(subject=tree['maths'], name='Division',
                                    slug='div-rep-td', parent=tree['number'])
    Topic.objects.create(subject=tree['maths'], name='Division (10x)',
                         slug='div10-rep-td', parent=division)

    assert 'THREE-LEVEL-TOPIC' in run()


def test_a_two_level_tree_reports_no_three_level_topic(tree):
    assert 'THREE-LEVEL-TOPIC' not in run()


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


def test_a_merge_reports_the_year_links_it_carried(tree):
    keep = Topic.objects.create(subject=tree['maths'], name='Pythagoras',
                                slug='py-k-td', parent=tree['number'])
    gone = Topic.objects.create(subject=tree['maths'], name='Pythagoras Theorem',
                                slug='py-g-td', parent=tree['number'])
    gone.levels.add(tree['level7'])

    out = run(keep=keep.id, absorb=str(gone.id))
    assert 'link carried to the survivor' in out
    keep.refresh_from_db()
    assert list(keep.levels.values_list('level_number', flat=True)) == [7]


def test_a_dry_run_merge_leaves_the_year_links_alone(tree):
    keep = Topic.objects.create(subject=tree['maths'], name='Indices',
                                slug='ix-k-td', parent=tree['number'])
    gone = Topic.objects.create(subject=tree['maths'], name='Indice',
                                slug='ix-g-td', parent=tree['number'])
    gone.levels.add(tree['level7'])

    run(keep=keep.id, absorb=str(gone.id), dry_run=True)

    keep.refresh_from_db()
    assert keep.levels.count() == 0
    assert Topic.objects.filter(pk=gone.id).exists()


def test_a_merge_reports_the_statistics_it_recomputed(tree):
    from maths.models import StudentFinalAnswer
    keep = Topic.objects.create(subject=tree['maths'], name='Angles',
                                slug='an-k-td', parent=tree['number'])
    gone = Topic.objects.create(subject=tree['maths'], name='Angle',
                                slug='an-g-td', parent=tree['number'])
    student = CustomUser.objects.create_user('td_stat', 'st@example.com', 'pass1234')
    StudentFinalAnswer.objects.create(student=student, topic=gone,
                                      level=tree['level7'], points=6.0)

    out = run(keep=keep.id, absorb=str(gone.id))
    assert 'topic-level statistics recomputed' in out


def test_a_merge_reports_dependents_moved_off_a_colliding_row(tree):
    from classroom.models import SubTopic, TopicLevel
    keep = Topic.objects.create(subject=tree['maths'], name='Fractions',
                                slug='fr-k-td', parent=tree['number'])
    gone = Topic.objects.create(subject=tree['maths'], name='Fraction',
                                slug='fr-g-td', parent=tree['number'])
    TopicLevel.objects.create(topic=keep, level=tree['level7'])
    tl_gone = TopicLevel.objects.create(topic=gone, level=tree['level7'])
    SubTopic.objects.create(topic_level=tl_gone, name='Equivalent',
                            slug='equiv-td')

    out = run(keep=keep.id, absorb=str(gone.id))
    assert 'dependents moved off a colliding row' in out
    assert SubTopic.objects.get(slug='equiv-td').topic_level.topic_id == keep.id


# ── --rename ──────────────────────────────────────────────────────────────
def test_rename_changes_the_name(tree):
    out = run(rename=tree['orphan'].id, new_name='Take Away')
    tree['orphan'].refresh_from_db()
    assert tree['orphan'].name == 'Take Away'
    assert 'Renamed' in out


def test_rename_leaves_the_slug_alone(tree):
    run(rename=tree['orphan'].id, new_name='Take Away')
    tree['orphan'].refresh_from_db()
    assert tree['orphan'].slug == 'sub-td'


def test_rename_changes_the_slug_when_asked(tree):
    out = run(rename=tree['orphan'].id, new_name='Take Away', new_slug='take-away-td')
    tree['orphan'].refresh_from_db()
    assert tree['orphan'].slug == 'take-away-td'
    assert 'not moved' in out          # the warning about image paths


def test_rename_dry_run_writes_nothing(tree):
    out = run(rename=tree['orphan'].id, new_name='Take Away', dry_run=True)
    tree['orphan'].refresh_from_db()
    assert tree['orphan'].name == 'Subtraction'
    assert 'Would rename' in out


def test_rename_moves_no_questions(tree):
    tree['q'](tree['orphan'])
    run(rename=tree['orphan'].id, new_name='Take Away')
    assert Question.objects.filter(topic=tree['orphan']).count() == 1


def test_rename_needs_a_new_name(tree):
    with pytest.raises(CommandError):
        run(rename=tree['orphan'].id)


def test_rename_needs_an_id(tree):
    with pytest.raises(CommandError):
        run(new_name='Take Away')


def test_rename_refuses_an_empty_name(tree):
    with pytest.raises(CommandError):
        run(rename=tree['orphan'].id, new_name='   ')


def test_rename_refuses_a_slug_already_used_in_the_subject(tree):
    with pytest.raises(CommandError):
        run(rename=tree['orphan'].id, new_name='Take Away', new_slug='number-td')
    tree['orphan'].refresh_from_db()
    assert tree['orphan'].slug == 'sub-td'


def test_rename_rejects_an_unknown_topic(tree):
    with pytest.raises(CommandError):
        run(rename=999999, new_name='Take Away')


def test_rename_and_merge_together_are_refused(tree):
    with pytest.raises(CommandError):
        run(rename=tree['orphan'].id, new_name='X',
            keep=tree['addition'].id, absorb=str(tree['addition_dupe'].id))


def test_rename_and_reparent_together_are_refused(tree):
    with pytest.raises(CommandError):
        run(rename=tree['orphan'].id, new_name='X', reparent=tree['orphan'].id)
