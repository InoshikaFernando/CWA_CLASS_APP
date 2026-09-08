"""Resolve a human topic name to the ``classroom.Topic`` rows it can mean.

Topics are a two-level ``strand › sub-topic`` tree, and
``import_global_questions`` matches them on ``(name, parent)`` — so one name
can legitimately be several rows, and questions for "Number Patterns" can sit
on the row itself, on a sibling row of the same name under another strand, or
on a sub-topic beneath it. Anything that asks "show me the X questions" has to
widen to all of them, or it reports a slice of the bank as the whole of it.

Matching the parent's name as well as the topic's own is what pulls a strand's
children in: searching "Number Patterns" finds
``Number Patterns › Sequences`` too.
"""
from django.db.models import Q


def topic_match_q(term, exact=False):
    """A ``Q`` matching topics by their own name, their parent's, or their slug.

    ``exact`` switches from substring to whole-name matching — use it when a
    loose term drags in a broader strand (searching "Number" otherwise matches
    every sub-topic of "Number and Algebra").
    """
    term = (term or '').strip()
    if not term:
        return Q()
    if exact:
        return (Q(name__iexact=term) | Q(parent__name__iexact=term)
                | Q(slug__iexact=term))
    return (Q(name__icontains=term) | Q(parent__name__icontains=term)
            | Q(slug__icontains=term))


def matching_topics(term, exact=False):
    """The Topic rows *term* resolves to, ordered strand-then-name."""
    from classroom.models import Topic

    if not (term or '').strip():
        return []
    return list(Topic.objects.filter(topic_match_q(term, exact=exact))
                .select_related('parent', 'subject')
                .order_by('parent__name', 'name'))


def topic_path(topic):
    """'Strand › Sub-topic' for a sub-topic, the plain name for a strand."""
    if topic is None:
        return '(no topic)'
    if topic.parent_id:
        return f'{topic.parent.name} › {topic.name}'
    return topic.name
