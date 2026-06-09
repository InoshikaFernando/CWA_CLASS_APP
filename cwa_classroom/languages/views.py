import json
import unicodedata
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Case, IntegerField, Prefetch, When
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.decorators import student_required
from .models import (
    Language, LanguageAnswer, LanguageExercise,
    LanguageProgress, LanguageStudentAnswer, LanguageTopicLevel,
)
from .utils import get_canvas_config, get_font_info, get_tts_lang_code


# ---------------------------------------------------------------------------
# Progression helpers
# ---------------------------------------------------------------------------

_LEVEL_ORDER = [LanguageTopicLevel.BEGINNER, LanguageTopicLevel.INTERMEDIATE, LanguageTopicLevel.ADVANCED]


def _recalculate_progress(student, topic_level):
    """Recompute LanguageProgress for this student × level after any submission.

    Returns True if mastery was just achieved (new unlock), False otherwise.
    """
    exercises = list(LanguageExercise.objects.filter(topic_level=topic_level, is_active=True))
    total = len(exercises)
    if total == 0:
        return False

    answers = {
        a.exercise_id: a.score
        for a in LanguageStudentAnswer.objects.filter(
            student=student, exercise__in=exercises
        ).only('exercise_id', 'score')
    }

    scores = list(answers.values())
    best_score_avg = round(sum(scores) / len(scores), 1) if scores else 0.0
    exercises_completed = sum(1 for s in scores if s >= 80.0)

    is_beginner = topic_level.level_choice == LanguageTopicLevel.BEGINNER
    mastery = best_score_avg >= 80.0 and (exercises_completed / total) >= 0.8

    with transaction.atomic():
        progress, _ = LanguageProgress.objects.select_for_update().get_or_create(
            student=student,
            topic_level=topic_level,
            defaults={'is_unlocked': is_beginner},
        )

        progress.exercises_total = total
        progress.exercises_completed = exercises_completed
        progress.best_score_avg = best_score_avg

        if mastery and not progress.completed_at:
            progress.completed_at = timezone.now()
            progress.save()
            _unlock_next_level(student, topic_level)
            return True
        else:
            progress.save(update_fields=['exercises_total', 'exercises_completed', 'best_score_avg'])
            return False


def _unlock_next_level(student, topic_level):
    """Unlock the next level in the same topic when mastery is achieved."""
    try:
        current_idx = _LEVEL_ORDER.index(topic_level.level_choice)
    except ValueError:
        return
    if current_idx + 1 >= len(_LEVEL_ORDER):
        return
    next_choice = _LEVEL_ORDER[current_idx + 1]
    try:
        next_level = LanguageTopicLevel.objects.get(
            topic=topic_level.topic, level_choice=next_choice
        )
    except LanguageTopicLevel.DoesNotExist:
        return
    next_total = LanguageExercise.objects.filter(topic_level=next_level, is_active=True).count()
    progress, created = LanguageProgress.objects.get_or_create(
        student=student,
        topic_level=next_level,
        defaults={'is_unlocked': True, 'exercises_total': next_total},
    )
    if not created and not progress.is_unlocked:
        progress.is_unlocked = True
        progress.exercises_total = next_total
        progress.save(update_fields=['is_unlocked', 'exercises_total'])


def _is_level_locked(user, topic_level):
    """Return True if this level is locked for the given student."""
    if topic_level.level_choice == LanguageTopicLevel.BEGINNER:
        return False
    try:
        p = LanguageProgress.objects.get(student=user, topic_level=topic_level)
        return not p.is_unlocked
    except LanguageProgress.DoesNotExist:
        return True


def _stars_from_score(score: float) -> int:
    if score >= 85:
        return 3
    if score >= 70:
        return 2
    if score >= 50:
        return 1
    return 0


# ---------------------------------------------------------------------------
# Locked exercise response
# ---------------------------------------------------------------------------

