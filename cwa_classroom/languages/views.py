import json
import unicodedata

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_http_methods

from accounts.decorators import student_required
from .models import Language, LanguageAnswer, LanguageExercise, LanguageStudentAnswer
from .utils import get_canvas_config, get_font_info, get_tts_lang_code


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stars_from_score(score: float) -> int:
    if score >= 85:
        return 3
    if score >= 70:
        return 2
    if score >= 50:
        return 1
    return 0


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@login_required
def languages_index(request):
    languages = Language.objects.filter(is_active=True).prefetch_related(
        'topics__levels__exercises'
    )

    answered = LanguageStudentAnswer.objects.filter(
        student=request.user
    ).values('exercise_id', 'is_correct', 'score')

    correct_ids   = frozenset(a['exercise_id'] for a in answered if a['is_correct'])
    attempted_ids = frozenset(a['exercise_id'] for a in answered)
    score_map     = {a['exercise_id']: a['score'] for a in answered}

    total_exercises = 0
    total_correct   = 0

    # Annotate languages, topics, and levels — forces prefetch cache, avoids
    # forloop.first/last hacks in the template for mixed exercise types.
    for lang in languages:
        ids = set()
        for topic in lang.topics.all():
            if not topic.is_active:
                continue
            for level in topic.levels.all():
                lw, ph, sp_mcq, sp_type, cw = [], [], [], [], []
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
                    elif ex.exercise_type == 'crossword':
                        cw.append(ex)
                level.lw_exercises   = lw
                level.ph_exercises   = ph
                level.sp_mcq_exercises = sp_mcq
                level.sp_type_exercises = sp_type
                level.cw_exercises   = cw
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

    if exercise.exercise_type == LanguageExercise.LETTER_WRITING:
        return _letter_writing(request, exercise, language)
    if exercise.exercise_type == LanguageExercise.PHONICS_MCQ:
        return _phonics_mcq(request, exercise, language)
    if exercise.exercise_type == LanguageExercise.SPELLING_MCQ:
        return _spelling_mcq(request, exercise, language)
    if exercise.exercise_type == LanguageExercise.SPELLING_TYPE:
        return _spelling_type(request, exercise, language)
    if exercise.exercise_type == LanguageExercise.CROSSWORD:
        return _crossword(request, exercise, language)

    # Future exercise types — serve 404 until implemented
    from django.http import Http404
    raise Http404('Exercise type not yet implemented')


# ---------------------------------------------------------------------------
# Letter writing
# ---------------------------------------------------------------------------

def _letter_writing(request, exercise, language):
    config = get_canvas_config(language.script_type)
    font_query, font_family = get_font_info(language.script_type)

    if request.method == 'POST':
        raw = request.POST.get('stroke_data', '{}')
        try:
            stroke_data = json.loads(raw)
        except (ValueError, TypeError):
            stroke_data = {}

        # Score: client sends IoU result (0–100). Fall back to has-strokes for
        # older clients or unit tests that pre-date CPP-311.
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

        return JsonResponse({
            'success': True,
            'score': round(score, 1),
            'stars': stars,
            'best_score': round(obj.score, 1),
            'points_earned': str(obj.points_earned),
            'is_correct': obj.is_correct,
        })

    # Unicode-safe: list() splits by code point so Sinhala/Tamil chars work
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
# Phonics MCQ
# ---------------------------------------------------------------------------

def _phonics_mcq(request, exercise, language):
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

        obj, created = LanguageStudentAnswer.objects.get_or_create(
            student=request.user,
            exercise=exercise,
            defaults={
                'selected_answer': selected,
                'is_correct': is_correct,
                'points_earned': exercise.points if is_correct else 0,
            },
        )
        if not created:
            # Always update — students should be able to improve on MCQ retries
            obj.selected_answer = selected
            obj.is_correct = is_correct
            obj.points_earned = exercise.points if is_correct else 0
            obj.save(update_fields=['selected_answer', 'is_correct', 'points_earned'])

        return JsonResponse({
            'success': True,
            'is_correct': is_correct,
            'correct_answer_id': correct_answer.pk if correct_answer else None,
            'correct_answer_text': correct_answer.answer_text if correct_answer else '',
            'points_earned': str(obj.points_earned),
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
    return render(request, 'languages/exercises/phonics_mcq.html', ctx)


# ---------------------------------------------------------------------------
# Spelling MCQ
# ---------------------------------------------------------------------------

def _spelling_mcq(request, exercise, language):
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

        return JsonResponse({
            'success': True,
            'is_correct': is_correct,
            'correct_answer_id': correct_answer.pk if correct_answer else None,
            'correct_answer_text': correct_answer.answer_text if correct_answer else '',
            'points_earned': str(obj.points_earned),
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
    return render(request, 'languages/exercises/spelling_mcq.html', ctx)


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

        return JsonResponse({
            'success': True,
            'is_correct': is_correct,
            'correct_spelling': exercise.prompt,
            'points_earned': str(obj.points_earned),
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
    """Compute 2-D cells list from puzzle_data words. Returns list-of-lists."""
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

        return JsonResponse({
            'success': True,
            'results': results,
            'score': score,
            'correct_count': correct_count,
            'total': total,
            'points_earned': str(obj.points_earned),
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
