from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.utils import timezone

from .models import (
    CodingLanguage,
    CodingTopic,
    TopicLevel,
    CodingExercise,
    CodingProblem,
    StudentExerciseAttempt,
    StudentProblemSubmission,
    ProblemSubmissionResult,
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
    languages = CodingLanguage.objects.filter(is_active=True)
    return render(request, 'coding/language_selector.html', {
        'languages': languages,
        'subject_sidebar': 'coding',
    })


# ---------------------------------------------------------------------------
# Topic browsing
# ---------------------------------------------------------------------------

@login_required
def topic_list(request, lang_slug):
    """Show all active topics with per-level progress.  /coding/<lang>/"""
    language = _get_language_or_404(lang_slug)
    topics = CodingTopic.objects.filter(language=language, is_active=True)

    level_choices = [TopicLevel.BEGINNER, TopicLevel.INTERMEDIATE, TopicLevel.ADVANCED]
    level_labels = dict(TopicLevel.LEVEL_CHOICES)

    topic_data = []
    for topic in topics:
        level_progress = []
        for lc in level_choices:
            exercises = CodingExercise.objects.filter(
                topic_level__topic=topic,
                topic_level__level_choice=lc,
                is_active=True,
            )
            total = exercises.count()
            completed = (
                StudentExerciseAttempt.objects.filter(
                    student=request.user,
                    exercise__in=exercises,
                    is_correct=True,
                )
                .values_list('exercise_id', flat=True)
                .distinct()
                .count()
            )
            level_progress.append({
                'level': lc,
                'label': level_labels[lc],
                'total': total,
                'completed': completed,
            })
        topic_data.append({'topic': topic, 'levels': level_progress})

    return render(request, 'coding/topic_list.html', {
        'language': language,
        'topic_data': topic_data,
        'subject_sidebar': 'coding',
    })


@login_required
def level_list(request, lang_slug, topic_slug):
    """Show Beginner / Intermediate / Advanced for a topic.  /coding/<lang>/topics/<topic>/"""
    language = _get_language_or_404(lang_slug)
    topic = get_object_or_404(CodingTopic, language=language, slug=topic_slug, is_active=True)

    levels = [
        TopicLevel.BEGINNER,
        TopicLevel.INTERMEDIATE,
        TopicLevel.ADVANCED,
    ]

    # Build completion info per level for the logged-in student
    level_data = []
    for level in levels:
        exercises = CodingExercise.objects.filter(topic_level__topic=topic, topic_level__level_choice=level, is_active=True)
        completed = StudentExerciseAttempt.objects.filter(
            student=request.user,
            exercise__in=exercises,
            is_correct=True,
        ).values_list('exercise_id', flat=True).distinct()
        level_data.append({
            'level': level,
            'label': dict(TopicLevel.LEVEL_CHOICES)[level],
            'total': exercises.count(),
            'completed': len(completed),
        })

    return render(request, 'coding/level_list.html', {
        'language': language,
        'topic': topic,
        'level_data': level_data,
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
    valid_levels = [c[0] for c in TopicLevel.LEVEL_CHOICES]
    if level not in valid_levels:
        from django.http import Http404
        raise Http404("Invalid level")

    exercises = CodingExercise.objects.filter(topic_level__topic=topic, topic_level__level_choice=level, is_active=True)

    # Mark which exercises this student has completed
    completed_ids = set(
        StudentExerciseAttempt.objects.filter(
            student=request.user,
            exercise__in=exercises,
            is_correct=True,
        ).values_list('exercise_id', flat=True)
    )

    exercise_data = [
        {'exercise': ex, 'completed': ex.id in completed_ids}
        for ex in exercises
    ]

    ctx = {
        'language': language,
        'topic': topic,
        'level': level,
        'level_label': dict(TopicLevel.LEVEL_CHOICES).get(level, level),
        'exercise_data': exercise_data,
        'subject_sidebar': 'coding',
    }

    # Return a lightweight partial for HTMX requests
    if request.headers.get('HX-Request'):
        return render(request, 'coding/partials/exercise_list.html', ctx)
    return render(request, 'coding/exercise_list.html', ctx)


@login_required
def exercise_detail(request, lang_slug, exercise_id):
    """Split-pane editor + instructions for a single exercise.  /coding/<lang>/exercise/<id>/"""
    language = _get_language_or_404(lang_slug)
    exercise = get_object_or_404(CodingExercise, id=exercise_id, topic_level__topic__language=language, is_active=True)

    is_completed = StudentExerciseAttempt.is_exercise_completed(request.user, exercise)

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
        exercises = CodingExercise.objects.filter(topic_level__topic=topic, is_active=True)
        completed = StudentExerciseAttempt.objects.filter(
            student=request.user,
            exercise__in=exercises,
            is_correct=True,
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

    Request JSON:
        { language_slug, code, stdin (optional),
          exercise_id (optional), mark_complete (optional bool) }
    Response JSON: { stdout, stderr, exit_code }

    When exercise_id is supplied the view records a StudentExerciseAttempt.
    When mark_complete is True the attempt is saved with is_correct=True.
    Delegates execution to coding.execution (Piston API or browser sandbox).
    """
    import json
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    lang_slug = body.get('language_slug', '').strip()
    code = body.get('code', '').strip()
    stdin = body.get('stdin', '')
    exercise_id = body.get('exercise_id')
    mark_complete = bool(body.get('mark_complete', False))

    if not lang_slug or not code:
        return JsonResponse({'error': 'language_slug and code are required'}, status=400)

    language = get_object_or_404(CodingLanguage, slug=lang_slug, is_active=True)

    # Resolve exercise once (used for attempt recording below)
    exercise = None
    if exercise_id:
        exercise = CodingExercise.objects.filter(id=exercise_id, is_active=True).first()

    # HTML/CSS — rendered in-browser; record attempt but skip server execution
    if language.uses_browser_sandbox:
        if exercise:
            StudentExerciseAttempt.objects.create(
                student=request.user,
                exercise=exercise,
                submitted_code=code,
                is_correct=mark_complete,
            )
        return JsonResponse({'browser_sandbox': True})

    # Scratch — runs in Blockly/browser; record attempt but skip server execution
    if language.uses_scratch_vm:
        if exercise:
            StudentExerciseAttempt.objects.create(
                student=request.user,
                exercise=exercise,
                submitted_code=code,
                is_correct=mark_complete,
            )
        return JsonResponse({'scratch': True})

    # Python / JavaScript → Piston API
    from .execution import run_code
    result = run_code(language.piston_language, code, stdin)

    # Record the student's attempt (CPP-120: save/submit records the attempt)
    if exercise:
        # Determine correctness:
        #   • explicit mark_complete → always correct
        #   • expected_output set    → compare stdout
        #   • otherwise             → not correct (run-only, no assertion)
        is_correct = mark_complete
        if not is_correct and exercise.expected_output:
            actual = result.get('stdout', '').strip()
            is_correct = (actual == exercise.expected_output.strip()) and result.get('exit_code', 1) == 0

        StudentExerciseAttempt.objects.create(
            student=request.user,
            exercise=exercise,
            submitted_code=code,
            output_received=result.get('stdout', ''),
            stderr_received=result.get('stderr', ''),
            is_correct=is_correct,
        )

    return JsonResponse(result)


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
    visible_total = len(visible_results)
    total_passed = visible_passed + hidden_passed
    total_tests = visible_total + hidden_total

    points = calculate_coding_points(total_passed, total_tests, time_taken) if all_passed else 0.0

    # Save submission record
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
        points=points,
        time_taken_seconds=time_taken,
    )

    return JsonResponse({
        'passed_all': all_passed,
        'visible_results': visible_results,
        'hidden_passed': hidden_passed,
        'hidden_total': hidden_total,
        'points': points,
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
