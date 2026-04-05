"""
homework/views_htmx.py
======================
HTMX partial views for homework module.
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from classroom.models import Topic


@login_required
def subtopics_for_topic(request):
    """Return subtopic checkboxes when a topic is selected."""
    topic_id = request.GET.get('topic')
    subtopics = []
    if topic_id:
        subtopics = Topic.objects.filter(
            parent_id=topic_id,
            is_active=True,
        ).order_by('order', 'name')
    return render(request, 'homework/partials/subtopics.html', {
        'subtopics': subtopics,
    })
