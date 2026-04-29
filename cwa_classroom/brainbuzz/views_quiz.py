"""
BrainBuzz Quiz Builder views.

Teacher flows (login + is_teacher required):
  quiz_list               GET        /brainbuzz/quizzes/
  quiz_create             GET/POST   /brainbuzz/quizzes/create/
  quiz_builder            GET        /brainbuzz/quizzes/<id>/build/
  quiz_delete             POST       /brainbuzz/quizzes/<id>/delete/
  quiz_publish            POST       /brainbuzz/quizzes/<id>/publish/
  quiz_launch             POST       /brainbuzz/quizzes/<id>/launch/

JSON API (called by quiz builder JS):
  api_quiz_detail         GET        /brainbuzz/api/quizzes/<id>/
  api_quiz_questions      POST       /brainbuzz/api/quizzes/<id>/questions/
  api_quiz_question       GET/PUT/DELETE  /brainbuzz/api/quizzes/<id>/questions/<q_id>/
  api_quiz_reorder        POST       /brainbuzz/api/quizzes/<id>/reorder/
  api_quiz_meta           POST       /brainbuzz/api/quizzes/<id>/meta/
"""

import json

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .models import (
    BrainBuzzQuiz,
    BrainBuzzQuizQuestion,
    BrainBuzzQuizOption,
    QUESTION_TYPE_MCQ,
    QUESTION_TYPE_TRUE_FALSE,
    QUIZ_QUESTION_TYPE_CHOICES,
)
from .views import _require_teacher


# ---------------------------------------------------------------------------
# Serialisers (plain dicts — no DRF)
# ---------------------------------------------------------------------------

def _option_to_dict(opt: BrainBuzzQuizOption) -> dict:
    return {
        'id': opt.id,
        'option_text': opt.option_text,
        'is_correct': opt.is_correct,
        'order': opt.order,
    }


def _question_to_dict(q: BrainBuzzQuizQuestion) -> dict:
    options = [_option_to_dict(o) for o in q.quiz_options.order_by('order')]
    return {
        'id': q.id,
        'question_text': q.question_text,
        'question_type': q.question_type,
        'time_limit': q.time_limit,
        'order': q.order,
        'correct_short_answer': q.correct_short_answer or '',
        'options': options,
    }


def _quiz_to_dict(quiz: BrainBuzzQuiz) -> dict:
    questions = [_question_to_dict(q) for q in quiz.quiz_questions.order_by('order')]
    return {
        'id': quiz.id,
        'title': quiz.title,
        'subject_id': quiz.subject_id,
        'subject_name': quiz.subject.name if quiz.subject else '',
        'is_draft': quiz.is_draft,
        'question_count': len(questions),
        'questions': questions,
        'is_valid': quiz.is_valid_for_publish(),
    }


# ---------------------------------------------------------------------------
# Teacher page views
# ---------------------------------------------------------------------------

@login_required
def quiz_list(request):
    if not _require_teacher(request):
        return redirect('subjects_hub')

    quizzes = (
        BrainBuzzQuiz.objects
        .filter(created_by=request.user)
        .order_by('-updated_at')
    )
    return render(request, 'brainbuzz/quiz_list.html', {'quizzes': quizzes})


@login_required
def quiz_create(request):
    if not _require_teacher(request):
        return redirect('subjects_hub')

    from classroom.models import Subject
    subjects = Subject.objects.all().order_by('name')

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        subject_id = request.POST.get('subject_id', '').strip()

        errors = []
        if not title:
            errors.append('Quiz title is required.')
        if len(title) > 255:
            errors.append('Title must be 255 characters or fewer.')

        subject_obj = None
        if subject_id:
            try:
                subject_obj = Subject.objects.get(id=int(subject_id))
            except (Subject.DoesNotExist, ValueError):
                errors.append('Invalid subject.')

        if errors:
            return render(request, 'brainbuzz/quiz_create.html', {
                'subjects': subjects,
                'errors': errors,
                'form_title': title,
                'form_subject_id': subject_id,
            })

        quiz = BrainBuzzQuiz.objects.create(
            title=title,
            subject=subject_obj,
            created_by=request.user,
            is_draft=True,
        )
        return redirect('brainbuzz:quiz_builder', quiz_id=quiz.id)

    return render(request, 'brainbuzz/quiz_create.html', {'subjects': subjects})


@login_required
def quiz_builder(request, quiz_id):
    if not _require_teacher(request):
        return redirect('subjects_hub')

    quiz = get_object_or_404(BrainBuzzQuiz, id=quiz_id, created_by=request.user)
    from classroom.models import Subject
    subjects = Subject.objects.all().order_by('name')
    return render(request, 'brainbuzz/quiz_builder.html', {
        'quiz': quiz,
        'subjects': subjects,
        'question_types': QUIZ_QUESTION_TYPE_CHOICES,
    })


