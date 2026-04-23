"""
BrainBuzz views — teacher and student flows plus JSON API endpoints.

Teacher flows (login + is_teacher required):
  create_session          GET/POST   /brainbuzz/create/
  teacher_lobby           GET        /brainbuzz/session/<code>/lobby/
  teacher_ingame          GET        /brainbuzz/session/<code>/play/
  teacher_end             GET        /brainbuzz/session/<code>/end/
  export_csv              GET        /brainbuzz/session/<code>/export/

Student flows:
  join                    GET        /brainbuzz/join/
  student_play            GET        /brainbuzz/play/<code>/

JSON API (called by JS polling / form submits):
  api_session_state       GET        /brainbuzz/api/session/<code>/state/
  api_teacher_action      POST       /brainbuzz/api/session/<code>/action/
  api_join                POST       /brainbuzz/api/join/
  api_submit              POST       /brainbuzz/api/session/<code>/submit/
  api_leaderboard         GET        /brainbuzz/api/session/<code>/leaderboard/
"""

import csv
import json
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.db.models import F
from django.http import JsonResponse, HttpResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import (
    BrainBuzzSession,
    BrainBuzzSessionQuestion,
    BrainBuzzParticipant,
    BrainBuzzSubmission,
    generate_join_code,
    calculate_brainbuzz_score,
    QUESTION_TYPE_MULTIPLE_CHOICE,
    QUESTION_TYPE_TRUE_FALSE,
    QUIZ_QUESTION_TYPE_CHOICES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PARTICIPANT_COOKIE_PREFIX = 'bb_pid_'
_PARTICIPANT_COOKIE_MAX_AGE = 60 * 60 * 8  # 8 hours


def _get_participant_id(request, join_code: str):
    """Read participant ID from session cookie."""
    return request.session.get(f'{_PARTICIPANT_COOKIE_PREFIX}{join_code}')


def _set_participant_id(request, join_code: str, participant_id: int):
    request.session[f'{_PARTICIPANT_COOKIE_PREFIX}{join_code}'] = participant_id


def _require_teacher(request):
    """Return True if user is a teacher (any teacher role)."""
    return (
        request.user.is_authenticated
        and (
            getattr(request.user, 'is_teacher', False)
            or getattr(request.user, 'is_junior_teacher', False)
            or getattr(request.user, 'is_senior_teacher', False)
        )
    )


def _session_state_payload(session: BrainBuzzSession) -> dict:
    """Build the canonical session state dict returned by the polling API."""
    current_q = session.current_question
    question_data = None
    if current_q is not None:
        question_data = {
            'order_index': current_q.order_index,
            'question_text': current_q.question_text,
            'question_type': current_q.question_type,
            'options': current_q.options,
            'time_limit_seconds': current_q.time_limit_seconds,
            'question_start_time_utc': (
                current_q.question_start_time_utc.isoformat()
                if current_q.question_start_time_utc else None
            ),
            'question_deadline_utc': (
                current_q.question_deadline_utc.isoformat()
                if current_q.question_deadline_utc else None
            ),
        }

    participants = list(
        session.leaderboard().values('id', 'nickname', 'total_score')
    )

    return {
        'join_code': session.join_code,
        'state': session.state,
        'state_version': session.state_version,
        'current_question_index': session.current_question_index,
        'question': question_data,
        'participant_count': session.participants.filter(is_active=True).count(),
        'participants': participants,
        'total_questions': session.questions.count(),
    }


def _snapshot_maths_questions(session: BrainBuzzSession, topic_id: int, level_id: int, count: int):
    """Snapshot maths questions into BrainBuzzSessionQuestion rows."""
    from maths.models import Question, Answer

    qs = (
        Question.objects
        .filter(topic_id=topic_id, level_id=level_id, is_active=True)
        .exclude(question_type='calculation')  # calculation questions don't fit MCQ/TF/SA format well for live buzz
        .order_by('?')[:count]
    )
    for i, q in enumerate(qs):
        answers = list(Answer.objects.filter(question=q).order_by('order'))
        options = [
            {'id': str(a.id), 'text': a.answer_text, 'is_correct': a.is_correct}
            for a in answers
        ]
        accepted = [a.answer_text.strip().lower() for a in answers if a.is_correct]
        BrainBuzzSessionQuestion.objects.create(
            session=session,
            order_index=i,
            question_text=q.question_text,
            question_type=q.question_type if q.question_type in dict(QUIZ_QUESTION_TYPE_CHOICES) else QUESTION_TYPE_MULTIPLE_CHOICE,
            options=options,
            accepted_answers=accepted,
            time_limit_seconds=20,
        )


def _snapshot_coding_questions(session: BrainBuzzSession, topic_level_id: int, count: int):
    """Snapshot coding MCQ/TF/SA exercises into BrainBuzzSessionQuestion rows."""
    from coding.models import CodingExercise, CodingAnswer

    WRITE_CODE = 'write_code'
    qs = (
        CodingExercise.objects
        .filter(topic_level_id=topic_level_id, is_active=True)
        .exclude(question_type=WRITE_CODE)
        .order_by('?')[:count]
    )
    for i, ex in enumerate(qs):
        answers = list(CodingAnswer.objects.filter(exercise=ex).order_by('order'))
        options = [
            {'id': str(a.id), 'text': a.answer_text, 'is_correct': a.is_correct}
            for a in answers
        ]
        accepted = [a.answer_text.strip().lower() for a in answers if a.is_correct]
        BrainBuzzSessionQuestion.objects.create(
            session=session,
            order_index=i,
            question_text=ex.description,
            question_type=ex.question_type if ex.question_type in dict(QUIZ_QUESTION_TYPE_CHOICES) else QUESTION_TYPE_MULTIPLE_CHOICE,
            options=options,
            accepted_answers=accepted,
            time_limit_seconds=20,
        )


# ---------------------------------------------------------------------------
# Rate limiting helper
# ---------------------------------------------------------------------------

def _check_join_rate_limit(request) -> bool:
    """True if the IP is within the join attempt limit (10 per minute)."""
    ip = request.META.get('HTTP_X_FORWARDED_FOR', request.META.get('REMOTE_ADDR', 'unknown'))
    ip = ip.split(',')[0].strip()
    cache_key = f'bb_join_rl_{ip}'
    count = cache.get(cache_key, 0)
    if count >= 10:
        return False
    cache.set(cache_key, count + 1, timeout=60)
    return True


# ---------------------------------------------------------------------------
# Teacher views
# ---------------------------------------------------------------------------

@login_required
def create_session(request):
    """Teacher creates a BrainBuzz session by choosing subject + topic/level + question count."""
    if not _require_teacher(request):
        return redirect('subjects_hub')

    if request.method == 'POST':
        subject = request.POST.get('subject', '').strip()
        count_raw = request.POST.get('question_count', '10').strip()

        try:
            question_count = max(1, min(30, int(count_raw)))
        except (ValueError, TypeError):
            question_count = 10

        if subject == BrainBuzzSession.SUBJECT_MATHS:
            topic_id = request.POST.get('topic_id', '').strip()
            level_id = request.POST.get('level_id', '').strip()
            if not topic_id or not level_id:
                return render(request, 'brainbuzz/teacher_create.html', {
                    'error': 'Select a topic and level.',
                    **_create_context(),
                })
            with transaction.atomic():
                session = BrainBuzzSession.objects.create(
                    join_code=generate_join_code(),
                    created_by=request.user,
                    subject=BrainBuzzSession.SUBJECT_MATHS,
                )
                _snapshot_maths_questions(session, int(topic_id), int(level_id), question_count)
            if not session.questions.exists():
                session.delete()
                return render(request, 'brainbuzz/teacher_create.html', {
                    'error': 'No suitable questions found for that topic and level. Try a different selection.',
                    **_create_context(),
                })
            return redirect('brainbuzz:teacher_lobby', join_code=session.join_code)

        elif subject == BrainBuzzSession.SUBJECT_CODING:
            topic_level_id = request.POST.get('topic_level_id', '').strip()
            if not topic_level_id:
                return render(request, 'brainbuzz/teacher_create.html', {
                    'error': 'Select a coding topic level.',
                    **_create_context(),
                })
            with transaction.atomic():
                session = BrainBuzzSession.objects.create(
                    join_code=generate_join_code(),
                    created_by=request.user,
                    subject=BrainBuzzSession.SUBJECT_CODING,
                )
                _snapshot_coding_questions(session, int(topic_level_id), question_count)
            if not session.questions.exists():
                session.delete()
                return render(request, 'brainbuzz/teacher_create.html', {
                    'error': 'No MCQ/TF/short-answer coding exercises found for that topic level.',
                    **_create_context(),
                })
            return redirect('brainbuzz:teacher_lobby', join_code=session.join_code)

        return render(request, 'brainbuzz/teacher_create.html', {
            'error': 'Invalid subject.',
            **_create_context(),
        })

    return render(request, 'brainbuzz/teacher_create.html', _create_context())


def _create_context():
    """Build context for the create-session form (topic/level selects)."""
    from maths.models import Question
    from classroom.models import Topic, Level

    maths_topics = list(
        Topic.objects.filter(subject__slug='mathematics', subject__school__isnull=True)
        .order_by('name')
        .values('id', 'name')
    )
    maths_levels = list(Level.objects.order_by('level_number').values('id', 'level_number'))

    try:
        from coding.models import TopicLevel, CodingTopic, CodingLanguage
        coding_topic_levels = list(
            TopicLevel.objects.filter(is_active=True)
            .select_related('topic', 'topic__language')
            .order_by('topic__language__order', 'topic__order', 'level_choice')
            .values('id', 'level_choice', 'topic__name', 'topic__language__name')
        )
    except Exception:
        coding_topic_levels = []

    return {
        'maths_topics': maths_topics,
        'maths_levels': maths_levels,
        'coding_topic_levels': coding_topic_levels,
    }


@login_required
def teacher_lobby(request, join_code):
    """Teacher waits in the lobby; students join."""
    if not _require_teacher(request):
        return redirect('subjects_hub')

    session = get_object_or_404(BrainBuzzSession, join_code=join_code.upper(), created_by=request.user)
    if session.state == BrainBuzzSession.ENDED:
        return redirect('brainbuzz:teacher_end', join_code=join_code)
    if session.state == BrainBuzzSession.IN_PROGRESS:
        return redirect('brainbuzz:teacher_ingame', join_code=join_code)

    join_url = request.build_absolute_uri(f'/brainbuzz/join/?code={join_code}')
    return render(request, 'brainbuzz/teacher_lobby.html', {
        'session': session,
        'join_url': join_url,
    })


@login_required
def teacher_ingame(request, join_code):
    """Teacher view during the quiz — shows current question and controls."""
    if not _require_teacher(request):
        return redirect('subjects_hub')

    session = get_object_or_404(BrainBuzzSession, join_code=join_code.upper(), created_by=request.user)
    if session.state == BrainBuzzSession.LOBBY:
        return redirect('brainbuzz:teacher_lobby', join_code=join_code)
    if session.state == BrainBuzzSession.ENDED:
        return redirect('brainbuzz:teacher_end', join_code=join_code)

    return render(request, 'brainbuzz/teacher_ingame.html', {'session': session})


@login_required
def teacher_end(request, join_code):
    """Teacher sees the final leaderboard and can export CSV."""
    if not _require_teacher(request):
        return redirect('subjects_hub')

    session = get_object_or_404(BrainBuzzSession, join_code=join_code.upper(), created_by=request.user)
    leaderboard = session.leaderboard()
    return render(request, 'brainbuzz/teacher_end.html', {
        'session': session,
        'leaderboard': leaderboard,
    })


@login_required
def export_csv(request, join_code):
    """Download final standings as CSV."""
    if not _require_teacher(request):
        return redirect('subjects_hub')

    session = get_object_or_404(BrainBuzzSession, join_code=join_code.upper(), created_by=request.user)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="brainbuzz_{join_code}_results.csv"'

    writer = csv.writer(response)
    writer.writerow(['Rank', 'Nickname', 'User', 'Total Score', 'Joined At'])
    for rank, participant in enumerate(session.leaderboard(), start=1):
        writer.writerow([
            rank,
            participant.nickname,
            participant.user.get_full_name() if participant.user else '—',
            participant.total_score,
            participant.joined_at.strftime('%Y-%m-%d %H:%M:%S'),
        ])
    return response


# ---------------------------------------------------------------------------
# Student views
# ---------------------------------------------------------------------------

def join(request):
    """Student enters a join code and nickname."""
    prefill_code = request.GET.get('code', '').upper()
    return render(request, 'brainbuzz/student_join.html', {'prefill_code': prefill_code})


def student_play(request, join_code):
    """Student in-game view — polls for state and submits answers."""
    session = get_object_or_404(BrainBuzzSession, join_code=join_code.upper())
    if session.state == BrainBuzzSession.ENDED:
        participant_id = _get_participant_id(request, join_code)
        participant = None
        if participant_id:
            participant = BrainBuzzParticipant.objects.filter(
                id=participant_id, session=session
            ).first()
        return render(request, 'brainbuzz/student_results.html', {
            'session': session,
            'participant': participant,
            'leaderboard': session.leaderboard(),
        })

    participant_id = _get_participant_id(request, join_code)
    if not participant_id:
        return redirect(f'/brainbuzz/join/?code={join_code}')

    participant = BrainBuzzParticipant.objects.filter(
        id=participant_id, session=session, is_active=True
    ).first()
    if not participant:
        return redirect(f'/brainbuzz/join/?code={join_code}')

    return render(request, 'brainbuzz/student_play.html', {
        'session': session,
        'participant': participant,
    })


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

@require_GET
def api_session_state(request, join_code):
    """Versioned polling endpoint.

    ?since=<state_version>  → 304 if unchanged, else full state.
    """
    session = get_object_or_404(BrainBuzzSession, join_code=join_code.upper())

    try:
        since = int(request.GET.get('since', -1))
    except (ValueError, TypeError):
        since = -1

    if since >= 0 and session.state_version == since:
        return HttpResponse(status=304)

    return JsonResponse(_session_state_payload(session))


@require_POST
@login_required
def api_teacher_action(request, join_code):
    """Teacher controls: start | next | end.

    POST body JSON:
      { "action": "start" | "next" | "end",
        "expected_current_index": <int|null> }

    Idempotent: if expected_current_index mismatches the server's current
    index the action is treated as a no-op (returns current state).
    """
    if not _require_teacher(request):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    session = get_object_or_404(BrainBuzzSession, join_code=join_code.upper(), created_by=request.user)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    action = body.get('action', '').strip()
    expected_index = body.get('expected_current_index')  # may be null

    with transaction.atomic():
        session = BrainBuzzSession.objects.select_for_update().get(pk=session.pk)

        if action == 'start':
            if session.state != BrainBuzzSession.LOBBY:
                return JsonResponse(_session_state_payload(session))
            first_q = session.questions.order_by('order_index').first()
            if first_q is None:
                return JsonResponse({'error': 'No questions in session'}, status=400)
            first_q.start()
            session.state = BrainBuzzSession.IN_PROGRESS
            session.current_question_index = 0
            session.bump_version()

        elif action == 'next':
            if session.state != BrainBuzzSession.IN_PROGRESS:
                return JsonResponse(_session_state_payload(session))
            # Idempotency check
            if expected_index is not None and session.current_question_index != expected_index:
                return JsonResponse(_session_state_payload(session))
            next_index = (session.current_question_index or 0) + 1
            next_q = session.questions.filter(order_index=next_index).first()
            if next_q is None:
                # No more questions — end the session
                session.state = BrainBuzzSession.ENDED
                session.current_question_index = None
                session.bump_version()
            else:
                next_q.start()
                session.current_question_index = next_index
                session.bump_version()

        elif action == 'end':
            if session.state == BrainBuzzSession.ENDED:
                return JsonResponse(_session_state_payload(session))
            session.state = BrainBuzzSession.ENDED
            session.current_question_index = None
            session.bump_version()

        else:
            return JsonResponse({'error': f'Unknown action: {action!r}'}, status=400)

    return JsonResponse(_session_state_payload(session))


@require_POST
def api_join(request):
    """Student joins a session.

    POST body JSON:
      { "join_code": "ABC123", "nickname": "Alice" }

    Returns participant_id which is stored in the Django session.
    """
    if not _check_join_rate_limit(request):
        return JsonResponse({'error': 'Too many join attempts. Wait a minute and try again.'}, status=429)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    join_code = body.get('join_code', '').strip().upper()
    nickname = body.get('nickname', '').strip()[:50]

    if not join_code or not nickname:
        return JsonResponse({'error': 'join_code and nickname are required'}, status=400)

    session = BrainBuzzSession.objects.filter(join_code=join_code).first()
    if session is None:
        return JsonResponse({'error': 'Session not found'}, status=404)
    if session.state != BrainBuzzSession.LOBBY:
        return JsonResponse({'error': 'Session has already started or ended. Joining is closed.'}, status=409)

    # Handle duplicate nickname
    resolved_nickname = BrainBuzzParticipant.resolve_nickname(session, nickname)

    user = request.user if request.user.is_authenticated else None
    participant = BrainBuzzParticipant.objects.create(
        session=session,
        user=user,
        nickname=resolved_nickname,
    )

    _set_participant_id(request, join_code, participant.id)

    return JsonResponse({
        'participant_id': participant.id,
        'nickname': resolved_nickname,
        'join_code': join_code,
        'redirect_url': f'/brainbuzz/play/{join_code}/',
    })


@require_POST
def api_submit(request, join_code):
    """Student submits an answer for the current question.

    POST body JSON:
      { "participant_id": <int>,
        "question_index": <int>,
        "answer_payload": {"option_id": "..."} | {"text": "..."} }

    Returns correctness and score awarded.
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    session = get_object_or_404(BrainBuzzSession, join_code=join_code.upper())

    if session.state != BrainBuzzSession.IN_PROGRESS:
        return JsonResponse({'error': 'Session is not in progress'}, status=409)

    participant_id = _get_participant_id(request, join_code)
    if not participant_id:
        return JsonResponse({'error': 'Not joined'}, status=403)

    participant = get_object_or_404(BrainBuzzParticipant, id=participant_id, session=session, is_active=True)

    question_index = body.get('question_index')
    answer_payload = body.get('answer_payload', {})

    if question_index != session.current_question_index:
        return JsonResponse({'error': 'Wrong question index — this question is no longer active'}, status=409)

    session_question = get_object_or_404(
        BrainBuzzSessionQuestion,
        session=session,
        order_index=question_index,
    )

    # Deadline enforcement (500 ms grace)
    now = timezone.now()
    if not session_question.is_submission_on_time(now):
        return JsonResponse({
            'error': 'Deadline passed',
            'is_correct': False,
            'score_awarded': 0,
        }, status=200)

    # Idempotency — reject duplicate submission
    if BrainBuzzSubmission.objects.filter(participant=participant, session_question=session_question).exists():
        return JsonResponse({'error': 'Already submitted for this question'}, status=409)

    is_correct = session_question.check_answer(answer_payload)

    if is_correct and session_question.question_deadline_utc:
        seconds_remaining = (session_question.question_deadline_utc - now).total_seconds()
        score = calculate_brainbuzz_score(session_question.time_limit_seconds, seconds_remaining)
    else:
        score = 0

    with transaction.atomic():
        BrainBuzzSubmission.objects.create(
            participant=participant,
            session_question=session_question,
            answer_payload=answer_payload,
            is_correct=is_correct,
            score_awarded=score,
        )
        if score > 0:
            BrainBuzzParticipant.objects.filter(pk=participant.pk).update(
                total_score=F('total_score') + score
            )

    participant.refresh_from_db()
    return JsonResponse({
        'is_correct': is_correct,
        'score_awarded': score,
        'total_score': participant.total_score,
    })


@require_GET
def api_leaderboard(request, join_code):
    """Current leaderboard for a session (public — any participant may read)."""
    session = get_object_or_404(BrainBuzzSession, join_code=join_code.upper())
    entries = list(
        session.leaderboard().values('id', 'nickname', 'total_score')
    )
    for rank, entry in enumerate(entries, start=1):
        entry['rank'] = rank
    return JsonResponse({'leaderboard': entries, 'state': session.state})
