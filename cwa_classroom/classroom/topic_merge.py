"""
Topic merge — detection and merge service for duplicated topic rows.

The same topic gets created twice: "Fractions" alongside "Fraction",
"Addition" alongside "Addition" under a different parent, a subject imported
once per source. Nothing is broken by that on its own, but it splits a strand
in two: a teacher filtering to one copy silently misses every question filed
under the other, and the question-health drill-down reports the same strand
under two names.

This module finds the likely duplicates and merges them. Unlike the student
merge next door, a topic carries no financial or identity history, so the
absorbed row is DELETED once everything that pointed at it has been re-pointed
at the survivor — leaving an inactive twin in the picker would defeat the point.

Re-pointing walks ``_meta.related_objects`` rather than a hand-written list of
models, so a topic FK added to a new app later is carried too instead of being
quietly left behind on a row that is about to disappear.
"""
import logging
import re
from collections import defaultdict

from django.db import IntegrityError, transaction

from .models import Topic

logger = logging.getLogger(__name__)

# Reverse relations handled explicitly or deliberately not carried over.
_SKIP_MODELS = {
    'classroom.topic',      # self-FK (parent) — re-parented explicitly below
    'admin.logentry',
    'audit.auditlog',
}

# Words that carry no meaning for matching a topic name. Without this,
# "Fractions" and "Fractions (Basic)" look unrelated to a plain comparison.
_NOISE = {'and', 'the', 'of', 'basic', 'basics', 'intro', 'introduction'}


def normalise(name):
    """A comparison key for a topic name.

    Case, punctuation, spacing and a trailing plural are all noise when asking
    "are these the same topic?" — 'Fraction', 'fractions' and 'Fractions '
    have to collide or the duplicates they represent stay invisible.
    """
    text = (name or '').strip().lower()
    text = re.sub(r'[^a-z0-9\s]+', ' ', text)
    words = []
    for word in text.split():
        if word in _NOISE:
            continue
        # Naive singularisation. Deliberately conservative: only a trailing
        # 's' on a word long enough that dropping it still means something,
        # so 'Mass' and 'Bus' are left alone.
        if len(word) > 3 and word.endswith('s') and not word.endswith('ss'):
            word = word[:-1]
        words.append(word)
    return ' '.join(words)


def question_count(topic):
    """Questions filed directly under this topic."""
    from maths.models import Question
    return Question.objects.filter(topic_id=topic.id).count()


def topic_summary(topic):
    """What a reviewer needs to choose the survivor, not just the name."""
    return {
        'topic': topic,
        'id': topic.id,
        'name': topic.name,
        'slug': topic.slug,
        'subject': topic.subject.name if topic.subject_id else None,
        'parent': topic.parent.name if topic.parent_id else None,
        'questions': question_count(topic),
        'subtopics': Topic.objects.filter(parent_id=topic.id).count(),
        'is_active': topic.is_active,
    }


def find_duplicate_groups(subject_ids=None):
    """Topics that look like the same topic, grouped.

    Grouped WITHIN a subject: two subjects legitimately both having a
    "Fractions" is not a duplicate, and merging across subjects would move
    questions out of the subject they belong to.
    """
    topics = (Topic.objects
              .select_related('subject', 'parent')
              .order_by('subject__name', 'name'))
    if subject_ids:
        topics = topics.filter(subject_id__in=subject_ids)

    buckets = defaultdict(list)
    for topic in topics:
        if not topic.subject_id:
            continue
        key = normalise(topic.name)
        if key:
            buckets[(topic.subject_id, key)].append(topic)

    groups = []
    for (subject_id, key), members in buckets.items():
        if len(members) < 2:
            continue
        summaries = [topic_summary(t) for t in members]
        groups.append({
            'subject_id': subject_id,
            'subject': members[0].subject.name,
            'key': key,
            'label': members[0].name,
            'members': summaries,
            'total_questions': sum(s['questions'] for s in summaries),
            # The copy holding the most questions is the sensible survivor:
            # it is the one already in use, and it minimises rows moved.
            'suggested_keep_id': max(summaries,
                                     key=lambda s: (s['questions'],
                                                    -s['id']))['id'],
        })

    groups.sort(key=lambda g: (-g['total_questions'], g['subject'], g['label']))
    return groups


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