def _locked_exercise_response(request, exercise, language):
    topic_level = exercise.topic_level
    try:
        current_idx = _LEVEL_ORDER.index(topic_level.level_choice)
    except ValueError:
        current_idx = 1
    blocking_choice = _LEVEL_ORDER[current_idx - 1] if current_idx > 0 else None

    blocking_level = None
    blocking_progress = None
    if blocking_choice:
        try:
            blocking_level = LanguageTopicLevel.objects.get(
                topic=topic_level.topic, level_choice=blocking_choice
            )
            blocking_progress = LanguageProgress.objects.filter(
                student=request.user, topic_level=blocking_level
            ).first()
        except LanguageTopicLevel.DoesNotExist:
            pass

    ctx = {
        'exercise': exercise,
        'language': language,
        'topic_level': topic_level,
        'blocking_level': blocking_level,
        'blocking_progress': blocking_progress,
    }
    return render(request, 'languages/exercises/locked_exercise.html', ctx)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

_LEVEL_SORT = Case(
    When(level_choice=LanguageTopicLevel.BEGINNER, then=0),
    When(level_choice=LanguageTopicLevel.INTERMEDIATE, then=1),
    When(level_choice=LanguageTopicLevel.ADVANCED, then=2),
    default=3,
    output_field=IntegerField(),
)


@login_required
def languages_index(request):
    levels_qs = LanguageTopicLevel.objects.annotate(
        _sort=_LEVEL_SORT
    ).order_by('_sort').prefetch_related('exercises')

    languages = Language.objects.filter(is_active=True).prefetch_related(
        Prefetch('topics__levels', queryset=levels_qs),
    ).order_by('order', 'name')

    answered = LanguageStudentAnswer.objects.filter(
        student=request.user
    ).values('exercise_id', 'is_correct', 'score')

    correct_ids   = frozenset(a['exercise_id'] for a in answered if a['is_correct'])
    attempted_ids = frozenset(a['exercise_id'] for a in answered)
    score_map     = {a['exercise_id']: a['score'] for a in answered}

    progress_map = {
        p.topic_level_id: p
        for p in LanguageProgress.objects.filter(student=request.user)
    }

    total_exercises = 0
    total_correct   = 0

    for lang in languages:
        ids = set()
        for topic in lang.topics.all():
            if not topic.is_active:
                continue
            for level in topic.levels.all():
                lw, ph, sp_mcq, sp_type, cw, gfb, so = [], [], [], [], [], [], []
                for ex in level.exercises.all():
                    if not ex.is_active:
                        continue
                    ids.add(ex.id)
                    if ex.exercise_type == 'letter_writing':
                        lw.append(ex)
                    elif ex.exercise_type == 'phonics_mcq':
                        ph.append(ex)
                    elif ex.exercise_type == 'spelling_mcq':
                        sp_mcq.append(ex)
                    elif ex.exercise_type == 'spelling_type':
                        sp_type.append(ex)
                    elif ex.exercise_type in ('crossword', 'advanced_crossword'):
                        cw.append(ex)
                    elif ex.exercise_type == 'grammar_fill_blank':
                        gfb.append(ex)
                    elif ex.exercise_type == 'sentence_order':
                        so.append(ex)
                level.lw_exercises      = lw
                level.ph_exercises      = ph
                level.sp_mcq_exercises  = sp_mcq
                level.sp_type_exercises = sp_type
                level.cw_exercises      = cw
                level.gfb_exercises     = gfb
                level.so_exercises      = so

                # Progression annotations
                p = progress_map.get(level.id)
                level.ui_locked = (
                    level.level_choice != LanguageTopicLevel.BEGINNER
                    and not (p and p.is_unlocked)
                )
                level.ui_completed = bool(p and p.completed_at)
                level.ui_stage_pct = round(p.best_score_avg) if p else 0
                level.ui_completed_count = p.exercises_completed if p else 0
                level.ui_total_count = p.exercises_total if p else 0

        lang.ui_total   = len(ids)
        lang.ui_correct = len(correct_ids & ids)
        lang.ui_pct     = round(lang.ui_correct * 100 / lang.ui_total) if lang.ui_total else 0
        total_exercises += lang.ui_total
        total_correct   += lang.ui_correct

    overall_pct = round(total_correct * 100 / total_exercises) if total_exercises else 0

    ctx = {
        'languages':       languages,
        'correct_ids':     correct_ids,
        'attempted_ids':   attempted_ids,
        'score_map':       score_map,
        'total_exercises': total_exercises,
        'total_correct':   total_correct,
        'overall_pct':     overall_pct,
        'user_name':       request.user.first_name or request.user.username,
    }
    return render(request, 'languages/index.html', ctx)


