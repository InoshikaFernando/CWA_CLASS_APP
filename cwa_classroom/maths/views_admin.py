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
from .question_review import USER_REPORTED

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
    # Raised from QuestionReport rows rather than by the verifier (CPP-398).
    # A question a student objected to is unhealthy even when every
    # deterministic check passes it — the verifier having no objection is
    # exactly the case the complaint is worth reading.
    USER_REPORTED: 'Reported by a user',
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

        from .answer_verification import Issue, verify_question
        from .models import Question
        from .question_review import ReviewState, report_detail

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
        cleared = 0
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

            # Reports and clearances for this batch, in two queries rather
            # than two per row (CPP-398).
            state = ReviewState([q.id for q in batch])

            for question in batch:
                scanned += 1
                # A person has looked at this one and passed it. Nothing more
                # to say about it until it is edited or reported again — which
                # is the whole point of the verdict.
                if state.is_cleared(question):
                    cleared += 1
                    continue
                issues, _verified = verify_question(question)
                reports = state.open_reports(question)
                if reports:
                    # Appended rather than merged into verify_question: the
                    # verifier reports what it can prove about the data, and
                    # "somebody objected" is not that kind of claim.
                    issues = list(issues) + [
                        Issue(USER_REPORTED, report_detail(reports))]
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
                    # The options themselves, so an answer key that no
                    # evaluator can settle ("666 in expanded form") can still
                    # be set from this page — tick one, choose "Use the answer
                    # I ticked". Without it the only route was the editor, one
                    # question at a time.
                    'options': list(question.answers.order_by('order', 'id')),
                    'needs_pick': any(i.code in PICKER_CODES for i in issues),
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
            'cleared': cleared,
            'bulk_actions': BULK_ACTIONS,
            'scanned': scanned,
            'truncated': truncated,
            'querystring': request.GET.urlencode(),
        })


# Fixes the check page can apply to a chosen set of questions. Each one is
# narrow and reversible-by-inspection: the audit log records the previous state
# so a bad run can be traced without a database restore.
BULK_ACTIONS = (
    ('auto', 'Fix automatically — try every fix that suits each problem'),
    ('set_answer_key', 'Use the answer I ticked in the row'),
    ('replace_duplicates', 'Replace duplicated options with distinct values'),
    ('delete_duplicates', 'Delete duplicated options (works on worded answers)'),
    ('pad_options', 'Add wrong answers (up to four options)'),
    ('to_short_answer', 'Change question type to Short Answer'),
    ('to_ai_graded', 'Convert to AI graded (Claude marks the written answer)'),
    ('trim_options', 'Trim to four options (keeps the correct one)'),
    ('fill_answer', 'Work out the missing answer (arithmetic only)'),
    ('fix_answer_key', 'Correct the answer key (arithmetic only)'),
    ('drop_blank_options', 'Delete blank answer options'),
    # Not repairs — verdicts (CPP-398). The deterministic checks are blunt, so
    # a question can be flagged and still be perfectly sound; before these the
    # only exits from such a row were to edit it needlessly or delete it, and
    # the same false positives came back on every run.
    ('mark_reviewed_correct', 'Reviewed and correct — clear it from this list'),
    ('mark_reviewed_broken', 'Reviewed — needs fixing (keep it listed)'),
)

# Which fixes address which finding, best first. Every code in CODE_LABELS
# must appear here: a problem the page reports but offers no route out of is
# how a reviewer ends up with a list they cannot act on. A test enforces it.
#
# Each code carries a CHAIN rather than a single fix, because the first-choice
# fix is usually the narrow one. 'Replace duplicated options' keeps the option
# count but only works on numbers; 'Delete duplicated options' works on any
# answer text but costs a choice. Listing both, in that order, is what makes
# the promise true for a bank whose options are mostly words — the earlier
# one-fix-per-code map was satisfied by a fix that skipped nine questions in
# ten.
FIXES_FOR_CODE = {
    'NO-CORRECT': ('fill_answer', 'set_answer_key'),
    'MULTI-CORRECT': ('fix_answer_key', 'delete_duplicates', 'set_answer_key'),
    'WRONG-ANSWER-KEY': ('fix_answer_key', 'set_answer_key'),
    'BLANK-OPTION': ('drop_blank_options',),
    'DUPLICATE-OPTION': ('replace_duplicates', 'delete_duplicates'),
    'DUPLICATE-CORRECT': ('replace_duplicates', 'delete_duplicates'),
    'EQUIVALENT-OPTION': ('replace_duplicates', 'delete_duplicates'),
    'DUPLICATE-VALUE': ('replace_duplicates', 'delete_duplicates'),
    'TOO-FEW-OPTIONS': ('pad_options', 'to_short_answer'),
    'TOO-MANY-OPTIONS': ('trim_options',),
    # A complaint is not a defect the machine can repair — the only route out
    # is a person looking. Both verdicts are manual (below), so 'auto' never
    # reaches this and a sweep can never dismiss somebody's report.
    USER_REPORTED: ('mark_reviewed_correct', 'mark_reviewed_broken'),
}

