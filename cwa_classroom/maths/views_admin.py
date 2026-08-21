"""Question-bank health dashboard (superuser only).

Reads QuestionHealthSnapshot rows written by ``record_question_health`` (cron).
Mirrors the ops dashboard: same superuser gate, same dark admin theme, same
"stale data" honesty when the recorder has stopped.
"""
from datetime import timedelta

from django.contrib import messages
from django.db import transaction
from django.shortcuts import redirect, render
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
    'DUPLICATE-OPTION': 'Same wrong option listed twice',
    'DUPLICATE-CORRECT': 'Correct answer also listed as a distractor',
    'EQUIVALENT-OPTION': 'Distractor equals the answer',
    'TOO-FEW-OPTIONS': 'Too few options',
    'TOO-MANY-OPTIONS': 'More than 1 correct + 3 wrong answers',
    'BLANK-OPTION': 'Blank option',
    'WRONG-ANSWER-KEY': 'Answer key is wrong',
    'DUPLICATE-VALUE': 'Two distractors are the same value',
}

# Codes that cannot mismark a student — shown, but never in the headline.
# DUPLICATE-OPTION is here because a repeated WRONG option only makes the
# question read sloppily; the case that actually mismarks someone — the correct
# answer repeated as a distractor — is DUPLICATE-CORRECT, which is blocking.
ADVISORY_LABELS = {'DUPLICATE-VALUE', 'DUPLICATE-OPTION', 'TOO-MANY-OPTIONS'}

# Advisory, but shown WITHOUT ticking "include advisory issues".
#
# The house rule is one correct option and at most three wrong ones. A
# five-option question breaks it, but cannot mismark anybody — so it is
# advisory by severity and must stay out of the "can mismark a student" count,
# which was ten times too large once before from exactly this kind of padding.
#
# Hiding it by default had a cost of its own, though: a question with eight
# options looked unflagged, so the rule read as unenforced. Severity and
# visibility are different questions, and this is the code where they part
# company.
ALWAYS_SHOWN_ADVISORY = {'TOO-MANY-OPTIONS'}

# The Problem filter's options, blocking first so the ones that actually
# mismark a student are what a super-admin reaches for without scrolling.
PROBLEM_CHOICES = [
    {'code': code, 'label': label, 'advisory': code in ADVISORY_LABELS}
    for code, label in sorted(
        CODE_LABELS.items(), key=lambda kv: (kv[0] in ADVISORY_LABELS, kv[1]))
]

# The live check walks every matching question and runs the full verifier over
# it, so it is bounded rather than open-ended: an unfiltered run over the whole
# bank would tie up a gunicorn worker. When the cap bites the page SAYS so —
# a truncated list that looks complete is worse than no list.
# 1000 per run: the bank is ~19,500 questions, so 500 meant forty rounds of
# "Check next" to walk it once. A run of this size is still well inside a
# gunicorn worker's patience.
CHECK_DEFAULT_LIMIT = 1000
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


def _problem_codes(request):
    """Selected issue codes from the Problem filter, ignoring unknown ones."""
    known = set(CODE_LABELS)
    return [code for code in request.GET.getlist('problem') if code in known]


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
        problem_codes = _problem_codes(request)
        include_advisory = request.GET.get('advisory') == '1'

        # Asking for an advisory problem by name and then being told there are
        # none — because the advisory checkbox was left unticked — would read as
        # a clean bank. An explicit request for a code outranks the checkbox.
        if any(code in ADVISORY_LABELS for code in problem_codes):
            include_advisory = True

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

        # Where the last run stopped. The cap exists so one request cannot walk
        # the whole bank, but without a cursor "Run check" re-scanned the SAME
        # first N questions every time — the rest of the bank was unreachable
        # from this page, and a clean first page read as a clean bank.
        try:
            after = int(request.GET.get('after') or 0)
        except ValueError:
            after = 0

        ran = request.GET.get('run') == '1'
        rows = []
        scanned = 0
        truncated = False
        checked_through = 0
        total_matching = 0
        next_url = None
        restart_url = None

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

            # Two cheap counts so the page can say how far through the bank
            # this run got. Without them "500 scanned" gives no sense of
            # whether that is the whole job or a twentieth of it.
            total_matching = qs.count()
            done_before = qs.filter(id__lte=after).count() if after else 0

            if after:
                qs = qs.filter(id__gt=after)

            # One extra row tells us the cap bit without a third COUNT query.
            batch = list(qs[:limit + 1])
            truncated = len(batch) > limit
            batch = batch[:limit]
            checked_through = done_before + len(batch)

            if truncated and batch:
                params = request.GET.copy()
                params['after'] = str(batch[-1].id)
                next_url = f'{request.path}?{params.urlencode()}'
            if after:
                params = request.GET.copy()
                params.pop('after', None)
                restart_url = f'{request.path}?{params.urlencode()}'

            for question in batch:
                scanned += 1
                issues, _verified = verify_question(question)
                if not include_advisory:
                    issues = [i for i in issues
                              if i.code not in ADVISORY_LABELS
                              or i.code in ALWAYS_SHOWN_ADVISORY]
                if problem_codes:
                    # Keep only the problems asked for, so the rows shown and
                    # the checkboxes a bulk fix acts on are the same set.
                    issues = [i for i in issues if i.code in problem_codes]
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
            'selected_problems': problem_codes,
            'problem_choices': PROBLEM_CHOICES,
            'after': after,
            'checked_through': checked_through,
            'total_matching': total_matching,
            'next_url': next_url,
            'restart_url': restart_url,
            'include_advisory': include_advisory,
            'limit': limit,
            'max_limit': CHECK_MAX_LIMIT,
            'ran': ran,
            'rows': rows,
            'bulk_actions': BULK_ACTIONS,
            'scanned': scanned,
            'truncated': truncated,
            'querystring': request.GET.urlencode(),
        })