@login_required
@student_required
@require_http_methods(['GET', 'POST'])
def exercise_detail(request, exercise_id):
    exercise = get_object_or_404(
        LanguageExercise.objects.select_related('topic_level__topic__language'),
        pk=exercise_id,
        is_active=True,
    )
    language = exercise.topic_level.topic.language

    if _is_level_locked(request.user, exercise.topic_level):
        if request.method == 'POST':
            return JsonResponse({'error': 'Stage is locked'}, status=403)
        return _locked_exercise_response(request, exercise, language)

    if exercise.exercise_type == LanguageExercise.LETTER_WRITING:
        return _letter_writing(request, exercise, language)
    if exercise.exercise_type == LanguageExercise.PHONICS_MCQ:
        return _phonics_mcq(request, exercise, language)
    if exercise.exercise_type == LanguageExercise.SPELLING_MCQ:
        return _spelling_mcq(request, exercise, language)
    if exercise.exercise_type == LanguageExercise.SPELLING_TYPE:
        return _spelling_type(request, exercise, language)
    if exercise.exercise_type in (LanguageExercise.CROSSWORD, LanguageExercise.ADVANCED_CROSSWORD):
        return _crossword(request, exercise, language)
    if exercise.exercise_type == LanguageExercise.GRAMMAR_FILL_BLANK:
        return _grammar_fill_blank(request, exercise, language)
    if exercise.exercise_type == LanguageExercise.SENTENCE_ORDER:
        return _sentence_order(request, exercise, language)

    raise Http404('Exercise type not yet implemented')


# ---------------------------------------------------------------------------
# Letter writing
# ---------------------------------------------------------------------------

def _letter_writing(request, exercise, language):
    config = get_canvas_config(language.script_type)
    font_query, font_family = get_font_info(language.script_type)

    if request.method == 'POST':
        raw = request.POST.get('stroke_data', '{}')
        if len(raw) > 500_000:
            raw = '{}'
        try:
            stroke_data = json.loads(raw)
        except (ValueError, TypeError):
            stroke_data = {}

        raw_score = request.POST.get('score')
        if raw_score is not None:
            try:
                score = max(0.0, min(100.0, float(raw_score)))
            except (ValueError, TypeError):
                score = 0.0
        else:
            score = 100.0 if bool(stroke_data.get('objects')) else 0.0

        is_correct = score >= 50.0
        stars = _stars_from_score(score)

        obj, created = LanguageStudentAnswer.objects.get_or_create(
            student=request.user,
            exercise=exercise,
            defaults={
                'score': score,
                'stroke_data': stroke_data,
                'is_correct': is_correct,
                'points_earned': exercise.points if is_correct else 0,
            },
        )
        if not created and score > obj.score:
            obj.score = score
            obj.is_correct = is_correct
            obj.stroke_data = stroke_data
            obj.points_earned = exercise.points if is_correct else 0
            obj.save(update_fields=['score', 'is_correct', 'stroke_data', 'points_earned'])

        stage_unlocked = _recalculate_progress(request.user, exercise.topic_level)

        return JsonResponse({
            'success': True,
            'score': round(score, 1),
            'stars': stars,
            'best_score': round(obj.score, 1),
            'points_earned': str(obj.points_earned),
            'is_correct': obj.is_correct,
            'stage_unlocked': stage_unlocked,
        })

    chars = list(exercise.prompt)
    guide_char = chars[0] if chars else '?'

    ctx = {
        'exercise': exercise,
        'language': language,
        'canvas_config': config,
        'guide_char': guide_char,
        'font_query': font_query,
        'font_family': font_family,
    }
    return render(request, 'languages/exercises/letter_writing.html', ctx)


# ---------------------------------------------------------------------------
# MCQ handler — shared by phonics and spelling MCQ exercise types
# ---------------------------------------------------------------------------

