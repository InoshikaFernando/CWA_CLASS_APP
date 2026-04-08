from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Count

from .models import (
    CodingLanguage,
    CodingTopic,
    CodingExercise,
    CodingProblem,
    StudentExerciseSubmission,
    StudentProblemSubmission,
    CodingTimeLog,
    calculate_coding_points,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_language_or_404(lang_slug):
    """Return active CodingLanguage by slug or raise 404."""
    return get_object_or_404(CodingLanguage, slug=lang_slug, is_active=True)


# ---------------------------------------------------------------------------
# Language selector  →  /coding/
# ---------------------------------------------------------------------------

@login_required
def language_selector(request):
    """Landing page — student picks a language to practise."""
    languages = list(CodingLanguage.objects.filter(is_active=True))
    total_languages = len(languages)

    # Topic and exercise counts per language
    topic_counts = {
        row['language_id']: row['total']
        for row in CodingTopic.objects.filter(language__is_active=True, is_active=True)
                                       .values('language_id')
                                       .annotate(total=Count('id'))
    }
    exercise_counts = {
        row['topic__language_id']: row['total']
        for row in CodingExercise.objects.filter(topic__language__is_active=True, is_active=True)
                                          .values('topic__language_id')
                                          .annotate(total=Count('id'))
    }

    # Languages the current student has started (at least one submission)
    started_lang_ids = set()
    if not request.user.is_staff:
        started_lang_ids = set(
            StudentExerciseSubmission.objects.filter(student=request.user)
            .values_list('exercise__topic__language_id', flat=True)
            .distinct()
        )

    # Attach computed fields to each language object
    for lang in languages:
        lang.topic_count = topic_counts.get(lang.id, 0)
        lang.exercise_count = exercise_counts.get(lang.id, 0)
        lang.is_started = lang.id in started_lang_ids

    started_count = len(started_lang_ids)

    # Badge labels per slug
    BADGE_MAP = {
        'python': ('Beginner friendly', 'starter'),
        'javascript': ('Most popular', 'popular'),
        'html': ('Great first step', 'starter'),
        'css': ('Updated', 'new'),
        'scratch': ('Visual blocks', 'visual'),
    }
    for lang in languages:
        badge = BADGE_MAP.get(lang.slug)
        lang.badge_label = badge[0] if badge else ''
        lang.badge_type = badge[1] if badge else ''

    return render(request, 'coding/language_selector.html', {
        'languages': languages,
        'total_languages': total_languages,
        'started_count': started_count,
        'subject_sidebar': 'coding',
    })


# ---------------------------------------------------------------------------
# Topic browsing
# ---------------------------------------------------------------------------

@login_required
def topic_list(request, lang_slug):
    """Show all active topics for a language.  /coding/<lang>/"""
    language = _get_language_or_404(lang_slug)
    topics = list(CodingTopic.objects.filter(language=language, is_active=True))

    # Aggregate total exercises and completed count per topic in two queries
    total_by_topic = {
        row['topic_id']: row['total']
        for row in CodingExercise.objects.filter(topic__in=topics, is_active=True)
                                          .values('topic_id')
                                          .annotate(total=Count('id'))
    }
    done_by_topic = {
        row['exercise__topic_id']: row['done']
        for row in StudentExerciseSubmission.objects.filter(
            student=request.user,
            exercise__topic__in=topics,
            is_completed=True,
        ).values('exercise__topic_id').annotate(done=Count('exercise_id', distinct=True))
    }

    # Icon colour palette (cycles through topics)
    ICON_COLOURS = ['blue', 'purple', 'green', 'amber', 'coral', 'pink', 'gray']

    topic_data = []
    for idx, t in enumerate(topics):
        total = total_by_topic.get(t.id, 0)
        completed = done_by_topic.get(t.id, 0)
        pct = round(completed / total * 100) if total else 0
        topic_data.append({
            'topic': t,
            'total': total,
            'completed': completed,
            'pct': pct,
            'is_started': completed > 0,
            'is_complete': total > 0 and completed >= total,
            'colour': ICON_COLOURS[idx % len(ICON_COLOURS)],
        })

    # Hero stat pills
    exercises_total = sum(td['total'] for td in topic_data)
    exercises_completed = sum(td['completed'] for td in topic_data)
    topics_started = sum(1 for td in topic_data if td['is_started'])
    completion_pct = round(exercises_completed / exercises_total * 100) if exercises_total else 0

    return render(request, 'coding/topic_list.html', {
        'language': language,
        'topic_data': topic_data,
        'topics_started': topics_started,
        'exercises_total': exercises_total,
        'exercises_completed': exercises_completed,
        'exercises_remaining': exercises_total - exercises_completed,
        'completion_pct': completion_pct,
        'subject_sidebar': 'coding',
    })


@login_required
def level_list(request, lang_slug, topic_slug):
    """Show Beginner / Intermediate / Advanced for a topic.  /coding/<lang>/topics/<topic>/"""
    language = _get_language_or_404(lang_slug)
    topic = get_object_or_404(CodingTopic, language=language, slug=topic_slug, is_active=True)

    levels = [
        CodingExercise.BEGINNER,
        CodingExercise.INTERMEDIATE,
        CodingExercise.ADVANCED,
    ]

    # Build completion info per level for the logged-in student
    LEVEL_META = {
        CodingExercise.BEGINNER:     {'stars': 1, 'colour': 'green',  'hint': 'Great starting point — core concepts explained simply.'},
        CodingExercise.INTERMEDIATE: {'stars': 2, 'colour': 'amber',  'hint': 'Apply what you know with more involved problems.'},
        CodingExercise.ADVANCED:     {'stars': 3, 'colour': 'rose',   'hint': 'Challenge yourself with complex, real-world scenarios.'},
    }

    level_data = []
    for level in levels:
        exercises = CodingExercise.objects.filter(topic=topic, level=level, is_active=True)
        total = exercises.count()
        completed_ids = StudentExerciseSubmission.objects.filter(
            student=request.user,
            exercise__in=exercises,
            is_completed=True,
        ).values_list('exercise_id', flat=True).distinct()
        completed = len(completed_ids)
        pct = round(completed / total * 100) if total else 0
        meta = LEVEL_META[level]
        level_data.append({
            'level': level,
            'label': dict(CodingExercise.LEVEL_CHOICES)[level],
            'total': total,
            'completed': completed,
            'pct': pct,
            'stars': meta['stars'],
            'colour': meta['colour'],
            'hint': meta['hint'],
            'is_started': completed > 0,
            'is_complete': total > 0 and completed >= total,
        })

    topic_total = sum(ld['total'] for ld in level_data)
    topic_completed = sum(ld['completed'] for ld in level_data)
    topic_pct = round(topic_completed / topic_total * 100) if topic_total else 0

    return render(request, 'coding/level_list.html', {
        'language': language,
        'topic': topic,
        'level_data': level_data,
        'topic_total': topic_total,
        'topic_completed': topic_completed,
        'topic_pct': topic_pct,
        'subject_sidebar': 'coding',
    })


# ---------------------------------------------------------------------------
# Exercises  (topic-based structured learning)
# ---------------------------------------------------------------------------

@login_required
def exercise_list(request, lang_slug, topic_slug, level):
    """List all exercises for a topic at a given level.  /coding/<lang>/topics/<topic>/<level>/"""
    language = _get_language_or_404(lang_slug)
    topic = get_object_or_404(CodingTopic, language=language, slug=topic_slug, is_active=True)

    # Validate level value
    valid_levels = [c[0] for c in CodingExercise.LEVEL_CHOICES]
    if level not in valid_levels:
        from django.http import Http404
        raise Http404("Invalid level")

    exercises = CodingExercise.objects.filter(topic=topic, level=level, is_active=True)

    # Mark which exercises this student has completed
    completed_ids = set(
        StudentExerciseSubmission.objects.filter(
            student=request.user,
            exercise__in=exercises,
            is_completed=True,
        ).values_list('exercise_id', flat=True)
    )

    exercise_data = [
        {'exercise': ex, 'completed': ex.id in completed_ids}
        for ex in exercises
    ]

    return render(request, 'coding/exercise_list.html', {
        'language': language,
        'topic': topic,
        'level': level,
        'level_label': dict(CodingExercise.LEVEL_CHOICES).get(level, level),
        'exercise_data': exercise_data,
        'subject_sidebar': 'coding',
    })


@login_required
def exercise_detail(request, lang_slug, exercise_id):
    """Split-pane editor + instructions for a single exercise.  /coding/<lang>/exercise/<id>/"""
    language = _get_language_or_404(lang_slug)
    exercise = get_object_or_404(CodingExercise, id=exercise_id, topic__language=language, is_active=True)

    is_completed = StudentExerciseSubmission.is_exercise_completed(request.user, exercise)

    return render(request, 'coding/exercise_detail.html', {
        'language': language,
        'exercise': exercise,
        'is_completed': is_completed,
        'subject_sidebar': 'coding',
    })


# ---------------------------------------------------------------------------
# Problem Solving  (algorithm / logic problems)
# ---------------------------------------------------------------------------

@login_required
def problem_list(request, lang_slug):
    """List problems filtered by difficulty.  /coding/<lang>/problems/"""
    language = _get_language_or_404(lang_slug)

    difficulty = request.GET.get('difficulty')  # optional ?difficulty=3 filter
    problems_qs = CodingProblem.objects.filter(language=language, is_active=True)
    if difficulty and difficulty.isdigit():
        problems_qs = problems_qs.filter(difficulty=int(difficulty))

    # Mark which problems this student has already solved
    solved_ids = set(
        StudentProblemSubmission.objects.filter(
            student=request.user,
            problem__in=problems_qs,
            passed_all_tests=True,
        ).values_list('problem_id', flat=True)
    )

    problem_data = [
        {'problem': p, 'solved': p.id in solved_ids}
        for p in problems_qs
    ]

    return render(request, 'coding/problem_list.html', {
        'language': language,
        'problem_data': problem_data,
        'selected_difficulty': difficulty,
        'difficulty_range': range(1, 9),   # 1–8
        'subject_sidebar': 'coding',
    })


@login_required
def problem_detail(request, lang_slug, problem_id):
    """Editor + visible test cases for a single problem.  /coding/<lang>/problems/<id>/"""
    language = _get_language_or_404(lang_slug)
    problem = get_object_or_404(CodingProblem, id=problem_id, language=language, is_active=True)

    visible_tests = problem.visible_test_cases
    has_solved = StudentProblemSubmission.has_solved(request.user, problem)

    # Latest submission for display (if any)
    latest = StudentProblemSubmission.get_best_result(request.user, problem)

    return render(request, 'coding/problem_detail.html', {
        'language': language,
        'problem': problem,
        'visible_tests': visible_tests,
        'hidden_count': problem.hidden_test_cases.count(),
        'has_solved': has_solved,
        'latest_submission': latest,
        'subject_sidebar': 'coding',
    })


# ---------------------------------------------------------------------------
# Dashboard / progress
# ---------------------------------------------------------------------------

@login_required
def dashboard(request, lang_slug):
    """Student progress dashboard for a language.  /coding/<lang>/dashboard/"""
    language = _get_language_or_404(lang_slug)
    topics = CodingTopic.objects.filter(language=language, is_active=True)

    topic_progress = []
    for topic in topics:
        exercises = CodingExercise.objects.filter(topic=topic, is_active=True)
        completed = StudentExerciseSubmission.objects.filter(
            student=request.user,
            exercise__in=exercises,
            is_completed=True,
        ).values_list('exercise_id', flat=True).distinct().count()
        topic_progress.append({
            'topic': topic,
            'total': exercises.count(),
            'completed': completed,
        })

    problems_solved = StudentProblemSubmission.objects.filter(
        student=request.user,
        problem__language=language,
        passed_all_tests=True,
    ).values('problem').distinct().count()

    total_problems = CodingProblem.objects.filter(language=language, is_active=True).count()

    return render(request, 'coding/dashboard.html', {
        'language': language,
        'topic_progress': topic_progress,
        'problems_solved': problems_solved,
        'total_problems': total_problems,
        'subject_sidebar': 'coding',
    })


# ---------------------------------------------------------------------------
# API — Run code (exercise, no test cases)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def api_run_code(request):
    """Execute student code and return output.  POST /coding/api/run/

    Request JSON: { language_slug, code, stdin (optional) }
    Response JSON: { stdout, stderr, exit_code }

    Delegates to coding.execution module (Piston API or browser sandbox).
    """
    import json
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    lang_slug = body.get('language_slug', '').strip()
    code = body.get('code', '').strip()
    stdin = body.get('stdin', '')
    mark_complete = body.get('mark_complete', False)
    exercise_id = body.get('exercise_id')

    if not lang_slug or not code:
        return JsonResponse({'error': 'language_slug and code are required'}, status=400)

    language = get_object_or_404(CodingLanguage, slug=lang_slug, is_active=True)

    # HTML/CSS — signal the frontend to use the iframe sandbox (no server execution)
    if language.uses_browser_sandbox:
        if mark_complete and exercise_id:
            _save_exercise_submission(request.user, exercise_id, language, code, '', '', completed=True)
        return JsonResponse({'browser_sandbox': True})

    # Scratch — not server-executed
    if language.uses_scratch_vm:
        return JsonResponse({'error': 'Scratch exercises run in the Scratch editor'}, status=400)

    # Python / JavaScript → Piston API
    from .execution import run_code
    result = run_code(language.piston_language, code, stdin)

    if mark_complete and exercise_id:
        _save_exercise_submission(
            request.user, exercise_id, language, code,
            result.get('stdout', ''), result.get('stderr', ''),
            completed=True,
        )

    return JsonResponse(result)


def _save_exercise_submission(user, exercise_id, language, code, stdout, stderr, completed):
    """Create or update a StudentExerciseSubmission for a topic exercise."""
    exercise = CodingExercise.objects.filter(
        id=exercise_id, topic__language=language, is_active=True
    ).first()
    if not exercise:
        return
    submission, _ = StudentExerciseSubmission.objects.get_or_create(
        student=user,
        exercise=exercise,
        defaults={
            'code_submitted': code,
            'output_received': stdout,
            'stderr_received': stderr,
            'is_completed': completed,
        },
    )
    if not submission.is_completed and completed:
        submission.code_submitted = code
        submission.output_received = stdout
        submission.stderr_received = stderr
        submission.is_completed = True
        submission.save(update_fields=['code_submitted', 'output_received', 'stderr_received', 'is_completed'])


# ---------------------------------------------------------------------------
# API — Submit problem (runs against all test cases)
# ---------------------------------------------------------------------------

@login_required
@require_POST
def api_submit_problem(request, problem_id):
    """Run student code against all test cases.  POST /coding/api/submit/<problem_id>/

    Request JSON: { code }
    Response JSON:
      {
        passed_all: bool,
        visible_results: [ { input, expected, actual, passed } ],
        hidden_passed: int,
        hidden_total: int,
        points: float,
      }
    """
    import json
    problem = get_object_or_404(CodingProblem, id=problem_id, is_active=True)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    code = body.get('code', '').strip()
    time_taken = int(body.get('time_taken_seconds', 0))

    if not code:
        return JsonResponse({'error': 'code is required'}, status=400)

    from .execution import run_code

    visible_results = []
    hidden_passed = 0
    hidden_total = 0
    all_passed = True
    test_results_store = []

    for tc in problem.test_cases.all().order_by('order', 'id'):
        result = run_code(problem.language.piston_language, code, tc.input_data)
        actual = result.get('stdout', '').strip()
        expected = tc.expected_output.strip()
        passed = (actual == expected) and result.get('exit_code', 1) == 0

        if not passed:
            all_passed = False

        if tc.is_visible:
            visible_results.append({
                'description': tc.description,
                'input': tc.input_data,
                'expected': expected,
                'actual': actual,
                'passed': passed,
            })
            test_results_store.append({
                'test_case_id': tc.id,
                'is_visible': True,
                'passed': passed,
                'actual_output': actual,
                'expected_output': expected,
            })
        else:
            hidden_total += 1
            if passed:
                hidden_passed += 1
            test_results_store.append({
                'test_case_id': tc.id,
                'is_visible': False,
                'passed': passed,
                # actual_output intentionally omitted for hidden cases
            })

    visible_passed = sum(1 for r in visible_results if r['passed'])
    visible_total  = len(visible_results)
    total_passed   = visible_passed + hidden_passed
    total_tests    = visible_total + hidden_total

    # ── Scoring ───────────────────────────────────────────────────────────────
    #
    # Two distinct values are tracked independently:
    #
    #   attempt_points  — points earned on THIS submission, calculated fresh
    #                     from accuracy + time.  Always reflects the real
    #                     performance for this attempt; can go up or down
    #                     compared to the previous attempt.
    #
    #   best_points     — the highest attempt_points ever recorded for this
    #                     student-problem pair across ALL submissions.
    #                     Stored in the DB and used by the leaderboard /
    #                     progress views.  Can only ever increase.
    #
    # Separating these two fixes both failure modes:
    #   • Previous bug #1 (before last fix): score dropped on each re-submit
    #     because time_taken accumulated.
    #   • Previous bug #2 (after last fix):  score was frozen because
    #     max(attempt, best_previous) always returned best_previous once
    #     the student slowed down even slightly.
    #
    # ─────────────────────────────────────────────────────────────────────────
    best_previous = StudentProblemSubmission.get_best_points(request.user, problem)

    if all_passed:
        attempt_points = calculate_coding_points(total_passed, total_tests, time_taken)
        best_points    = max(attempt_points, best_previous)
    else:
        attempt_points = 0.0
        best_points    = best_previous   # a failed attempt never reduces the leaderboard score

    is_new_best = all_passed and attempt_points > best_previous

    # Persist every submission for audit trail.
    # Store best_points so leaderboard queries (ORDER BY points DESC) always
    # surface the student's best performance, not their most recent one.
    attempt_number = StudentProblemSubmission.get_next_attempt_number(request.user, problem)
    StudentProblemSubmission.objects.create(
        student=request.user,
        problem=problem,
        attempt_number=attempt_number,
        code_submitted=code,
        passed_all_tests=all_passed,
        visible_passed=visible_passed,
        visible_total=visible_total,
        hidden_passed=hidden_passed,
        hidden_total=hidden_total,
        test_results=test_results_store,
        points=best_points,          # leaderboard always uses best-of
        time_taken_seconds=time_taken,
    )

    return JsonResponse({
        'passed_all':      all_passed,
        'visible_results': visible_results,
        'hidden_passed':   hidden_passed,
        'hidden_total':    hidden_total,
        'attempt_points':  attempt_points,  # what the student earned THIS attempt
        'best_points':     best_points,     # their all-time best (leaderboard value)
        'is_new_best':     is_new_best,     # true only when this attempt beats all prior ones
    })


# ---------------------------------------------------------------------------
# API — Time tracking
# ---------------------------------------------------------------------------

@login_required
def api_piston_health(request):
    """GET /coding/api/piston-health/  — staff/admin only.

    Returns JSON indicating whether Piston is reachable and which
    runtimes are installed. Use this to verify your Docker setup.
    """
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    from .execution import piston_health_check
    ok, detail = piston_health_check()
    return JsonResponse({'ok': ok, 'detail': detail}, status=200 if ok else 503)


@login_required
@require_POST
def api_update_time_log(request):
    """Update daily/weekly time log.  POST /coding/api/update-time-log/

    Request JSON: { seconds: <int> }
    Mirrors maths update_time_log view.
    """
    import json
    try:
        body = json.loads(request.body)
        seconds = int(body.get('seconds', 0))
    except (json.JSONDecodeError, ValueError, TypeError):
        return JsonResponse({'error': 'Invalid request'}, status=400)

    if seconds <= 0:
        return JsonResponse({'status': 'ok'})

    log, _ = CodingTimeLog.objects.get_or_create(student=request.user)
    log.reset_daily_if_needed()
    log.reset_weekly_if_needed()
    log.daily_total_seconds += seconds
    log.weekly_total_seconds += seconds
    log.save(update_fields=['daily_total_seconds', 'weekly_total_seconds'])

    return JsonResponse({
        'status': 'ok',
        'daily_seconds': log.daily_total_seconds,
        'weekly_seconds': log.weekly_total_seconds,
    })
