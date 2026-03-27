import time

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from .models import (
    NumberPuzzle,
    NumberPuzzleLevel,
    PuzzleAttempt,
    PuzzleSession,
    SessionPuzzle,
    StudentPuzzleProgress,
)


def _ensure_level1_unlocked(user):
    """Lazily ensure Level 1 progress exists and is unlocked."""
    level1 = NumberPuzzleLevel.objects.filter(number=1).first()
    if level1:
        StudentPuzzleProgress.objects.get_or_create(
            student=user, level=level1,
            defaults={'is_unlocked': True}
        )


def _get_progress_map(user):
    """Return {level_id: progress} dict for this user."""
    return {
        p.level_id: p
        for p in StudentPuzzleProgress.objects.filter(student=user)
    }


class NumberPuzzlesHomeView(LoginRequiredMixin, View):
    """Level selection grid showing all 6 levels with lock/unlock state."""

    def get(self, request):
        _ensure_level1_unlocked(request.user)
        levels = NumberPuzzleLevel.objects.all()
        progress_map = _get_progress_map(request.user)

        level_data = []
        for level in levels:
            prog = progress_map.get(level.id)
            level_data.append({
                'level': level,
                'is_unlocked': prog.is_unlocked if prog else False,
                'best_score': prog.best_score if prog else 0,
                'stars': prog.stars if prog else 0,
                'total_sessions': prog.total_sessions if prog else 0,
                'accuracy': prog.accuracy if prog else 0,
            })

        return render(request, 'number_puzzles/level_list.html', {
            'levels': level_data,
            'back_url': '/',
        })


class NumberPuzzlesPlayView(LoginRequiredMixin, View):
    """Start a new puzzle session and display the quiz."""

    def get(self, request, slug):
        level = get_object_or_404(NumberPuzzleLevel, slug=slug)

        # Check unlock
        _ensure_level1_unlocked(request.user)
        prog = StudentPuzzleProgress.objects.filter(
            student=request.user, level=level
        ).first()
        if not prog or not prog.is_unlocked:
            return redirect('number_puzzles_home')

        # Check puzzle pool
        puzzle_count = NumberPuzzle.objects.filter(level=level, is_active=True).count()
        if puzzle_count == 0:
            return render(request, 'number_puzzles/no_puzzles.html', {
                'level': level,
                'back_url': '/basic-facts/number-puzzles/',
            })

        # Abandon any existing in-progress session for this level
        PuzzleSession.objects.filter(
            student=request.user, level=level, status='in_progress'
        ).update(status='abandoned')

        # Create session
        session = PuzzleSession.objects.create(
            student=request.user,
            level=level,
            total_questions=level.puzzles_per_set,
        )

        # Pick puzzles, avoiding recently seen
        recent_puzzle_ids = PuzzleAttempt.objects.filter(
            session__student=request.user,
            session__level=level,
        ).order_by('-answered_at').values_list('puzzle_id', flat=True)[:50]

        available = NumberPuzzle.objects.filter(
            level=level, is_active=True
        ).exclude(id__in=list(recent_puzzle_ids))

        if available.count() < level.puzzles_per_set:
            # Not enough unseen puzzles, include all
            available = NumberPuzzle.objects.filter(level=level, is_active=True)

        puzzles = list(available.order_by('?')[:level.puzzles_per_set])

        # Store puzzle queue
        for i, puzzle in enumerate(puzzles, 1):
            SessionPuzzle.objects.create(
                session=session, puzzle=puzzle, question_number=i
            )

        # Store start time in Django session
        request.session[f'np_{session.id}'] = {
            'start_time': time.time(),
        }

        # Build question data
        questions = []
        for sp in SessionPuzzle.objects.filter(session=session).select_related('puzzle').order_by('question_number'):
            questions.append({
                'number': sp.question_number,
                'puzzle_id': sp.puzzle.id,
                'display': sp.puzzle.display_template,
                'operands': sp.puzzle.operands,
            })

        return render(request, 'number_puzzles/play.html', {
            'session': session,
            'level': level,
            'questions': questions,
            'back_url': '/basic-facts/number-puzzles/',
        })

    def post(self, request, slug):
        level = get_object_or_404(NumberPuzzleLevel, slug=slug)
        session_id = request.POST.get('session_id', '')

        session = PuzzleSession.objects.filter(
            id=session_id, student=request.user, level=level
        ).first()
        if not session:
            return redirect('number_puzzles_home')

        session_key = f'np_{session.id}'
        session_meta = request.session.get(session_key, {})
        start_time = session_meta.get('start_time', time.time())
        time_taken = max(1, int(time.time() - start_time))

        # Grade each puzzle
        session_puzzles = SessionPuzzle.objects.filter(
            session=session
        ).select_related('puzzle', 'puzzle__level').order_by('question_number')

        correct_count = 0
        for sp in session_puzzles:
            raw_answer = request.POST.get(f'answer_{sp.puzzle.id}', '').strip()
            is_correct = _check_puzzle_answer(sp.puzzle, raw_answer)
            if is_correct:
                correct_count += 1

            PuzzleAttempt.objects.update_or_create(
                session=session,
                question_number=sp.question_number,
                defaults={
                    'puzzle': sp.puzzle,
                    'student_answer': raw_answer,
                    'is_correct': is_correct,
                }
            )

        # Update session
        session.score = correct_count
        session.status = 'completed'
        session.completed_at = timezone.now()
        session.duration_seconds = time_taken
        session.save()

        # Update progress
        _update_progress(request.user, level, session)

        # Clean Django session
        request.session.pop(session_key, None)

        return redirect('number_puzzles_results', session_id=session.id)