def _mcq_handler(request, exercise, language, template_name):
    font_query, font_family = get_font_info(language.script_type)
    tts_lang = get_tts_lang_code(language.code)

    if request.method == 'POST':
        answer_id = request.POST.get('selected_answer_id', '').strip()
        selected = None
        is_correct = False

        if answer_id:
            try:
                selected = LanguageAnswer.objects.get(pk=int(answer_id), exercise=exercise)
                is_correct = selected.is_correct
            except (LanguageAnswer.DoesNotExist, ValueError, TypeError):
                pass

        correct_answer = exercise.answers.filter(is_correct=True).first()
        score = 100.0 if is_correct else 0.0

        obj, created = LanguageStudentAnswer.objects.get_or_create(
            student=request.user,
            exercise=exercise,
            defaults={
                'selected_answer': selected,
                'is_correct': is_correct,
                'score': score,
                'points_earned': exercise.points if is_correct else 0,
            },
        )
        if not created:
            obj.selected_answer = selected
            obj.is_correct = is_correct
            obj.score = score
            obj.points_earned = exercise.points if is_correct else 0
            obj.save(update_fields=['selected_answer', 'is_correct', 'score', 'points_earned'])

        stage_unlocked = _recalculate_progress(request.user, exercise.topic_level)

        return JsonResponse({
            'success': True,
            'is_correct': is_correct,
            'correct_answer_id': correct_answer.pk if correct_answer else None,
            'correct_answer_text': correct_answer.answer_text if correct_answer else '',
            'points_earned': str(obj.points_earned),
            'stage_unlocked': stage_unlocked,
        })

    answers = list(exercise.answers.order_by('display_order', 'pk'))
    audio_file_url = exercise.audio_file.url if exercise.audio_file else ''

    ctx = {
        'exercise': exercise,
        'language': language,
        'answers': answers,
        'tts_lang': tts_lang,
        'font_query': font_query,
        'font_family': font_family,
        'audio_file_url': audio_file_url,
    }
    return render(request, template_name, ctx)


def _phonics_mcq(request, exercise, language):
    return _mcq_handler(request, exercise, language, 'languages/exercises/phonics_mcq.html')


def _spelling_mcq(request, exercise, language):
    return _mcq_handler(request, exercise, language, 'languages/exercises/spelling_mcq.html')


# ---------------------------------------------------------------------------
# Spelling Type
# ---------------------------------------------------------------------------

def _spelling_type(request, exercise, language):
    font_query, font_family = get_font_info(language.script_type)
    tts_lang = get_tts_lang_code(language.code)

    if request.method == 'POST':
        raw = request.POST.get('answer', '').strip()
        submitted = unicodedata.normalize('NFC', raw)
        expected  = unicodedata.normalize('NFC', exercise.prompt.strip())

        if language.script_type == Language.SCRIPT_LATIN:
            is_correct = submitted.lower() == expected.lower()
        else:
            is_correct = submitted == expected

        score = 100.0 if is_correct else 0.0

        obj, created = LanguageStudentAnswer.objects.get_or_create(
            student=request.user,
            exercise=exercise,
            defaults={
                'text_answer': submitted,
                'is_correct': is_correct,
                'score': score,
                'points_earned': exercise.points if is_correct else 0,
            },
        )
        if not created:
            obj.text_answer = submitted
            obj.is_correct = is_correct
            obj.score = score
            obj.points_earned = exercise.points if is_correct else 0
            obj.save(update_fields=['text_answer', 'is_correct', 'score', 'points_earned'])

        stage_unlocked = _recalculate_progress(request.user, exercise.topic_level)

        return JsonResponse({
            'success': True,
            'is_correct': is_correct,
            'correct_spelling': exercise.prompt,
            'points_earned': str(obj.points_earned),
            'stage_unlocked': stage_unlocked,
        })

    audio_file_url = exercise.audio_file.url if exercise.audio_file else ''

    ctx = {
        'exercise': exercise,
        'language': language,
        'tts_lang': tts_lang,
        'font_query': font_query,
        'font_family': font_family,
        'audio_file_url': audio_file_url,
    }
    return render(request, 'languages/exercises/spelling_type.html', ctx)