@login_required
@require_POST
def quiz_delete(request, quiz_id):
    if not _require_teacher(request):
        return redirect('subjects_hub')

    quiz = get_object_or_404(BrainBuzzQuiz, id=quiz_id, created_by=request.user)
    quiz.delete()
    return redirect('brainbuzz:quiz_list')


@login_required
@require_POST
def quiz_publish(request, quiz_id):
    if not _require_teacher(request):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    quiz = get_object_or_404(BrainBuzzQuiz, id=quiz_id, created_by=request.user)

    if not quiz.is_valid_for_publish():
        return JsonResponse(
            {'error': 'Quiz must have at least one question, and every MCQ/True-False question must have a correct answer.'},
            status=400,
        )

    quiz.is_draft = False
    quiz.save(update_fields=['is_draft', 'updated_at'])
    return JsonResponse({'status': 'published', 'is_draft': False})


@login_required
@require_POST
def quiz_launch(request, quiz_id):
    """Launch a BrainBuzz session from a custom quiz."""
    if not _require_teacher(request):
        return redirect('subjects_hub')

    quiz = get_object_or_404(BrainBuzzQuiz, id=quiz_id, created_by=request.user)

    if not quiz.quiz_questions.exists():
        return redirect('brainbuzz:quiz_builder', quiz_id=quiz.id)

    from .views import _snapshot_quiz_questions
    from .models import BrainBuzzSession
    from .utils import generate_join_code
    from classroom.models import Subject

    time_sec = 20
    try:
        time_sec = max(5, min(120, int(request.POST.get('time_per_question_sec', 20))))
    except (ValueError, TypeError):
        pass

    subject_obj = quiz.subject
    if not subject_obj:
        subject_obj = Subject.objects.first()
    if not subject_obj:
        return redirect('brainbuzz:quiz_builder', quiz_id=quiz.id)

    config = {
        'source': 'quiz',
        'quiz_id': quiz.id,
        'time_per_question_sec': time_sec,
    }

    with transaction.atomic():
        session = BrainBuzzSession.objects.create(
            code=generate_join_code(),
            host=request.user,
            subject=subject_obj,
            status=BrainBuzzSession.STATUS_LOBBY,
            time_per_question_sec=time_sec,
            config_json=config,
        )
        _snapshot_quiz_questions(session, quiz)

    return redirect('brainbuzz:teacher_lobby', join_code=session.code)


# ---------------------------------------------------------------------------
# JSON API — quiz metadata
# ---------------------------------------------------------------------------

@login_required
def api_quiz_detail(request, quiz_id):
    if not _require_teacher(request):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    quiz = get_object_or_404(BrainBuzzQuiz, id=quiz_id, created_by=request.user)
    return JsonResponse(_quiz_to_dict(quiz))


@login_required
@require_POST
def api_quiz_meta(request, quiz_id):
    """Update quiz title and/or subject."""
    if not _require_teacher(request):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    quiz = get_object_or_404(BrainBuzzQuiz, id=quiz_id, created_by=request.user)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    title = body.get('title', '').strip()
    if title:
        if len(title) > 255:
            return JsonResponse({'error': 'Title too long (max 255 chars).'}, status=400)
        quiz.title = title

    subject_id = body.get('subject_id')
    if subject_id is not None:
        if subject_id == '':
            quiz.subject = None
        else:
            from classroom.models import Subject
            try:
                quiz.subject = Subject.objects.get(id=int(subject_id))
            except (Subject.DoesNotExist, ValueError):
                return JsonResponse({'error': 'Invalid subject.'}, status=400)

    quiz.save()
    return JsonResponse({'id': quiz.id, 'title': quiz.title, 'subject_id': quiz.subject_id})


# ---------------------------------------------------------------------------
# JSON API — questions
# ---------------------------------------------------------------------------

@login_required
def api_quiz_questions(request, quiz_id):
    if not _require_teacher(request):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    quiz = get_object_or_404(BrainBuzzQuiz, id=quiz_id, created_by=request.user)

    if request.method == 'POST':
        return _api_create_question(request, quiz)

    return JsonResponse({'error': 'Method not allowed'}, status=405)


