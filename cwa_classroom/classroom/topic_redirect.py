"""Keep a link to a merged-away topic working.

``topic_merge.merge_topics`` collapses duplicated topics: it re-points every
row that referenced the absorbed topic onto the survivor, then deletes it. The
one thing it cannot re-point is a link that is already out in the world — a
bookmark, an open tab, a browser history entry, a URL in a message — and every
one of those becomes a bare Django 404 the moment the merge runs. A student who
practised "Fractions" last week clicks the same link and is told the page does
not exist, which is not what happened: the topic moved.

``resolve_topic`` is what a view whose URL carries a topic id uses in place of
``get_object_or_404``. It answers with the live topic, or with a redirect to
the survivor, or it 404s — and the 404 is reserved for an id that genuinely
resolves to nothing, because an alias makes a *moved* topic reachable, it does
not invent one.
"""
from django.http import Http404
from django.shortcuts import redirect

from .models import Topic, TopicAlias


def resolve_topic(topic_id, url_name, **url_kwargs):
    """Return ``(topic, None)``, or ``(None, response)`` when the id moved.

    ``url_name`` and ``url_kwargs`` describe the route to send the visitor back
    to with the survivor's id — the same view they asked for, so a redirected
    quiz link lands on a quiz rather than on a generic page.

    Raises ``Http404`` when the id is neither a live topic nor a retired one.

    The redirect is a 302, not a 301. A permanent redirect is the tidier answer
    on paper and is also the one answer that cannot be taken back: browsers
    cache it indefinitely, so a wrong target would outlive any fix we deployed.
    The alias row makes the hop free on every later visit anyway, so there is
    nothing to buy with that risk.
    """
    topic = Topic.objects.filter(id=topic_id).first()
    if topic is not None:
        return topic, None

    survivor = TopicAlias.resolve(topic_id)
    if survivor is None:
        raise Http404(f'No topic with id {topic_id}.')

    return None, redirect(url_name, topic_id=survivor.id, **url_kwargs)