# Fixes that decide for themselves. 'set_answer_key' is deliberately excluded:
# it applies a judgement the reviewer made in the row, so running it inside an
# automatic sweep would either do nothing (no tick) or, worse, look like the
# machine had settled a question it cannot settle.
#
# 'to_ai_graded' is excluded for a different reason: it spends money and, for a
# school without the AI grading module, REMOVES the question from quizzes
# altogether (quiz.views.gradable_for). Neither is a consequence an automatic
# sweep may choose on a reviewer's behalf, so it stays a deliberate pick from
# the menu. It is absent from FIXES_FOR_CODE too, which is what actually keeps
# 'auto' away from it; this is the belt to that pair of braces.
#
# The two review verdicts are manual for the plainest reason of all: they record
# what a PERSON concluded. A sweep that wrote "reviewed and correct" would be
# the dashboard vouching for text nobody read.
MANUAL_FIXES = frozenset({'set_answer_key', 'to_ai_graded',
                          'mark_reviewed_correct', 'mark_reviewed_broken'})

# The codes whose only remaining route needs a person to tick an option. The
# check page renders that ticker inline for these rows, so the answer key can
# be set without opening the editor.
PICKER_CODES = frozenset(
    code for code, fixes in FIXES_FOR_CODE.items() if 'set_answer_key' in fixes
)