def _api_create_question(request, quiz: BrainBuzzQuiz):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    q_text = body.get('question_text', '').strip()
    if not q_text:
        return JsonResponse({'error': 'question_text is required.'}, status=400)

    q_type = body.get('question_type', QUESTION_TYPE_MCQ)
    if q_type not in dict(QUIZ_QUESTION_TYPE_CHOICES):
        return JsonResponse({'error': f'Invalid question_type: {q_type}'}, status=400)

    try:
        time_limit = max(5, min(300, int(body.get('time_limit', 20))))
    except (ValueError, TypeError):
        time_limit = 20

    next_order = quiz.quiz_questions.count()

    with transaction.atomic():
        question = BrainBuzzQuizQuestion.objects.create(
            quiz=quiz,
            question_text=q_text,
            question_type=q_type,
            time_limit=time_limit,
            order=next_order,
            correct_short_answer=body.get('correct_short_answer', '') or None,
        )
        _sync_options(question, body.get('options', []))
        quiz.save(update_fields=['updated_at'])

    return JsonResponse(_question_to_dict(question), status=201)


@login_required
def api_quiz_question_detail(request, quiz_id, q_id):
    if not _require_teacher(request):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    quiz = get_object_or_404(BrainBuzzQuiz, id=quiz_id, created_by=request.user)
    question = get_object_or_404(BrainBuzzQuizQuestion, id=q_id, quiz=quiz)

    if request.method == 'GET':
        return JsonResponse(_question_to_dict(question))

    if request.method in ('PUT', 'PATCH'):
        return _api_update_question(request, quiz, question)

    if request.method == 'DELETE':
        return _api_delete_question(quiz, question)

    return JsonResponse({'error': 'Method not allowed'}, status=405)


def _api_update_question(request, quiz: BrainBuzzQuiz, question: BrainBuzzQuizQuestion):
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    q_text = body.get('question_text', '').strip()
    if q_text:
        question.question_text = q_text

    q_type = body.get('question_type')
    if q_type is not None:
        if q_type not in dict(QUIZ_QUESTION_TYPE_CHOICES):
            return JsonResponse({'error': f'Invalid question_type: {q_type}'}, status=400)
        question.question_type = q_type

    time_limit = body.get('time_limit')
    if time_limit is not None:
        try:
            question.time_limit = max(5, min(300, int(time_limit)))
        except (ValueError, TypeError):
            pass

    csa = body.get('correct_short_answer')
    if csa is not None:
        question.correct_short_answer = csa.strip() or None

    with transaction.atomic():
        question.save()
        if 'options' in body:
            _sync_options(question, body['options'])
        quiz.save(update_fields=['updated_at'])

    return JsonResponse(_question_to_dict(question))


def _api_delete_question(quiz: BrainBuzzQuiz, question: BrainBuzzQuizQuestion):
    deleted_order = question.order
    with transaction.atomic():
        question.delete()
        # Re-number remaining questions
        for i, q in enumerate(quiz.quiz_questions.order_by('order')):
            if q.order != i:
                q.order = i
                q.save(update_fields=['order'])
        quiz.save(update_fields=['updated_at'])
    return JsonResponse({'deleted': True, 'deleted_order': deleted_order})


def _sync_options(question: BrainBuzzQuizQuestion, options_data: list):
    """Replace all options for a question from the given list of dicts."""
    question.quiz_options.all().delete()
    for i, opt in enumerate(options_data):
        text = str(opt.get('option_text', '')).strip()
        if not text:
            continue
        BrainBuzzQuizOption.objects.create(
            question=question,
            option_text=text,
            is_correct=bool(opt.get('is_correct', False)),
            order=i,
        )


# ---------------------------------------------------------------------------
# JSON API — reorder questions
# ---------------------------------------------------------------------------

@login_required
@require_POST
def api_quiz_reorder(request, quiz_id):
    if not _require_teacher(request):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    quiz = get_object_or_404(BrainBuzzQuiz, id=quiz_id, created_by=request.user)

    try:
        body = json.loads(request.body)
        ordered_ids = [int(x) for x in body.get('ordered_ids', [])]
    except (json.JSONDecodeError, ValueError, TypeError):
        return JsonResponse({'error': 'Invalid payload. Expect {"ordered_ids": [...]}'}, status=400)

    questions = {q.id: q for q in quiz.quiz_questions.all()}
    if set(ordered_ids) != set(questions.keys()):
        return JsonResponse({'error': 'ordered_ids must contain exactly the quiz question IDs.'}, status=400)

    with transaction.atomic():
        for new_order, q_id in enumerate(ordered_ids):
            q = questions[q_id]
            if q.order != new_order:
                q.order = new_order
                q.save(update_fields=['order'])
        quiz.save(update_fields=['updated_at'])

    return JsonResponse({'reordered': True})