# ---------------------------------------------------------------------------
# Crossword
# ---------------------------------------------------------------------------

def _build_crossword_grid(puzzle_data):
    width  = puzzle_data.get('width', 0)
    height = puzzle_data.get('height', 0)
    if not width or not height:
        return []
    grid = [[None] * width for _ in range(height)]
    for word in puzzle_data.get('words', []):
        answer   = unicodedata.normalize('NFC', word['answer'])
        row, col = word['row'], word['col']
        direction = word['direction']
        number    = word.get('number')
        for i, ch in enumerate(answer):
            r = row + (i if direction == 'down' else 0)
            c = col + (i if direction == 'across' else 0)
            if 0 <= r < height and 0 <= c < width:
                cell = grid[r][c] or {}
                cell['letter'] = ch
                if i == 0 and number is not None:
                    cell['number'] = number
                grid[r][c] = cell
    return grid


def _crossword(request, exercise, language):
    font_query, font_family = get_font_info(language.script_type)

    puzzle_data = exercise.puzzle_data or {}
    words       = puzzle_data.get('words', [])

    if request.method == 'POST':
        raw_answers  = request.POST.get('word_answers', '{}')
        raw_hints    = request.POST.get('hints_used', '[]')
        try:
            word_answers = json.loads(raw_answers)
            hints_used   = json.loads(raw_hints)
            if not isinstance(word_answers, dict):
                word_answers = {}
            if not isinstance(hints_used, list):
                hints_used = []
        except (ValueError, TypeError):
            word_answers = {}
            hints_used   = []

        results      = []
        correct_count = 0

        for word in words:
            idx      = str(word['index'])
            expected = unicodedata.normalize('NFC', word['answer'].strip())
            typed    = unicodedata.normalize('NFC', word_answers.get(idx, '').strip())

            if language.script_type == Language.SCRIPT_LATIN:
                is_correct = typed.lower() == expected.lower()
            else:
                is_correct = typed == expected

            results.append({'index': word['index'], 'correct': is_correct})
            if is_correct:
                correct_count += 1

        total = len(words)
        base_score = (correct_count / total * 100) if total else 0
        hint_penalty = len([h for h in hints_used if isinstance(h, int)]) * 10
        score = max(0.0, round(base_score - hint_penalty, 1))
        is_correct_overall = score >= 50

        obj, created = LanguageStudentAnswer.objects.get_or_create(
            student=request.user,
            exercise=exercise,
            defaults={
                'is_correct': is_correct_overall,
                'score': score,
                'points_earned': exercise.points if is_correct_overall else 0,
            },
        )
        if not created:
            obj.is_correct    = is_correct_overall
            obj.score         = score
            obj.points_earned = exercise.points if is_correct_overall else 0
            obj.save(update_fields=['is_correct', 'score', 'points_earned'])

        stage_unlocked = _recalculate_progress(request.user, exercise.topic_level)

        return JsonResponse({
            'success': True,
            'results': results,
            'score': score,
            'correct_count': correct_count,
            'total': total,
            'points_earned': str(obj.points_earned),
            'stage_unlocked': stage_unlocked,
        })

    grid = _build_crossword_grid(puzzle_data)
    ctx = {
        'exercise':    exercise,
        'language':    language,
        'font_query':  font_query,
        'font_family': font_family,
        'puzzle_data': json.dumps(puzzle_data),
        'grid':        grid,
        'words':       words,
    }
    return render(request, 'languages/exercises/crossword.html', ctx)


# ---------------------------------------------------------------------------
# Grammar Fill-in-the-Blank
# ---------------------------------------------------------------------------

