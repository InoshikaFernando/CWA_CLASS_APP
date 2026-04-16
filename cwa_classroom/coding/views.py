from functools import wraps

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Count, F, Q
from django.conf import settings

import logging

from .models import (
    CodingLanguage,
    CodingTopic,
    TopicLevel,
    CodingExercise,
    CodingProblem,
    StudentExerciseSubmission,
    StudentProblemSubmission,
    CodingTimeLog,
)
from .scoring import evaluate_submission, score_submission

logger = logging.getLogger(__name__)


def student_required(view_func):
    """Decorator: allow only authenticated students.

    Elevated non-student roles must not accumulate CodingTimeLog records or
    StudentProblemSubmission rows.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        blocked_flags = (
            'is_teacher',
            'is_head_of_institute',
            'is_head_of_department',
            'is_institute_owner',
            'is_admin_user',
        )
        if any(getattr(request.user, flag, False) for flag in blocked_flags):
            return redirect('home')
        return view_func(request, *args, **kwargs)
    return _wrapped



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_language_or_404(lang_slug):
    """Return active CodingLanguage by slug or raise 404."""
    return get_object_or_404(CodingLanguage, slug=lang_slug, is_active=True)


def _find_forbidden_code_pattern(problem, code):
    """Return the first forbidden code substring found in *code* for *problem*.

    Patterns are simple case-insensitive substring checks stored on the problem,
    e.g. ['sorted(', '.sort('] for Bubble Sort.
    """
    forbidden_patterns = getattr(problem, 'forbidden_code_patterns', None) or []
    if not forbidden_patterns or not code:
        return None

    normalized_code = code.casefold()
    for pattern in forbidden_patterns:
        if isinstance(pattern, str) and pattern and pattern.casefold() in normalized_code:
            return pattern
    return None


# ---------------------------------------------------------------------------
# Language selector  →  /coding/
# ---------------------------------------------------------------------------

@login_required
@student_required
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
        row['topic_level__topic__language_id']: row['total']
        for row in CodingExercise.objects.filter(topic_level__topic__language__is_active=True, is_active=True)
                                          .values('topic_level__topic__language_id')
                                          .annotate(total=Count('id'))
    }

    # Languages the current student has started (at least one submission)
    started_lang_ids = set()
    if not request.user.is_staff:
        started_lang_ids = set(
            StudentExerciseSubmission.objects.filter(student=request.user)
            .values_list('exercise__topic_level__topic__language_id', flat=True)
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
@student_required
def topic_list(request, lang_slug):
    """Show all active topics for a language.  /coding/<lang>/"""
    language = _get_language_or_404(lang_slug)
    topics = list(CodingTopic.objects.filter(language=language, is_active=True))

    # Aggregate total exercises and completed count per topic in two queries
    total_by_topic = {
        row['topic_level__topic_id']: row['total']
        for row in CodingExercise.objects.filter(topic_level__topic__in=topics, is_active=True)
                                          .values('topic_level__topic_id')
                                          .annotate(total=Count('id'))
    }
    done_by_topic = {
        row['exercise__topic_level__topic_id']: row['done']
        for row in StudentExerciseSubmission.objects.filter(
            student=request.user,
            exercise__topic_level__topic__in=topics,
            is_completed=True,
        ).values('exercise__topic_level__topic_id').annotate(done=Count('exercise_id', distinct=True))
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
@student_required
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
        exercises = CodingExercise.objects.filter(topic_level__topic=topic, topic_level__level_choice=level, is_active=True)
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
@student_required
def exercise_list(request, lang_slug, topic_slug, level):
    """List all exercises for a topic at a given level.  /coding/<lang>/topics/<topic>/<level>/"""
    language = _get_language_or_404(lang_slug)
    topic = get_object_or_404(CodingTopic, language=language, slug=topic_slug, is_active=True)

    # Validate level value
    valid_levels = [c[0] for c in CodingExercise.LEVEL_CHOICES]
    if level not in valid_levels:
        from django.http import Http404
        raise Http404("Invalid level")

    exercises = CodingExercise.objects.filter(topic_level__topic=topic, topic_level__level_choice=level, is_active=True)

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
@student_required
def exercise_detail(request, lang_slug, exercise_id):
    """Split-pane editor + instructions for a single exercise.  /coding/<lang>/exercise/<id>/"""
    language = _get_language_or_404(lang_slug)
    exercise = get_object_or_404(CodingExercise, id=exercise_id, topic_level__topic__language=language, is_active=True)

    is_completed = StudentExerciseSubmission.is_exercise_completed(request.user, exercise)

    # For Scratch exercises, pass the student's most recent blocks_xml so the
    # template can restore their workspace via server-side data (server_blocks_xml),
    # falling back to the exercise starter_code if no submission exists yet.
    server_blocks_xml = ''
    if language.uses_scratch_vm:
        latest = (
            StudentExerciseSubmission.objects
            .filter(student=request.user, exercise=exercise)
            .order_by('-submitted_at')
            .values_list('blocks_xml', flat=True)
            .first()
        )
        server_blocks_xml = latest or ''

    return render(request, 'coding/exercise_detail.html', {
        'language': language,
        'exercise': exercise,
        'is_completed': is_completed,
        'server_blocks_xml': server_blocks_xml,
        'subject_sidebar': 'coding',
    })


# ---------------------------------------------------------------------------
# Problem Solving  (algorithm / logic problems)
# ---------------------------------------------------------------------------

@login_required
@student_required
def problem_list(request, lang_slug):
    """List problems filtered by difficulty.  /coding/<lang>/problems/"""
    language = _get_language_or_404(lang_slug)

    difficulty = request.GET.get('difficulty')  # optional ?difficulty=3 filter
    category   = request.GET.get('category', '')
    # Include problems pinned to this language OR language-agnostic problems (language=NULL)
    from django.db.models import Q
    problems_qs = CodingProblem.objects.filter(
        Q(language=language) | Q(language__isnull=True),
        is_active=True,
    )
    if difficulty and difficulty.isdigit():
        problems_qs = problems_qs.filter(difficulty=int(difficulty))
    if category:
        problems_qs = problems_qs.filter(category=category)

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
        'selected_category': category,
        'category_choices': CodingProblem.CATEGORY_CHOICES,
        'difficulty_range': range(1, 9),   # 1–8
        'subject_sidebar': 'coding',
    })


@login_required
@student_required
def problem_detail(request, lang_slug, problem_id):
    """Editor + visible test cases for a single problem.  /coding/<lang>/problems/<id>/"""
    language = _get_language_or_404(lang_slug)
    from django.db.models import Q
    problem = get_object_or_404(
        CodingProblem,
        Q(language=language) | Q(language__isnull=True),
        id=problem_id,
        is_active=True,
    )

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
@student_required
def dashboard(request, lang_slug):
    """Student progress dashboard for a language.  /coding/<lang>/dashboard/"""
    language = _get_language_or_404(lang_slug)
    topics = CodingTopic.objects.filter(language=language, is_active=True)

    exercises = CodingExercise.objects.filter(topic_level__topic__in=topics, is_active=True)
    completed_exercise_ids = set(
        StudentExerciseSubmission.objects.filter(
            student=request.user,
            exercise__in=exercises,
            is_completed=True,
        ).values_list('exercise_id', flat=True).distinct()
    )

    level_meta = {
        CodingExercise.BEGINNER:     {'label': 'Beginner',     'colour': 'emerald', 'stars': 1},
        CodingExercise.INTERMEDIATE: {'label': 'Intermediate', 'colour': 'amber',   'stars': 2},
        CodingExercise.ADVANCED:     {'label': 'Advanced',     'colour': 'rose',    'stars': 3},
    }

    topic_progress = []
    exercises_total = 0
    exercises_completed = 0
    topics_started = 0
    topics_completed = 0

    for topic in topics:
        topic_exercises = exercises.filter(topic_level__topic=topic)
        topic_total = topic_exercises.count()
        topic_completed = sum(1 for ex in topic_exercises if ex.id in completed_exercise_ids)
        if topic_completed:
            topics_started += 1
        if topic_total and topic_completed >= topic_total:
            topics_completed += 1

        level_data = []
        for level, _label in CodingExercise.LEVEL_CHOICES:
            level_exercises = topic_exercises.filter(topic_level__level_choice=level)
            level_total = level_exercises.count()
            level_completed = sum(1 for ex in level_exercises if ex.id in completed_exercise_ids)
            level_pct = round(level_completed / level_total * 100) if level_total else 0
            meta = level_meta[level]
            level_data.append({
                'level': level,
                'label': meta['label'],
                'colour': meta['colour'],
                'stars': meta['stars'],
                'total': level_total,
                'completed': level_completed,
                'pct': level_pct,
                'is_complete': level_total > 0 and level_completed >= level_total,
            })

        topic_pct = round(topic_completed / topic_total * 100) if topic_total else 0
        topic_progress.append({
            'topic': topic,
            'total': topic_total,
            'completed': topic_completed,
            'pct': topic_pct,
            'levels': level_data,
            'is_complete': topic_total > 0 and topic_completed >= topic_total,
        })
        exercises_total += topic_total
        exercises_completed += topic_completed

    problems_qs = CodingProblem.objects.filter(
        Q(language=language) | Q(language__isnull=True),
        is_active=True,
    )
    solved_problem_ids = set(
        StudentProblemSubmission.objects.filter(
            student=request.user,
            problem__in=problems_qs,
            passed_all_tests=True,
        ).values_list('problem_id', flat=True).distinct()
    )

    difficulty_data = []
    for difficulty in range(1, 9):
        total = problems_qs.filter(difficulty=difficulty).count()
        solved = problems_qs.filter(difficulty=difficulty, id__in=solved_problem_ids).count()
        difficulty_data.append({
            'difficulty': difficulty,
            'total': total,
            'solved': solved,
            'pct': round(solved / total * 100) if total else 0,
        })

    return render(request, 'coding/dashboard.html', {
        'language': language,
        'topic_progress': topic_progress,
        'exercises_total': exercises_total,
        'exercises_completed': exercises_completed,
        'topics_started': topics_started,
        'topics_completed': topics_completed,
        'difficulty_data': difficulty_data,
        'problems_solved': len(solved_problem_ids),
        'total_problems': problems_qs.count(),
        'subject_sidebar': 'coding',
    })


# ---------------------------------------------------------------------------
# API — Run code (exercise, no test cases)
# ---------------------------------------------------------------------------

@login_required
@student_required
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

    # Scratch — execute Blockly-generated Python via Piston
    if language.uses_scratch_vm:
        blocks_xml = body.get('blocks_xml', '')
        if not code:
            return JsonResponse({'stdout': '', 'stderr': '', 'exit_code': 0})
        from .execution import run_code as _run
        result = _run('python', code, stdin)
        if mark_complete and exercise_id:
            _save_exercise_submission(
                request.user, exercise_id, language, code,
                result.get('stdout', ''), result.get('stderr', ''),
                completed=True, blocks_xml=blocks_xml,
            )
        return JsonResponse(result)

    # Python / JavaScript → Piston API
    if not code:
        return JsonResponse({'error': 'code is required'}, status=400)

    from .execution import run_code
    result = run_code(language.piston_language, code, stdin)

    if mark_complete and exercise_id:
        _save_exercise_submission(
            request.user, exercise_id, language, code,
            result.get('stdout', ''), result.get('stderr', ''),
            completed=True,
        )

    return JsonResponse(result)


def _save_exercise_submission(user, exercise_id, language, code, stdout, stderr, completed, blocks_xml=''):
    """Create or update a StudentExerciseSubmission for a topic exercise."""
    exercise = CodingExercise.objects.filter(
        id=exercise_id, topic_level__topic__language=language, is_active=True
    ).first()
    if not exercise:
        return
    submission, created = StudentExerciseSubmission.objects.get_or_create(
        student=user,
        exercise=exercise,
        defaults={
            'code_submitted': code,
            'output_received': stdout,
            'stderr_received': stderr,
            'blocks_xml': blocks_xml,
            'is_completed': completed,
        },
    )
    if not created and (not submission.is_completed and completed):
        submission.code_submitted = code
        submission.output_received = stdout
        submission.stderr_received = stderr
        submission.blocks_xml = blocks_xml
        submission.is_completed = True
        submission.save(update_fields=['code_submitted', 'output_received', 'stderr_received', 'blocks_xml', 'is_completed'])


# ---------------------------------------------------------------------------
# API — Submit problem (runs against all test cases)
# ---------------------------------------------------------------------------

@login_required
@student_required
@require_POST
def api_submit_problem(request, problem_id):
    """Run student code against all test cases.  POST /coding/api/submit/<problem_id>/

    Request JSON: { code }
    Response JSON:
      {
        passed_all:      bool,
        visible_results: [ { input, expected, actual, passed } ],
        hidden_passed:   int,
        hidden_total:    int,
                attempt_points:  float,   — points for this attempt (binary: 100 / 50 / 0)
        best_points:     float,   — student's all-time best
        is_new_best:     bool,
                quality_score:   float,   — currently fixed at 1.0 in binary-scoring mode
                quality_issues:  [str],   — currently [] in binary-scoring mode
      }
    """
    import json

    # Resolve the problem BEFORE the outer try/except so Http404 propagates
    # correctly as a 404 response.  If this line were inside the try block,
    # Http404 (a subclass of Exception) would be caught and returned as 500.
    problem = get_object_or_404(CodingProblem, id=problem_id, is_active=True)

    try:
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        code = body.get('code', '').strip()
        time_taken = int(body.get('time_taken_seconds', 0))
        # language_slug in body takes priority; fall back to problem's fixed language
        req_lang_slug = body.get('language_slug', '').strip()

        if not code:
            return JsonResponse({'error': 'code is required'}, status=400)

        # Resolve the execution language
        if req_lang_slug:
            exec_language = get_object_or_404(CodingLanguage, slug=req_lang_slug, is_active=True)
        elif problem.language_id:
            exec_language = problem.language
        else:
            return JsonResponse({'error': 'language_slug is required for language-agnostic problems'}, status=400)

        piston_lang = exec_language.piston_language
        if not piston_lang:
            return JsonResponse({'error': f'Language "{exec_language.slug}" does not support server-side execution'}, status=400)

        forbidden_pattern = _find_forbidden_code_pattern(problem, code)
        if forbidden_pattern:
            best_previous = StudentProblemSubmission.get_best_points(request.user, problem)
            attempt_number = StudentProblemSubmission.get_next_attempt_number(request.user, problem)
            failure_message = f'Forbidden shortcut used: {forbidden_pattern}'
            failure_result = {
                'description': 'Forbidden approach',
                'input': '',
                'expected': 'Solve this problem without using restricted built-in shortcuts.',
                'actual': failure_message,
                'passed': False,
            }
            StudentProblemSubmission.objects.create(
                student=request.user,
                problem=problem,
                attempt_number=attempt_number,
                code_submitted=code,
                passed_all_tests=False,
                visible_passed=0,
                visible_total=1,
                hidden_passed=0,
                hidden_total=0,
                test_results=[
                    {
                        'test_case_id': None,
                        'is_visible': True,
                        'passed': False,
                        'actual_output': failure_message,
                        'expected_output': 'No forbidden shortcuts',
                    }
                ],
                points=best_previous,
                time_taken_seconds=time_taken,
            )
            return JsonResponse({
                'passed_all': False,
                'visible_results': [failure_result],
                'hidden_passed': 0,
                'hidden_total': 0,
                'attempt_points': 0.0,
                'best_points': best_previous,
                'is_new_best': False,
                'quality_score': 1.0,
                'quality_issues': [failure_message],
                'error': failure_message,
            })

        # ── Evaluate: run code against every test case ───────────────────────
        # evaluate_submission() is the single, problem-type-agnostic entry point.
        # It determines comparison strategy from problem.category automatically.
        eval_result = evaluate_submission(problem, code, piston_lang)

        if not eval_result.has_test_cases:
            logger.warning('Problem %s has no test cases configured.', problem_id)
            return JsonResponse({
                'passed_all': False,
                'visible_results': [],
                'hidden_passed': 0,
                'hidden_total': 0,
                'attempt_points': 0.0,
                'best_points': StudentProblemSubmission.get_best_points(request.user, problem),
                'is_new_best': False,
                'quality_score': 1.0,
                'quality_issues': ['Problem has no test cases configured'],
                'error': 'Test cases not found for this problem',
            }, status=400)

        # Build the visible-test payload returned to the browser
        visible_results = [
            {
                'description': tr.description,
                'input': tr.input_data,
                'expected': tr.expected_output,
                'actual': tr.actual_output,
                'passed': tr.passed,
            }
            for tr in eval_result.test_results
            if tr.is_visible
        ]

        # Build the JSON blob stored in StudentProblemSubmission.test_results
        test_results_store = [
            {
                'test_case_id': tr.test_case_id,
                'is_visible': tr.is_visible,
                'passed': tr.passed,
                **({'actual_output': tr.actual_output, 'expected_output': tr.expected_output}
                   if tr.is_visible else {}),
            }
            for tr in eval_result.test_results
        ]

        # ── Quality fields ────────────────────────────────────────────────────
        # Under binary scoring these are neutral and informational only.
        quality_score = 1.0
        quality_issues = []

        # ── Scoring ───────────────────────────────────────────────────────────
        # Binary model: 100 (all pass) / 50 (visible pass, hidden fail) / 0 (visible fail).
        # Deterministic — same code always produces the same score.
        best_previous = StudentProblemSubmission.get_best_points(request.user, problem)
        attempt_points = score_submission(eval_result)
        best_points = max(attempt_points, best_previous)
        is_new_best = eval_result.all_passed and attempt_points > best_previous

        # ── Persist ───────────────────────────────────────────────────────────
        attempt_number = StudentProblemSubmission.get_next_attempt_number(request.user, problem)
        StudentProblemSubmission.objects.create(
            student=request.user,
            problem=problem,
            attempt_number=attempt_number,
            code_submitted=code,
            passed_all_tests=eval_result.all_passed,
            visible_passed=eval_result.visible_passed,
            visible_total=eval_result.visible_total,
            hidden_passed=eval_result.hidden_passed,
            hidden_total=eval_result.hidden_total,
            test_results=test_results_store,
            points=best_points,          # leaderboard always uses best-of
            time_taken_seconds=time_taken,
        )

        return JsonResponse({
            'passed_all':      eval_result.all_passed,
            'visible_results': visible_results,
            'hidden_passed':   eval_result.hidden_passed,
            'hidden_total':    eval_result.hidden_total,
            'attempt_points':  attempt_points,
            'best_points':     best_points,
            'is_new_best':     is_new_best,
            'quality_score':   quality_score,
            'quality_issues':  quality_issues,
        })

    except Exception as exc:
        # Catch-all for any unexpected errors during submission processing
        import traceback
        exc_str = str(exc)
        logger.error(f'Submission error for problem {problem_id}: {exc}', exc_info=True)
        
        # Provide helpful error messages for common issues
        error_detail = exc_str
        if 'display_order' in exc_str or 'no such column' in exc_str.lower():
            error_detail = (
                'Database schema mismatch: The migration adding display_order may not have been applied. '
                'Run: python manage.py migrate'
            )
        
        return JsonResponse({
            'error': error_detail,
            'detail': traceback.format_exc() if getattr(settings, 'DEBUG', False) else None,
        }, status=500)



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
@student_required
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
    CodingTimeLog.objects.filter(pk=log.pk).update(
        daily_total_seconds=F('daily_total_seconds') + seconds,
        weekly_total_seconds=F('weekly_total_seconds') + seconds,
    )
    log.refresh_from_db()

    return JsonResponse({
        'status': 'ok',
        'daily_seconds': log.daily_total_seconds,
        'weekly_seconds': log.weekly_total_seconds,
    })
