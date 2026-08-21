"""Question-bank health dashboard (superuser only).

Reads QuestionHealthSnapshot rows written by ``record_question_health`` (cron).
Mirrors the ops dashboard: same superuser gate, same dark admin theme, same
"stale data" honesty when the recorder has stopped.
"""
from datetime import timedelta

from django.shortcuts import render
from django.utils import timezone
from django.views import View

# Single source of truth for the superuser gate (same as ops / usage).
from billing.views_admin import SuperuserRequiredMixin

from .models import QuestionHealthSnapshot

# A daily recorder is considered stalled after two missed days, so a single
# skipped cron run does not cry wolf.
STALE_AFTER_HOURS = 48

TREND_POINTS = 30

# Human labels for the issue codes, so the dashboard does not make a
# super-admin decode SCREAMING-KEBAB-CASE.
CODE_LABELS = {
    'NO-CORRECT': 'No correct option',
    'MULTI-CORRECT': 'Several options marked correct',
    'DUPLICATE-OPTION': 'Duplicate option text',
    'EQUIVALENT-OPTION': 'Distractor equals the answer',
    'TOO-FEW-OPTIONS': 'Too few options',
    'BLANK-OPTION': 'Blank option',
    'WRONG-ANSWER-KEY': 'Answer key is wrong',
    'DUPLICATE-VALUE': 'Two distractors are the same value',
}

# Codes that cannot mismark a student — shown, but never in the headline.
ADVISORY_LABELS = {'DUPLICATE-VALUE'}

# The live check walks every matching question and runs the full verifier over
# it, so it is bounded rather than open-ended: an unfiltered run over the whole
# bank would tie up a gunicorn worker. When the cap bites the page SAYS so —
# a truncated list that looks complete is worse than no list.
CHECK_DEFAULT_LIMIT = 500
CHECK_MAX_LIMIT = 5000


class QuestionHealthDashboardView(SuperuserRequiredMixin, View):
    def get(self, request):
        latest = QuestionHealthSnapshot.objects.first()   # Meta.ordering
        history = list(QuestionHealthSnapshot.objects.all()[:TREND_POINTS])

        latest_stale = bool(
            latest
            and latest.created_at
            < timezone.now() - timedelta(hours=STALE_AFTER_HOURS)
        )

        issues = []
        if latest:
            for code, count in sorted(
                    latest.issue_counts.items(), key=lambda kv: -kv[1]):
                issues.append({
                    'code': code,
                    'label': CODE_LABELS.get(code, code),
                    'count': count,
                    'advisory': code in ADVISORY_LABELS,
                })

        # Oldest-first for the trend line; the query is newest-first.
        trend = [
            {
                'at': snapshot.created_at,
                'health': snapshot.health_percent,
                'blocking': snapshot.questions_blocking,
            }
            for snapshot in reversed(history)
        ]

        return render(request, 'admin_dashboard/question_health/dashboard.html', {
            'latest': latest,
            'latest_stale': latest_stale,
            'stale_after_hours': STALE_AFTER_HOURS,
            'issues': issues,
            'trend': trend,
            'flagged': (latest.flagged_questions if latest else []),
        })


def _ids(request, key):
    """Multi-select GET values as a list of ints, ignoring anything unparseable."""
    out = []
    for raw in request.GET.getlist(key):
        raw = (raw or '').strip()
        if not raw:
            continue
        try:
            out.append(int(raw))
        except ValueError:
            continue
    return out


class QuestionCheckView(SuperuserRequiredMixin, View):
    """Run the answer verifier on demand over a filtered slice of the bank.

    The dashboard above reports yesterday's cron snapshot for the WHOLE bank.
    This answers a different question — "what is wrong in Year 7 Fractions,
    right now?" — and puts Edit and Delete next to each finding, so a
    super-admin can fix what it finds without leaving the page or opening a
    shell.

    Editing and deleting reuse the existing ``edit_question`` /
    ``delete_question`` views rather than reimplementing them: those already
    carry the permission checks and the audit-log entry, and a second delete
    path that skipped either would be a hole.
    """

    def get(self, request):
        from classroom.models import Level, Subject, Topic

        from .answer_verification import verify_question
        from .models import Question

        subject_ids = _ids(request, 'subject')
        level_ids = _ids(request, 'level')
        topic_ids = _ids(request, 'topic')
        include_advisory = request.GET.get('advisory') == '1'

        try:
            limit = int(request.GET.get('limit') or CHECK_DEFAULT_LIMIT)
        except ValueError:
            limit = CHECK_DEFAULT_LIMIT
        limit = max(1, min(limit, CHECK_MAX_LIMIT))

        # The filter lists themselves. Topics are grouped by subject so the
        # picker stays usable when several subjects are in play.
        subjects = list(Subject.objects.order_by('name'))
        levels = list(Level.objects.filter(level_number__lte=13)
                      .order_by('level_number'))
        topic_qs = Topic.objects.select_related('subject').order_by(
            'subject__name', 'name')
        if subject_ids:
            topic_qs = topic_qs.filter(subject_id__in=subject_ids)
        topics = list(topic_qs)

        ran = request.GET.get('run') == '1'
        rows = []
        scanned = 0
        truncated = False

        if ran:
            qs = (Question.objects
                  .select_related('level', 'topic', 'topic__parent',
                                  'topic__subject', 'school')
                  .prefetch_related('answers')
                  .order_by('id'))
            if subject_ids:
                qs = qs.filter(topic__subject_id__in=subject_ids)
            if level_ids:
                qs = qs.filter(level_id__in=level_ids)
            if topic_ids:
                qs = qs.filter(topic_id__in=topic_ids)

            # One extra row tells us the cap bit without a second COUNT query.
            batch = list(qs[:limit + 1])
            truncated = len(batch) > limit
            batch = batch[:limit]

            for question in batch:
                scanned += 1
                issues, _verified = verify_question(question)
                if not include_advisory:
                    issues = [i for i in issues if i.code not in ADVISORY_LABELS]
                if not issues:
                    continue
                rows.append({
                    'q': question,
                    'issues': [{
                        'code': i.code,
                        'label': CODE_LABELS.get(i.code, i.code),
                        'detail': i.detail,
                        'advisory': i.code in ADVISORY_LABELS,
                    } for i in issues],
                    # A question that reads oddly on its own may be perfectly
                    # clear with its diagram, so the evidence is shown rather
                    # than the row being silently dropped.
                    'has_image': bool(question.image),
                    'specs': [name for name in (
                        'grid_spec', 'shape_spec', 'plane_spec', 'graph_spec',
                        'number_line_spec', 'table_spec',
                    ) if getattr(question, name, None)],
                })

        return render(request, 'admin_dashboard/question_health/check.html', {
            'subjects': subjects,
            'levels': levels,
            'topics': topics,
            'selected_subjects': subject_ids,
            'selected_levels': level_ids,
            'selected_topics': topic_ids,
            'include_advisory': include_advisory,
            'limit': limit,
            'max_limit': CHECK_MAX_LIMIT,
            'ran': ran,
            'rows': rows,
            'scanned': scanned,
            'truncated': truncated,
            'querystring': request.GET.urlencode(),
        })
