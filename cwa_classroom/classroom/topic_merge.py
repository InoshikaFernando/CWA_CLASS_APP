"""
Topic inventory and merge — see what the topic tree actually contains, and
collapse rows that should be one.

The same topic gets created twice: "Fractions" alongside "Fraction", "Addition"
under two different parents, a subject imported once per source. Nothing is
broken by that on its own, but it splits a strand in two: a teacher filtering
to one copy silently misses every question filed under the other, and the
question-health drill-down reports the same strand under two names.

This module deliberately does NOT guess which topics mean the same thing.
Fuzzy name matching ("Fraction" ≈ "Fractions") reads well in a demo and is
wrong often enough to be dangerous — "Mass" and "Masses", "Time" and "Times"
are not obviously the same call, and a merge is not reversible. So the service
reports FACTS — what exists, what each row holds, and what is structurally
inconsistent — and a human decides what to combine.

Merging re-points everything that pointed at the absorbed rows onto the
survivor, then DELETES them. Unlike the student merge next door there is no
financial or identity history to preserve, and leaving an inactive twin in the
picker would defeat the point.

Re-pointing walks ``_meta.related_objects`` rather than a hand-written list of
models, so a topic FK added to a new app later is carried too instead of being
quietly left behind on a row that is about to disappear.
"""
import logging
import re
from collections import defaultdict

from django.db import IntegrityError, transaction
from django.db.models import Count, Q

from .models import Subject, Topic

logger = logging.getLogger(__name__)

# Reverse relations handled explicitly or deliberately not carried over.
_SKIP_MODELS = {
    'classroom.topic',      # self-FK (parent) — re-parented explicitly below
    'admin.logentry',
    'audit.auditlog',
}


def question_count(topic):
    """Questions filed directly under this topic."""
    from maths.models import Question
    return Question.objects.filter(topic_id=topic.id).count()


def topic_summary(topic, questions=None, subtopics=None):
    """What a reviewer needs to choose a survivor — not just the name."""
    return {
        'topic': topic,
        'id': topic.id,
        'name': topic.name,
        'slug': topic.slug,
        'subject': topic.subject.name if topic.subject_id else None,
        'subject_id': topic.subject_id,
        'parent': topic.parent.name if topic.parent_id else None,
        'parent_id': topic.parent_id,
        'questions': (question_count(topic) if questions is None else questions),
        'subtopics': (Topic.objects.filter(parent_id=topic.id).count()
                      if subtopics is None else subtopics),
        'is_active': topic.is_active,
    }


def topic_inventory(subject_ids=None):
    """Every topic, grouped by subject, with what each one holds.

    The whole tree in one list is the thing that makes a duplicate obvious to a
    human: two "Addition" rows sitting next to each other, one with 42
    questions and one with none, need no algorithm to interpret.
    """
    topics = (Topic.objects
              .select_related('subject', 'parent')
              .annotate(n_questions=Count('maths_questions', distinct=True),
                        n_subtopics=Count('subtopics', distinct=True))
              .order_by('subject__name', 'parent__name', 'name'))
    if subject_ids:
        topics = topics.filter(subject_id__in=subject_ids)

    by_subject = {}
    for topic in topics:
        entry = by_subject.setdefault(topic.subject_id, {
            'subject_id': topic.subject_id,
            'subject': topic.subject.name if topic.subject_id else '(none)',
            'topics': [],
            'questions': 0,
        })
        summary = topic_summary(topic, questions=topic.n_questions,
                                subtopics=topic.n_subtopics)
        entry['topics'].append(summary)
        entry['questions'] += topic.n_questions

    return sorted(by_subject.values(), key=lambda s: s['subject'])