# Fixes the check page can apply to a chosen set of questions. Each one is
# narrow and reversible-by-inspection: the audit log records the previous state
# so a bad run can be traced without a database restore.
BULK_ACTIONS = (
    ('replace_duplicates', 'Replace duplicated options with distinct values'),
    ('pad_options', 'Add wrong answers (up to four options)'),
    ('to_short_answer', 'Change question type to Short Answer'),
    ('trim_options', 'Trim to four options (keeps the correct one)'),
    ('fill_answer', 'Work out the missing answer (arithmetic only)'),
)

# Padding target — four options is the house style for multiple choice.
PAD_TO = 4


class QuestionBulkFixView(SuperuserRequiredMixin, View):
    """Apply one fix to the questions a super-admin selected on the check page.

    Every question is reported on, whether it was changed or not. A bulk tool
    that quietly skips what it could not handle is how a reviewer comes away
    believing a bank is clean when it is not — the same failure this dashboard
    exists to prevent.
    """

    def post(self, request):
        from audit.services import log_event

        from .duplicate_repair import (
            Skipped, plan_answer_fill, plan_padding, plan_repair)
        from .models import Answer, Question

        action = request.POST.get('action', '')
        ids = []
        for raw in request.POST.getlist('question_id'):
            try:
                ids.append(int(raw))
            except (TypeError, ValueError):
                continue

        valid = {value for value, _label in BULK_ACTIONS}
        if action not in valid or not ids:
            messages.error(
                request,
                'Nothing to do — choose at least one question and a fix.')
            return redirect(request.POST.get('next')
                            or 'question_check_admin_dashboard')

        questions = (Question.objects
                     .filter(id__in=ids)
                     .prefetch_related('answers'))

        changed, skipped = 0, []
        for question in questions:
            answers = list(question.answers.order_by('order', 'id'))
            try:
                with transaction.atomic():
                    detail = self._apply(action, question, answers)
            except Skipped as exc:
                skipped.append(f'Q{question.id}: {exc}')
                continue

            if detail is None:
                skipped.append(f'Q{question.id}: nothing to change')
                continue

            changed += 1
            log_event(
                user=request.user, school=question.school,
                category='data_change', action=f'bulk_fix_{action}',
                detail={'question_id': question.id, **detail},
                request=request,
            )

        if changed:
            messages.success(
                request,
                f'{changed} question{"s" if changed != 1 else ""} fixed.')
        for note in skipped:
            # Reported individually rather than as a count: "3 skipped" tells
            # the reviewer nothing about what still needs a human.
            messages.warning(request, f'Left alone — {note}')

        return redirect(request.POST.get('next')
                        or 'question_check_admin_dashboard')

    def _apply(self, action, question, answers):
        """Perform one fix. Returns an audit detail dict, or None for a no-op."""
        from .duplicate_repair import (
            plan_answer_fill, plan_padding, plan_repair)
        from .models import Answer

        if action == 'replace_duplicates':
            edits = plan_repair(question, answers)
            if not edits:
                return None
            for answer, _old, new in edits:
                answer.answer_text = new
                answer.save(update_fields=['answer_text'])
            return {'edits': [{'answer_id': a.id, 'was': old, 'now': new}
                              for a, old, new in edits]}

        if action == 'fill_answer':
            plan = plan_answer_fill(question, answers)
            if plan is None:
                return None
            how, target = plan
            if how == 'flag':
                target.is_correct = True
                target.save(update_fields=['is_correct'])
                return {'flagged_correct': target.answer_text}
            order = max((a.order for a in answers), default=-1) + 1
            Answer.objects.create(question=question, answer_text=target,
                                  is_correct=True, order=order)
            return {'answer_added': target}

        if action == 'pad_options':
            additions = plan_padding(question, answers, target=PAD_TO)
            if not additions:
                return None
            order = max((a.order for a in answers), default=-1)
            for text in additions:
                order += 1
                Answer.objects.create(question=question, answer_text=text,
                                      is_correct=False, order=order)
            return {'added': additions}

        if action == 'trim_options':
            from .duplicate_repair import plan_trim

            surplus = plan_trim(question, answers, target=PAD_TO)
            if not surplus:
                return None
            removed = [{'answer_id': o.id, 'was': o.answer_text}
                       for o in surplus]
            for option in surplus:
                option.delete()
            return {'removed': removed}

        if action == 'to_short_answer':
            if question.question_type == 'short_answer':
                return None
            was = question.question_type
            question.question_type = 'short_answer'
            question.save(update_fields=['question_type', 'updated_at'])
            return {'question_type_was': was, 'question_type_now': 'short_answer'}

        return None