class NumberPuzzlesResultsView(LoginRequiredMixin, View):
    """Show results for a completed session."""

    def get(self, request, session_id):
        session = get_object_or_404(
            PuzzleSession, id=session_id, student=request.user
        )
        level = session.level

        attempts = PuzzleAttempt.objects.filter(
            session=session
        ).select_related('puzzle').order_by('question_number')

        questions_data = []
        for att in attempts:
            questions_data.append({
                'number': att.question_number,
                'display': att.puzzle.display_template,
                'student_answer': att.student_answer,
                'correct_answer': att.puzzle.solution,
                'is_correct': att.is_correct,
            })

        # Check if next level was unlocked
        next_level = NumberPuzzleLevel.objects.filter(
            number=level.number + 1
        ).first()
        next_level_unlocked = False
        if next_level:
            next_prog = StudentPuzzleProgress.objects.filter(
                student=request.user, level=next_level
            ).first()
            next_level_unlocked = next_prog.is_unlocked if next_prog else False

        # Best score check
        progress = StudentPuzzleProgress.objects.filter(
            student=request.user, level=level
        ).first()
        is_new_best = progress and progress.best_score == session.score and progress.total_sessions > 1

        time_mins = session.duration_seconds // 60 if session.duration_seconds else 0
        time_secs = session.duration_seconds % 60 if session.duration_seconds else 0

        session_accuracy = round((session.score / session.total_questions) * 100) if session.total_questions else 0

        return render(request, 'number_puzzles/results.html', {
            'session': session,
            'level': level,
            'questions_data': questions_data,
            'is_new_best': is_new_best,
            'next_level': next_level if next_level_unlocked else None,
            'time_display': f"{time_mins}:{time_secs:02d}",
            'progress': progress,
            'session_accuracy': session_accuracy,
            'back_url': '/basic-facts/number-puzzles/',
        })


def _check_puzzle_answer(puzzle, raw_answer):
    """
    Check if the student's answer is mathematically correct.
    The answer should be an expression that equals the target.
    """
    if not raw_answer:
        return False

    from number_puzzles.management.commands.generate_puzzles import safe_eval

    # Normalize: replace x/X with *, strip spaces
    normalized = raw_answer.replace('x', '*').replace('X', '*').replace(' ', '')
    # Remove trailing = and target if student typed full expression like "1+2=3"
    if '=' in normalized:
        normalized = normalized.split('=')[0]

    result = safe_eval(normalized)
    if result is None:
        return False

    # Must equal the target
    if int(result) != puzzle.target:
        return False

    # Must use the correct operands in order
    # Extract numbers from the answer
    import re
    answer_numbers = [int(n) for n in re.findall(r'\d+', normalized)]
    if answer_numbers != puzzle.operands:
        return False

    return True


def _update_progress(user, level, session):
    """Update StudentPuzzleProgress after a completed session."""
    progress, _ = StudentPuzzleProgress.objects.get_or_create(
        student=user, level=level,
        defaults={'is_unlocked': True}
    )

    progress.total_sessions += 1
    progress.total_puzzles_attempted += session.total_questions
    progress.total_puzzles_correct += session.score
    progress.last_played_at = timezone.now()

    if session.score > progress.best_score:
        progress.best_score = session.score
        if session.duration_seconds:
            progress.best_time_seconds = session.duration_seconds
    elif session.score == progress.best_score and session.duration_seconds:
        if not progress.best_time_seconds or session.duration_seconds < progress.best_time_seconds:
            progress.best_time_seconds = session.duration_seconds

    progress.save()

    # Check unlock for next level
    if session.score >= level.unlock_threshold:
        next_level = NumberPuzzleLevel.objects.filter(
            number=level.number + 1
        ).first()
        if next_level:
            next_prog, created = StudentPuzzleProgress.objects.get_or_create(
                student=user, level=next_level,
                defaults={'is_unlocked': True}
            )
            if not next_prog.is_unlocked:
                next_prog.is_unlocked = True
                next_prog.save()