def exact_name_clashes(subject_ids=None):
    """Topics sharing a name with another topic in the SAME subject.

    Not a guess and not a suggestion — two rows literally named "Addition"
    under Mathematics is a fact, and it is the case that actually bit: the
    picker shows the name twice with no way to tell them apart.

    Case and surrounding whitespace are ignored, because "Addition " and
    "addition" are the same name to everyone reading the picker. Nothing
    further is inferred.
    """
    groups = defaultdict(list)
    for subject in topic_inventory(subject_ids):
        for summary in subject['topics']:
            key = (summary['subject_id'], (summary['name'] or '').strip().lower())
            groups[key].append(summary)

    clashes = [
        {
            'subject': members[0]['subject'],
            'subject_id': members[0]['subject_id'],
            'name': members[0]['name'],
            'members': members,
            'total_questions': sum(m['questions'] for m in members),
        }
        for members in groups.values() if len(members) > 1
    ]
    clashes.sort(key=lambda c: (-c['total_questions'], c['subject'], c['name']))
    return clashes


# Words that carry no meaning in a topic name, so their presence or absence
# does not make two names different: "Addition of Fractions" and "Addition
# Fractions" are one topic that somebody typed twice.
_FILLER_WORDS = frozenset({
    'a', 'an', 'and', 'for', 'in', 'of', 'on', 'the', 'to', 'using', 'with',
})


def _singular(word):
    """Crude, deliberate stemming — plurals only, no dictionary.

    A topic bank writes "Fraction" and "Fractions", "Place Value" and "Place
    Values". Nothing here tries to be a linguist: the rules are the four that
    cover school topic names, and a word too short to be safely trimmed is
    left alone.
    """
    if len(word) <= 3 or word.endswith('ss'):
        return word
    if word.endswith('ies'):
        return word[:-3] + 'y'
    if word.endswith(('ches', 'shes', 'ses', 'xes', 'zes')):
        return word[:-2]
    if word.endswith('s'):
        return word[:-1]
    return word


def normalised_name(name):
    """The comparison key behind :func:`near_duplicate_names`.

    Every step is a rewrite anyone can replay by hand, which is the point:
    two names group together because they reduce to the same string, not
    because an algorithm scored them similar. Case, punctuation, ``&`` versus
    ``and``, filler words, plurals and word ORDER are all discarded, so
    "Fractions & Decimals" and "Decimals and Fraction" share a key.

    Discarding word order is the one rule that can surprise, and it is here
    because reordered names are a real duplicate shape in this bank, not a
    hypothetical one.
    """
    text = (name or '').lower().replace('&', ' and ')
    text = re.sub(r'[^a-z0-9]+', ' ', text)
    words = [_singular(w) for w in text.split() if w not in _FILLER_WORDS]
    return ' '.join(sorted(words))


def near_duplicate_names(subject_ids=None):
    """Topics in one subject whose names reduce to the same key.

    The module rule is that nothing here guesses what a topic MEANS, and this
    keeps it: normalisation is not fuzzy matching. There is no similarity
    threshold to tune and no ranking — two names either reduce to the same
    string or they do not, and the answer is the same on every run.

    That still does not make a group a decision. "Mass" and "Masses" reduce
    alike and probably are one topic; "Time" and "Times" reduce alike and may
    well not be. So this reports the cluster with what each row holds and
    leaves the survivor to a human, exactly as the exact matcher does.

    Groups that are only exact clashes are left out — ``exact_name_clashes``
    already reports those, and repeating them would bury the findings that
    are new here.
    """
    groups = defaultdict(list)
    for subject in topic_inventory(subject_ids):
        for summary in subject['topics']:
            key = (summary['subject_id'], normalised_name(summary['name']))
            groups[key].append(summary)

    clusters = []
    for (_subject_id, key), members in groups.items():
        if not key:
            continue
        distinct = {(m['name'] or '').strip().lower() for m in members}
        if len(distinct) < 2:
            continue        # one spelling: an exact clash, or nothing at all
        clusters.append({
            'subject': members[0]['subject'],
            'subject_id': members[0]['subject_id'],
            'key': key,
            'names': sorted(distinct),
            'members': sorted(members, key=lambda m: -m['questions']),
            'total_questions': sum(m['questions'] for m in members),
        })
    clusters.sort(key=lambda c: (-c['total_questions'], c['subject'], c['key']))
    return clusters