def auto_fix_sequence(codes):
    """Fixes to try, in order, for a question reporting ``codes``.

    Ordered by the chains above and de-duplicated, so a question with three
    duplicate faults tries 'replace_duplicates' once rather than three times.
    Blank rows are cleared first wherever they are present: nearly every other
    planner refuses outright on a question that still holds one.
    """
    ordered = []
    for code in sorted(codes, key=lambda c: c != 'BLANK-OPTION'):
        for fix in FIXES_FOR_CODE.get(code, ()):
            if fix not in MANUAL_FIXES and fix not in ordered:
                ordered.append(fix)
    return ordered


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
            Skipped, plan_answer_fill, plan_answer_key,
            plan_blank_removal, plan_padding, plan_repair)
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

        changed, skipped, rubricless = 0, [], []
        for question in questions:
            answers = list(question.answers.order_by('order', 'id'))
            if action == 'auto':
                applied, why = self._auto(request, question, answers)
            else:
                applied, why = self._one(request, action, question, answers)

            if not applied:
                skipped.append(f'Q{question.id}: {why}')
                continue

            changed += 1
            for name, detail in applied:
                if detail.get('needs_rubric'):
                    rubricless.append(question.id)
                log_event(
                    user=request.user, school=question.school,
                    category='data_change', action=f'bulk_fix_{name}',
                    detail={'question_id': question.id, **detail},
                    request=request,
                )

        if changed:
            # "3 questions fixed" would be a lie for a verdict — nothing about
            # the question changed, a person's reading of it was recorded.
            noun = ('reviewed' if action.startswith('mark_reviewed_')
                    else 'fixed')
            messages.success(
                request,
                f'{changed} question{"s" if changed != 1 else ""} {noun}.')
        for note in skipped:
            # Reported individually rather than as a count: "3 skipped" tells
            # the reviewer nothing about what still needs a human.
            messages.warning(request, f'Left alone — {note}')

        if rubricless:
            # Converted, but not finished. Without a marking guide the grader
            # judges the answer on the question text alone, so the mark drifts
            # between two students who wrote the same thing. Saying so here is
            # the difference between a job done and a job that looks done.
            messages.warning(
                request,
                'AI graded, but no marking guide yet — '
                f'{", ".join(f"Q{qid}" for qid in rubricless)}. '
                'Add a grading rubric in the editor saying what a correct '
                'answer must contain, or the AI marks them inconsistently.')

        return redirect(request.POST.get('next')
                        or 'question_check_admin_dashboard')

    def _one(self, request, action, question, answers):
        """Apply a single named fix. Returns ``([(action, detail)], reason)``.

        An empty first element means nothing happened, and the reason says why
        — reported to the reviewer verbatim rather than counted, because "3
        skipped" tells them nothing about what still needs a person.
        """
        from .duplicate_repair import Skipped

        try:
            with transaction.atomic():
                detail = self._apply(action, question, answers, request=request)
        except Skipped as exc:
            return [], str(exc)
        if detail is None:
            return [], 'nothing to change'
        return [(action, detail)], ''

    def _auto(self, request, question, answers):
        """Try each fix that suits this question's actual problems, in turn.

        Re-verifies the question rather than trusting the codes the page was
        rendered with: the row may have been fixed by an earlier run, or by
        someone else, and applying a repair to a stale finding is how a good
        question gets damaged.

        Stops at the first fix that changes something. Fixes are not chained
        further in one pass on purpose — after a change the findings differ,
        and the reviewer should see the new state before more is done to it.
        """
        from .answer_verification import verify_question
        from .duplicate_repair import Skipped

        issues, _ = verify_question(question)
        codes = {issue.code for issue in issues}
        if not codes:
            return [], 'nothing wrong with it now'

        sequence = auto_fix_sequence(codes)
        if not sequence:
            return [], 'no automatic fix suits this problem'

        reasons = []
        for name in sequence:
            try:
                with transaction.atomic():
                    detail = self._apply(name, question, answers,
                                         request=request)
            except Skipped as exc:
                reasons.append(f'{name}: {exc}')
                continue
            if detail is None:
                reasons.append(f'{name}: nothing to change')
                continue
            return [(name, detail)], ''

        # Every fix declined. The reviewer is told what each one refused and
        # why, which is the difference between "needs a human" and "the tool
        # is broken".
        needs_pick = codes & PICKER_CODES
        tail = ('  Tick the right answer in the row and choose '
                '"Use the answer I ticked".' if needs_pick else '')
        return [], '; '.join(reasons) + tail

    def _apply(self, action, question, answers, request=None):
        """Perform one fix. Returns an audit detail dict, or None for a no-op."""
        from .duplicate_repair import (
            Skipped, plan_ai_grading, plan_answer_fill, plan_answer_key,
            plan_blank_removal, plan_chosen_answer_key, plan_duplicate_removal,
            plan_padding, plan_repair, plan_type_change)
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

        if action == 'fix_answer_key':
            to_flag, to_unflag = plan_answer_key(question, answers)
            if not to_flag and not to_unflag:
                return None
            for answer in to_flag:
                answer.is_correct = True
                answer.save(update_fields=['is_correct'])
            for answer in to_unflag:
                answer.is_correct = False
                answer.save(update_fields=['is_correct'])
            return {'flagged': [a.answer_text for a in to_flag],
                    'unflagged': [a.answer_text for a in to_unflag]}

        if action == 'drop_blank_options':
            blanks = plan_blank_removal(question, answers)
            if not blanks:
                return None
            # Recorded before the delete: a row removed by mistake cannot be
            # recovered from the row itself.
            detail = {'deleted_ids': [a.id for a in blanks]}
            for answer in blanks:
                answer.delete()
            return detail

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

        if action == 'delete_duplicates':
            doomed = plan_duplicate_removal(question, answers)
            if not doomed:
                return None
            detail = {'deleted': [{'answer_id': o.id, 'was': o.answer_text}
                                  for o in doomed]}
            for option in doomed:
                option.delete()
            return detail

        if action == 'set_answer_key':
            # One radio group per question on the check page, so a single
            # submission can set the key on many rows at once.
            raw = (request.POST.get(f'answer_key_{question.id}', '')
                   if request is not None else '')
            try:
                chosen_id = int(raw)
            except (TypeError, ValueError):
                raise Skipped('no answer was ticked for this question')
            to_flag, to_unflag = plan_chosen_answer_key(
                question, chosen_id, answers)
            if not to_flag and not to_unflag:
                return None
            for answer in to_flag:
                answer.is_correct = True
                answer.save(update_fields=['is_correct'])
            for answer in to_unflag:
                answer.is_correct = False
                answer.save(update_fields=['is_correct'])
            return {'flagged': [a.answer_text for a in to_flag],
                    'unflagged': [a.answer_text for a in to_unflag]}

        if action in ('mark_reviewed_correct', 'mark_reviewed_broken'):
            from .models import QuestionReview
            from .question_review import ReviewState, record_review

            verdict = (QuestionReview.VERDICT_CORRECT
                       if action == 'mark_reviewed_correct'
                       else QuestionReview.VERDICT_BROKEN)
            user = getattr(request, 'user', None) if request else None

            # Re-clearing a question already cleared would stack identical rows
            # and read as work done. Saying "nothing to change" is the honest
            # answer, and an edit or a fresh report since the last verdict makes
            # this false again — which is when a new review IS worth recording.
            if (verdict == QuestionReview.VERDICT_CORRECT
                    and ReviewState([question.id]).is_cleared(question)):
                return None

            review = record_review(question, user=user, verdict=verdict)
            return {'verdict': verdict, 'review_id': review.id,
                    'question_updated_at': (
                        question.updated_at.isoformat()
                        if question.updated_at else None)}

        if action == 'to_short_answer':
            if not plan_type_change(question, answers):
                return None
            was = question.question_type
            question.question_type = 'short_answer'
            question.save(update_fields=['question_type', 'updated_at'])
            return {'question_type_was': was, 'question_type_now': 'short_answer'}

        if action == 'to_ai_graded':
            from .models import Question

            if not plan_ai_grading(question, answers):
                return None
            was = question.validation_type
            question.validation_type = Question.VALIDATION_AI
            question.save(update_fields=['validation_type', 'updated_at'])
            # A rubric is what the grader marks AGAINST, so a question converted
            # without one is only half-converted — it will be marked on the
            # question text alone, inconsistently. The caller turns this flag
            # into a warning naming the question, rather than letting the run
            # report a clean success over work still to do.
            return {'validation_type_was': was,
                    'validation_type_now': Question.VALIDATION_AI,
                    'needs_rubric': not (question.grading_rubric or '').strip()}

        return None