def _grammar_fill_blank(request, exercise, language):
    font_query, font_family = get_font_info(language.script_type)
    tts_lang = get_tts_lang_code(language.code)

    if request.method == 'POST':
        answer_id = request.POST.get('selected_answer_id', '').strip()
        selected = None
        is_correct = False

        if answer_id:
            try:
                selected = LanguageAnswer.objects.get(pk=int(answer_id), exercise=exercise)
                is_correct = selected.is_correct
            except (LanguageAnswer.DoesNotExist, ValueError, TypeError):
                pass

        correct_answer = exercise.answers.filter(is_correct=True).first()
        score = 100.0 if is_correct else 0.0
        grammar_explanation = exercise.puzzle_data.get('grammar_explanation', '')
        points_earned = Decimal(str(exercise.points)) if is_correct else Decimal('0')

        obj, created = LanguageStudentAnswer.objects.get_or_create(
            student=request.user,
            exercise=exercise,
            defaults={
                'selected_answer': selected,
                'is_correct': is_correct,
                'score': score,
                'points_earned': points_earned,
            },
        )
        if not created:
            obj.selected_answer = selected
            obj.is_correct = is_correct
            obj.score = score
            obj.points_earned = points_earned
            obj.save(update_fields=['selected_answer', 'is_correct', 'score', 'points_earned'])

        stage_unlocked = _recalculate_progress(request.user, exercise.topic_level)

        return JsonResponse({
            'success': True,
            'is_correct': is_correct,
            'correct_answer_id': correct_answer.pk if correct_answer else None,
            'correct_answer_text': correct_answer.answer_text if correct_answer else '',
            'grammar_explanation': grammar_explanation,
            'points_earned': str(obj.points_earned),
            'stage_unlocked': stage_unlocked,
        })

    parts = exercise.prompt.split('___')
    sentence_before = parts[0] if len(parts) > 0 else exercise.prompt
    sentence_after  = parts[1] if len(parts) > 1 else ''
    grammar_explanation = exercise.puzzle_data.get('grammar_explanation', '')

    answers = list(exercise.answers.order_by('display_order', 'pk'))

    ctx = {
        'exercise':            exercise,
        'language':            language,
        'answers':             answers,
        'tts_lang':            tts_lang,
        'font_query':          font_query,
        'font_family':         font_family,
        'sentence_before':     sentence_before,
        'sentence_after':      sentence_after,
        'grammar_explanation': grammar_explanation,
    }
    return render(request, 'languages/exercises/grammar_fill_blank.html', ctx)


# ---------------------------------------------------------------------------
# Sentence Ordering
# ---------------------------------------------------------------------------

def _sentence_order(request, exercise, language):
    font_query, font_family = get_font_info(language.script_type)

    word_order = exercise.puzzle_data.get('word_order', [])

    if request.method == 'POST':
        raw = request.POST.get('submitted_order', '[]')
        try:
            submitted = json.loads(raw)
            if not isinstance(submitted, list):
                submitted = []
        except (ValueError, TypeError):
            submitted = []

        n = len(word_order)
        if n == 0:
            score = 0.0
            correct_count = 0
        else:
            correct_count = sum(
                1 for i, w in enumerate(submitted[:n])
                if i < n and unicodedata.normalize('NFC', str(w)) == unicodedata.normalize('NFC', word_order[i])
            )
            score = round(correct_count / n * 100, 1)

        is_correct = score >= 80.0
        points_earned = Decimal(str(exercise.points)) * Decimal(str(score)) / Decimal('100')
        points_earned = points_earned.quantize(Decimal('0.01'))

        obj, created = LanguageStudentAnswer.objects.get_or_create(
            student=request.user,
            exercise=exercise,
            defaults={
                'is_correct': is_correct,
                'score': score,
                'points_earned': points_earned,
            },
        )
        if not created and score > obj.score:
            obj.is_correct    = is_correct
            obj.score         = score
            obj.points_earned = points_earned
            obj.save(update_fields=['is_correct', 'score', 'points_earned'])

        stage_unlocked = _recalculate_progress(request.user, exercise.topic_level)

        return JsonResponse({
            'success': True,
            'is_correct': is_correct,
            'score': score,
            'correct_count': correct_count,
            'total': n,
            'correct_sentence': ' '.join(word_order),
            'points_earned': str(obj.points_earned),
            'stage_unlocked': stage_unlocked,
        })

    ctx = {
        'exercise':   exercise,
        'language':   language,
        'word_order': json.dumps(word_order),
        'font_query':  font_query,
        'font_family': font_family,
    }
    return render(request, 'languages/exercises/sentence_order.html', ctx)