def structural_issues(subject_ids=None):
    """Things that are wrong regardless of anyone's naming preferences.

    Each finding is checkable from the row itself, so none of them needs a
    judgement call about what a topic "means".
    """
    issues = []

    for clash in exact_name_clashes(subject_ids):
        issues.append({
            'code': 'DUPLICATE-NAME',
            'subject': clash['subject'],
            'detail': (f'{len(clash["members"])} topics named '
                       f'{clash["name"]!r} — the picker shows the same name '
                       f'more than once'),
            'topics': clash['members'],
        })

    for subject in topic_inventory(subject_ids):
        for summary in subject['topics']:
            topic = summary['topic']

            if summary['questions'] == 0 and summary['subtopics'] == 0:
                issues.append({
                    'code': 'EMPTY-TOPIC',
                    'subject': summary['subject'],
                    'detail': 'no questions and no subtopics',
                    'topics': [summary],
                })

            if not summary['is_active'] and summary['questions']:
                issues.append({
                    'code': 'INACTIVE-WITH-QUESTIONS',
                    'subject': summary['subject'],
                    'detail': (f'marked inactive but still holds '
                               f'{summary["questions"]} question(s) — they are '
                               f'hidden without being moved'),
                    'topics': [summary],
                })

            if (topic.parent_id
                    and topic.parent.subject_id != topic.subject_id):
                issues.append({
                    'code': 'PARENT-IN-OTHER-SUBJECT',
                    'subject': summary['subject'],
                    'detail': (f'parent {topic.parent.name!r} belongs to '
                               f'{topic.parent.subject.name}, not '
                               f'{summary["subject"]}'),
                    'topics': [summary],
                })

    return issues


def subject_name_clashes():
    """Subjects sharing a name — the reason the picker lists Mathematics twice.

    Reported, not merged: a subject can be a school's own custom copy
    (``school`` set) rather than a mistake, and telling those apart is a
    judgement call for a human.
    """
    groups = defaultdict(list)
    for subject in Subject.objects.select_related('school').annotate(
            n_topics=Count('topics', distinct=True)).order_by('name'):
        groups[(subject.name or '').strip().lower()].append({
            'id': subject.id,
            'name': subject.name,
            'slug': subject.slug,
            'school': subject.school.name if subject.school_id else None,
            'topics': subject.n_topics,
            'is_active': subject.is_active,
        })
    return [members for members in groups.values() if len(members) > 1]



def top_level_topics_with_questions(subject_ids=None):
    """Top-level rows holding questions directly — the picker never offers them.

    The student year page groups topics as ``strand > sub-topic`` and keeps
    only the strands that HAVE sub-topics, and the topic quiz then filters on
    one exact topic row (``maths.views``). So a question filed straight onto a
    strand is not offered by the topic picker at all; it surfaces only in level
    practice, which filters on level alone.

    Questions land there when an importer cannot match the topic name it was
    given: the homework PDF path falls back to
    ``Topic.objects.filter(subject=subject).first()`` rather than creating the
    topic, and that first row is a strand.

    Reported, never fixed automatically — whether those questions belong under
    an existing sub-topic, a new one, or a different strand entirely is a
    judgement call about their content.
    """
    topics = (Topic.objects
              .filter(parent__isnull=True)
              .select_related('subject')
              .annotate(n_questions=Count('maths_questions', distinct=True),
                        n_subtopics=Count('subtopics', distinct=True))
              .order_by('subject__name', 'name'))
    if subject_ids:
        topics = topics.filter(subject_id__in=subject_ids)
    return [topic_summary(t, questions=t.n_questions, subtopics=t.n_subtopics)
            for t in topics if t.n_questions]


def validate_reparent(topic, parent):
    """Refuse a re-parent that would break the two-level strand > sub-topic tree.

    ``parent=None`` (promoting a row to a strand) is always allowed; everything
    else has to keep the tree two deep, because that shape is assumed
    throughout — ``topic_path``, the export's title/sub-title grouping, and the
    year page's strand grouping all read exactly two levels.
    """
    if parent is None:
        return True, ''
    if topic.id == parent.id:
        return False, 'a topic cannot be its own parent'
    if topic.subject_id != parent.subject_id:
        return False, (f'different subjects ({topic.subject} vs '
                       f'{parent.subject}) — a sub-topic must sit under a '
                       f'strand of its own subject')
    if parent.parent_id:
        return False, (f'{parent.name!r} is itself a sub-topic of '
                       f'{parent.parent.name!r} — nesting under it would make '
                       f'a three-level tree')
    if Topic.objects.filter(parent_id=topic.id).exists():
        return False, (f'{topic.name!r} has sub-topics of its own — moving it '
                       f'under a strand would make a three-level tree')
    return True, ''

def validate_merge(keep, absorbed):
    """Refuse merges that would move questions somewhere they don't belong."""
    if keep.id == absorbed.id:
        return False, 'a topic cannot be merged into itself'
    if keep.subject_id != absorbed.subject_id:
        return False, (f'different subjects ({absorbed.subject} vs '
                       f'{keep.subject}) — merging would move questions out '
                       f'of their subject')
    if absorbed.id == keep.parent_id:
        return False, (f'{absorbed.name!r} is the parent of {keep.name!r} — '
                       f'merging a parent into its own child would flatten '
                       f'the strand')
    return True, ''


def merge_topics(keep, absorbed_list, actor=None, request=None):
    """Re-point everything at ``keep``, then delete each absorbed topic.

    Returns a summary dict. Raises ValueError if any pair fails a guardrail —
    a partial merge is worse than none, so validation happens up front for the
    whole batch rather than per row.
    """
    for absorbed in absorbed_list:
        ok, err = validate_merge(keep, absorbed)
        if not ok:
            raise ValueError(
                f'Refusing to merge {absorbed.name!r} into {keep.name!r}: {err}')

    summary = {
        'keep_id': keep.id,
        'keep_name': keep.name,
        'absorbed': [],
        'repointed': defaultdict(int),
        'skipped_collisions': defaultdict(int),
        'reparented': 0,
    }

    with transaction.atomic():
        for absorbed in absorbed_list:
            for rel in absorbed._meta.related_objects:
                model = rel.related_model
                key = f'{model._meta.app_label}.{model._meta.model_name}'
                if key in _SKIP_MODELS:
                    continue
                field = rel.field
                label = f'{model._meta.app_label}.{model.__name__}'

                if rel.many_to_many:
                    # e.g. HomeworkAssignment.topics — add the survivor, drop
                    # the absorbed row, without disturbing other topics.
                    accessor = rel.get_accessor_name()
                    for obj in getattr(absorbed, accessor).all():
                        through = getattr(obj, field.name)
                        through.add(keep)
                        through.remove(absorbed)
                        summary['repointed'][label] += 1
                    continue

                for obj in model.objects.filter(**{field.name: absorbed.id}):
                    setattr(obj, field.attname, keep.id)
                    try:
                        with transaction.atomic():
                            obj.save(update_fields=[field.attname])
                        summary['repointed'][label] += 1
                    except IntegrityError:
                        # The survivor already holds the equivalent row (a
                        # unique constraint, e.g. one statistics row per
                        # topic+level). Nothing is lost by leaving it: the
                        # absorbed row is about to be deleted with it.
                        summary['skipped_collisions'][label] += 1

            # Children of the absorbed topic become children of the survivor,
            # rather than being orphaned by the delete (parent is SET_NULL).
            moved = Topic.objects.filter(parent_id=absorbed.id).update(
                parent_id=keep.id)
            summary['reparented'] += moved

            summary['absorbed'].append({
                'id': absorbed.id, 'name': absorbed.name, 'slug': absorbed.slug,
            })
            absorbed.delete()

    summary['repointed'] = dict(summary['repointed'])
    summary['skipped_collisions'] = dict(summary['skipped_collisions'])

    try:
        from audit.services import log_event
        log_event(
            user=actor, school=None, category='data_change',
            action='topics_merged', result='allowed',
            detail=summary, request=request,
        )
    except Exception:  # audit must never break the merge
        logger.exception('topic merge audit log failed')

    return summary
