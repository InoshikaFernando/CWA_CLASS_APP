"""
BrainBuzz views — teacher and student flows plus JSON API endpoints.

Teacher flows (login + is_teacher required):
  create_session          GET/POST   /brainbuzz/create/
  teacher_lobby           GET        /brainbuzz/session/<code>/lobby/
  teacher_ingame          GET        /brainbuzz/session/<code>/play/
  teacher_end             GET        /brainbuzz/session/<code>/end/
  export_csv              GET        /brainbuzz/session/<code>/export/
  repeat_session          POST       /brainbuzz/session/<code>/repeat/

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
import re
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.db.models import Avg, Count, F, Q
from django.http import JsonResponse, HttpResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .models import (
    BrainBuzzSession,
    BrainBuzzSessionQuestion,
    BrainBuzzParticipant,
    BrainBuzzAnswer,
    QUESTION_TYPE_MCQ,
    QUESTION_TYPE_TRUE_FALSE,
    QUESTION_TYPE_SHORT_ANSWER,
    QUESTION_TYPE_FILL_BLANK,
    QUIZ_QUESTION_TYPE_CHOICES,
)
from .scoring import calculate_points, is_short_answer_correct
from .ranking import compute_ranks
from .utils import generate_join_code

# Nickname: 1–20 chars, letters / digits / internal spaces
_NICKNAME_RE = re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9 ]{0,19}$')
_NICKNAME_MAX = 20


def _resolve_nickname(session: 'BrainBuzzSession', desired: str) -> str:
    """Return desired nickname (or auto-suffixed variant) ensuring uniqueness in session."""
    desired = desired.strip()[:_NICKNAME_MAX]
    if not BrainBuzzParticipant.objects.filter(session=session, nickname=desired).exists():
        return desired
    # Suffix #2 … #99.  Truncate base to leave room for " #NN".
    base = desired[:16]
    for n in range(2, 100):
        suffix = f' #{n}'
        candidate = (base + suffix)[:_NICKNAME_MAX]
        if not BrainBuzzParticipant.objects.filter(session=session, nickname=candidate).exists():
            return candidate
    return desired  # extremely unlikely; let DB constraint catch it


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


def _build_distribution(session: BrainBuzzSession, current_q: BrainBuzzSessionQuestion) -> list:
    """Return answer distribution for the current question (used in REVEAL phase).

    For MCQ/TF: [{label, text, count, is_correct}, ...]  ordered by label.
    For SA/FB:  [{label: 'correct', count, is_correct: True}, {label: 'incorrect', count, is_correct: False}]
    """
    if current_q is None:
        return []

    answers_qs = BrainBuzzAnswer.objects.filter(session_question=current_q)

    if current_q.question_type in (QUESTION_TYPE_MCQ, QUESTION_TYPE_TRUE_FALSE):
        counts = dict(
            answers_qs.values('selected_option_label')
            .annotate(n=Count('id'))
            .values_list('selected_option_label', 'n')
        )
        correct_labels = {
            opt['label']
            for opt in current_q.options_json
            if opt.get('is_correct')
        }
        distribution = []
        for opt in current_q.options_json:
            label = opt.get('label', '')
            distribution.append({
                'label': label,
                'text': opt.get('text', ''),
                'count': counts.get(label, 0),
                'is_correct': opt.get('is_correct', False),
            })
        return distribution
    else:
        # Short answer / fill-blank: correct vs incorrect
        correct_count = answers_qs.filter(is_correct=True).count()
        incorrect_count = answers_qs.filter(is_correct=False).count()
        return [
            {'label': 'Correct', 'text': '', 'count': correct_count, 'is_correct': True},
            {'label': 'Incorrect', 'text': '', 'count': incorrect_count, 'is_correct': False},
        ]


def _session_state_payload(session: BrainBuzzSession) -> dict:
    """Build the canonical session state dict returned by the polling API."""
    try:
        current_q = session.questions.get(order=session.current_index)
    except BrainBuzzSessionQuestion.DoesNotExist:
        current_q = None

    question_data = None
    if current_q is not None:
        question_data = {
            'order': current_q.order,
            'question_text': current_q.question_text,
            'question_type': current_q.question_type,
            'options': current_q.options_json,
            'question_deadline': (
                session.question_deadline.isoformat()
                if session.question_deadline else None
            ),
        }

    participants = list(
        session.participants.order_by('-score', 'joined_at').values('id', 'nickname', 'score')
    )

    answers_received = 0
    answer_distribution = []
    if current_q is not None:
        answers_received = BrainBuzzAnswer.objects.filter(session_question=current_q).count()
        if session.status == BrainBuzzSession.STATUS_REVEAL:
            answer_distribution = _build_distribution(session, current_q)

    return {
        'code': session.code,
        'status': session.status,
        'state_version': session.state_version,
        'current_index': session.current_index,
        'time_per_question_sec': session.time_per_question_sec,
        'question': question_data,
        'participant_count': session.participants.count(),
        'participants': participants,
        'total_questions': session.questions.count(),
        'answers_received': answers_received,
        'answer_distribution': answer_distribution,
    }


def _snapshot_maths_questions(session: BrainBuzzSession, topic_id: int, level_id: int, count: int):
    """Snapshot maths questions into BrainBuzzSessionQuestion rows."""
    from maths.models import Question, Answer

    qs = (
        Question.objects
        .filter(topic_id=topic_id, level_id=level_id)
        .exclude(question_type='calculation')
        .order_by('?')[:count]
    )
    for i, q in enumerate(qs):
        answers = list(Answer.objects.filter(question=q).order_by('order'))
        options = [
            {'label': chr(65 + idx), 'text': a.answer_text, 'is_correct': a.is_correct}
            for idx, a in enumerate(answers)
        ]
        BrainBuzzSessionQuestion.objects.create(
            session=session,
            order=i,
            question_text=q.question_text,
            question_type=q.question_type if q.question_type in dict(QUIZ_QUESTION_TYPE_CHOICES) else QUESTION_TYPE_MCQ,
            options_json=options,
            correct_short_answer=None,
            points_base=1000,
            source_model='MathsQuestion',
            source_id=q.id,
        )


def _snapshot_quiz_questions(session: BrainBuzzSession, quiz) -> None:
    """Snapshot all questions from a custom BrainBuzzQuiz into BrainBuzzSessionQuestion rows."""
    from .models import BrainBuzzQuizQuestion

    for q in quiz.quiz_questions.order_by('order'):
        options = [
            {'label': chr(65 + idx), 'text': opt.option_text, 'is_correct': opt.is_correct}
            for idx, opt in enumerate(q.quiz_options.order_by('order'))
        ]
        BrainBuzzSessionQuestion.objects.create(
            session=session,
            order=q.order,
            question_text=q.question_text,
            question_type=q.question_type if q.question_type in dict(QUIZ_QUESTION_TYPE_CHOICES) else QUESTION_TYPE_MCQ,
            options_json=options,
            correct_short_answer=q.correct_short_answer or None,
            points_base=1000,
            source_model='BrainBuzzQuizQuestion',
            source_id=q.id,
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
            {'label': chr(65 + idx), 'text': a.answer_text, 'is_correct': a.is_correct}
            for idx, a in enumerate(answers)
        ]
        BrainBuzzSessionQuestion.objects.create(
            session=session,
            order=i,
            question_text=ex.description,
            question_type=ex.question_type if ex.question_type in dict(QUIZ_QUESTION_TYPE_CHOICES) else QUESTION_TYPE_MCQ,
            options_json=options,
            correct_short_answer=ex.correct_short_answer or None,
            points_base=1000,
            source_model='CodingExercise',
            source_id=ex.id,
        )


def _generate_qr_data_uri(url: str) -> str | None:
    """Return a data: URI PNG for the given URL, or None if qrcode is unavailable."""
    try:
        import io
        import base64
        import qrcode  # type: ignore
        img = qrcode.make(url)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f'data:image/png;base64,{b64}'
    except Exception:
        return None


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
        subject_key = request.POST.get('subject', '').strip()
        count_raw = request.POST.get('question_count', '10').strip()

        try:
            question_count = max(1, min(30, int(count_raw)))
        except (ValueError, TypeError):
            question_count = 10

        if not subject_key:
            return render(request, 'brainbuzz/teacher_create.html', {
                'error': 'Invalid subject.',
                **_create_context(),
            })

        slug_mapping = {
            'maths': 'mathematics',
            'coding': 'coding',
        }
        subject_slug = slug_mapping.get(subject_key, subject_key)

        from classroom.models import Subject
        subject_obj = Subject.objects.filter(slug=subject_slug).first()
        if not subject_obj:
            return render(request, 'brainbuzz/teacher_create.html', {
                'error': 'Invalid subject.',
                **_create_context(),
            })

        if subject_slug == 'mathematics':
            topic_id = request.POST.get('topic_id', '').strip()
            level_id = request.POST.get('level_id', '').strip()
            if not topic_id or not level_id:
                return render(request, 'brainbuzz/teacher_create.html', {
                    'error': 'Select a topic and level.',
                    **_create_context(),
                })
            config = {
                'subject': subject_key,
                'topic_id': int(topic_id),
                'level_id': int(level_id),
                'question_count': question_count,
                'time_per_question_sec': int(request.POST.get('time_per_question_sec', 20)),
            }
            with transaction.atomic():
                session = BrainBuzzSession.objects.create(
                    code=generate_join_code(),
                    host=request.user,
                    subject=subject_obj,
                    status=BrainBuzzSession.STATUS_LOBBY,
                    time_per_question_sec=config['time_per_question_sec'],
                    config_json=config,
                )
                _snapshot_maths_questions(session, int(topic_id), int(level_id), question_count)
            if not session.questions.exists():
                session.delete()
                return render(request, 'brainbuzz/teacher_create.html', {
                    'error': 'No suitable questions found for that topic and level. Try a different selection.',
                    **_create_context(),
                })
            return redirect('brainbuzz:teacher_lobby', join_code=session.code)

        elif subject_slug == 'coding':
            topic_level_id = request.POST.get('topic_level_id', '').strip()
            if not topic_level_id:
                return render(request, 'brainbuzz/teacher_create.html', {
                    'error': 'Select a coding topic level.',
                    **_create_context(),
                })
            config = {
                'subject': subject_key,
                'topic_level_id': int(topic_level_id),
                'question_count': question_count,
                'time_per_question_sec': int(request.POST.get('time_per_question_sec', 20)),
            }
            with transaction.atomic():
                session = BrainBuzzSession.objects.create(
                    code=generate_join_code(),
                    host=request.user,
                    subject=subject_obj,
                    status=BrainBuzzSession.STATUS_LOBBY,
                    time_per_question_sec=config['time_per_question_sec'],
                    config_json=config,
                )
                _snapshot_coding_questions(session, int(topic_level_id), question_count)
            if not session.questions.exists():
                session.delete()
                return render(request, 'brainbuzz/teacher_create.html', {
                    'error': 'No MCQ/TF/short-answer coding exercises found for that topic level.',
                    **_create_context(),
                })
            return redirect('brainbuzz:teacher_lobby', join_code=session.code)

        return render(request, 'brainbuzz/teacher_create.html', {
            'error': 'Invalid subject.',
            **_create_context(),
        })

    return render(request, 'brainbuzz/teacher_create.html', _create_context())


def _create_context():
    """Build context for the create-session form via the subject plugin registry."""
    from classroom.subject_registry import brainbuzz_plugins
    from django.db.models import Count

    ctx = {
        'bb_subject_choices': [],
        'maths_topics': [],
        'maths_levels': [],
        'coding_topic_levels': [],
    }
    for plugin in brainbuzz_plugins():
        ctx['bb_subject_choices'].append((plugin.brainbuzz_subject_key, plugin.display_name))
        ctx.update(plugin.brainbuzz_topic_choices())

    # Annotate maths levels with question counts + per-topic breakdown for popup
    try:
        from maths.models import Question
        base_qs = Question.objects.filter(school__isnull=True, topic__subject__slug='mathematics')
        counts = {
            r['level__level_number']: r['n']
            for r in base_qs.values('level__level_number').annotate(n=Count('id'))
        }
        topic_rows = (base_qs
            .values('level__level_number', 'topic__name')
            .annotate(n=Count('id'))
            .order_by('level__level_number', 'topic__name'))
        level_topic_map = {}
        for r in topic_rows:
            ln = r['level__level_number']
            if ln not in level_topic_map:
                level_topic_map[ln] = []
            level_topic_map[ln].append({'topic': r['topic__name'], 'count': r['n']})
        for lvl in ctx['maths_levels']:
            lvl['question_count'] = counts.get(lvl['level_number'], 0)
            lvl['topics'] = level_topic_map.get(lvl['level_number'], [])
    except Exception:
        for lvl in ctx['maths_levels']:
            lvl['question_count'] = 0
            lvl['topics'] = []

    # Annotate coding topic-levels with question counts + question titles for popup
    try:
        from coding.models import CodingExercise
        counts = {
            r['topic_level_id']: r['n']
            for r in CodingExercise.objects.filter(is_active=True).values('topic_level_id').annotate(n=Count('id'))
        }
        tl_q_map = {}
        for ex in (CodingExercise.objects
                   .filter(is_active=True, question_type='multiple_choice')
                   .values('topic_level_id', 'title')
                   .order_by('topic_level_id', 'id')):
            tid = ex['topic_level_id']
            if tid not in tl_q_map:
                tl_q_map[tid] = []
            tl_q_map[tid].append(ex['title'])
        for tl in ctx['coding_topic_levels']:
            tl['question_count'] = counts.get(tl['id'], 0)
            tl['questions'] = tl_q_map.get(tl['id'], [])
    except Exception:
        for tl in ctx['coding_topic_levels']:
            tl['question_count'] = 0
            tl['questions'] = []

    return ctx


_INGAME_STATUSES = {
    BrainBuzzSession.STATUS_ACTIVE,
    BrainBuzzSession.STATUS_REVEAL,
    BrainBuzzSession.STATUS_BETWEEN,
}


@login_required
def teacher_lobby(request, join_code):
    """Teacher waits in the lobby; students join."""
    if not _require_teacher(request):
        return redirect('subjects_hub')

    session = get_object_or_404(BrainBuzzSession, code=join_code.upper(), host=request.user)
    if session.status == BrainBuzzSession.STATUS_FINISHED:
        return redirect('brainbuzz:teacher_end', join_code=join_code)
    if session.status in _INGAME_STATUSES:
        return redirect('brainbuzz:teacher_ingame', join_code=join_code)

    join_url = request.build_absolute_uri(f'/brainbuzz/join/?code={session.code}')
    qr_data_uri = _generate_qr_data_uri(join_url)
    
    # Get initial state for the frontend
    initial_state = _session_state_payload(session)

    return render(request, 'brainbuzz/teacher_lobby.html', {
        'session': session,
        'join_url': join_url,
        'qr_data_uri': qr_data_uri,
        'initial_participant_count': initial_state['participant_count'],
        'initial_participants': initial_state['participants'],
        'initial_state_version': initial_state['state_version'],
    })


@login_required
def teacher_ingame(request, join_code):
    """Teacher view during the quiz — shows current question and controls."""
    if not _require_teacher(request):
        return redirect('subjects_hub')

    session = get_object_or_404(BrainBuzzSession, code=join_code.upper(), host=request.user)
    if session.status == BrainBuzzSession.STATUS_LOBBY:
        return redirect('brainbuzz:teacher_lobby', join_code=join_code)
    if session.status == BrainBuzzSession.STATUS_FINISHED:
        return redirect('brainbuzz:teacher_end', join_code=join_code)

    return render(request, 'brainbuzz/teacher_ingame.html', {'session': session})


@login_required
def teacher_end(request, join_code):
    """Teacher sees the final leaderboard and can export CSV."""
    if not _require_teacher(request):
        return redirect('subjects_hub')

    session = get_object_or_404(BrainBuzzSession, code=join_code.upper(), host=request.user)
    leaderboard = list(
        session.participants
        .annotate(
            correct_count=Count('answers', filter=Q(answers__is_correct=True)),
            avg_response_ms=Avg('answers__time_taken_ms'),
        )
        .order_by('-score', 'joined_at')
    )
    return render(request, 'brainbuzz/teacher_end.html', {
        'session': session,
        'leaderboard': leaderboard,
        'has_config': bool(session.config_json),
    })


@login_required
def export_csv(request, join_code):
    """Download final standings as CSV."""
    if not _require_teacher(request):
        return redirect('subjects_hub')

    session = get_object_or_404(BrainBuzzSession, code=join_code.upper(), host=request.user)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="brainbuzz_{join_code}_results.csv"'

    writer = csv.writer(response)
    writer.writerow(['Rank', 'Nickname', 'User', 'Total Score', 'Correct', 'Avg Response (ms)', 'Joined At'])

    participants = (
        session.participants
        .annotate(
            correct_count=Count('answers', filter=Q(answers__is_correct=True)),
            avg_response_ms=Avg('answers__time_taken_ms'),
        )
        .order_by('-score', 'joined_at')
    )

    for rank, p in enumerate(participants, start=1):
        avg_ms = round(p.avg_response_ms) if p.avg_response_ms is not None else ''
        writer.writerow([
            rank,
            p.nickname,
            p.student.get_full_name() if p.student else '',
            p.score,
            p.correct_count,
            avg_ms,
            p.joined_at.strftime('%Y-%m-%d %H:%M:%S'),
        ])
    return response


@login_required
@require_POST
def repeat_session(request, join_code):
    """Create a fresh session using the same config as an existing session."""
    if not _require_teacher(request):
        return redirect('subjects_hub')

    original = get_object_or_404(BrainBuzzSession, code=join_code.upper(), host=request.user)
    config = original.config_json
    if not config:
        return redirect('brainbuzz:create')

    subject_key = config.get('subject', '')
    question_count = config.get('question_count', 10)
    time_per_q = config.get('time_per_question_sec', 20)

    slug_mapping = {'maths': 'mathematics', 'coding': 'coding'}
    subject_slug = slug_mapping.get(subject_key, subject_key)

    from classroom.models import Subject
    subject_obj = Subject.objects.filter(slug=subject_slug).first()
    if not subject_obj:
        return redirect('brainbuzz:create')

    with transaction.atomic():
        new_session = BrainBuzzSession.objects.create(
            code=generate_join_code(),
            host=request.user,
            subject=subject_obj,
            status=BrainBuzzSession.STATUS_LOBBY,
            time_per_question_sec=time_per_q,
            config_json=config,
        )
        if subject_slug == 'mathematics':
            _snapshot_maths_questions(
                new_session,
                config['topic_id'],
                config['level_id'],
                question_count,
            )
        elif subject_slug == 'coding':
            _snapshot_coding_questions(
                new_session,
                config['topic_level_id'],
                question_count,
            )

    if not new_session.questions.exists():
        new_session.delete()
        return redirect('brainbuzz:create')

    return redirect('brainbuzz:teacher_lobby', join_code=new_session.code)


# ---------------------------------------------------------------------------
# Student views
# ---------------------------------------------------------------------------

def join(request):
    """Student enters a join code and nickname."""
    prefill_code = request.GET.get('code', '').upper()
    return render(request, 'brainbuzz/student_join.html', {'prefill_code': prefill_code})


def student_play(request, join_code):
    """Student in-game view — polls for state and submits answers."""
    session = get_object_or_404(BrainBuzzSession, code=join_code.upper())
    if session.status == BrainBuzzSession.STATUS_FINISHED:
        participant_id = _get_participant_id(request, join_code)
        participant = None
        if participant_id:
            participant = BrainBuzzParticipant.objects.filter(
                id=participant_id, session=session
            ).first()
        leaderboard = list(session.participants.order_by('-score', 'joined_at'))
        return render(request, 'brainbuzz/student_results.html', {
            'session': session,
            'participant': participant,
            'leaderboard': leaderboard,
        })

    participant_id = _get_participant_id(request, join_code)
    if not participant_id:
        return redirect(f'/brainbuzz/join/?code={join_code}')

    participant = BrainBuzzParticipant.objects.filter(
        id=participant_id, session=session
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
    session = get_object_or_404(BrainBuzzSession, code=join_code.upper())

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
    """Teacher controls: start | reveal | next | end.

    POST body JSON:
      { "action": "start" | "reveal" | "next" | "end",
        "expected_current_index": <int|null> }

    State machine:
      start  : LOBBY  → ACTIVE  (sets deadline for q0)
      reveal : ACTIVE → REVEAL  (freeze deadline, show distribution)
      next   : REVEAL → ACTIVE(q+1) or FINISHED
               ACTIVE → ACTIVE(q+1) or FINISHED  (skip-reveal shortcut)
      end    : any    → FINISHED

    Idempotent: if expected_current_index mismatches the action is a no-op.
    """
    if not _require_teacher(request):
        return JsonResponse({'error': 'Forbidden'}, status=403)

    session = get_object_or_404(BrainBuzzSession, code=join_code.upper(), host=request.user)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    action = body.get('action', '').strip()
    expected_index = body.get('expected_current_index')

    with transaction.atomic():
        session = BrainBuzzSession.objects.select_for_update().get(pk=session.pk)

        if action == 'start':
            if session.status != BrainBuzzSession.STATUS_LOBBY:
                return JsonResponse(_session_state_payload(session))
            first_q = session.questions.order_by('order').first()
            if first_q is None:
                return JsonResponse({'error': 'No questions in session'}, status=400)
            # Require at least 1 participant to have joined
            participant_count = session.participants.count()
            if participant_count < 1:
                return JsonResponse({'error': 'At least 1 participant must join before starting'}, status=400)
            session.status = BrainBuzzSession.STATUS_ACTIVE
            session.current_index = 0
            session.question_deadline = timezone.now() + timedelta(seconds=session.time_per_question_sec)
            session.started_at = timezone.now()
            session.state_version += 1
            session.save()

        elif action == 'reveal':
            if session.status != BrainBuzzSession.STATUS_ACTIVE:
                return JsonResponse(_session_state_payload(session))
            if expected_index is not None and session.current_index != expected_index:
                return JsonResponse(_session_state_payload(session))
            session.status = BrainBuzzSession.STATUS_REVEAL
            session.question_deadline = None
            session.state_version += 1
            session.save()

        elif action == 'next':
            if session.status not in (
                BrainBuzzSession.STATUS_REVEAL,
                BrainBuzzSession.STATUS_ACTIVE,
                BrainBuzzSession.STATUS_BETWEEN,
            ):
                return JsonResponse(_session_state_payload(session))
            if expected_index is not None and session.current_index != expected_index:
                return JsonResponse(_session_state_payload(session))
            next_index = session.current_index + 1
            next_q = session.questions.filter(order=next_index).first()
            if next_q is None:
                session.status = BrainBuzzSession.STATUS_FINISHED
                session.question_deadline = None
                session.ended_at = timezone.now()
                session.state_version += 1
                session.save()
            else:
                session.status = BrainBuzzSession.STATUS_ACTIVE
                session.current_index = next_index
                session.question_deadline = timezone.now() + timedelta(seconds=session.time_per_question_sec)
                session.state_version += 1
                session.save()

        elif action == 'end':
            if session.status == BrainBuzzSession.STATUS_FINISHED:
                return JsonResponse(_session_state_payload(session))
            session.status = BrainBuzzSession.STATUS_FINISHED
            session.question_deadline = None
            session.ended_at = timezone.now()
            session.state_version += 1
            session.save()

        else:
            return JsonResponse({'error': f'Unknown action: {action!r}'}, status=400)

    return JsonResponse(_session_state_payload(session))


@require_POST
def api_join(request):
    """Student joins a session.

    POST body JSON:
      { "code": "ABC123", "nickname": "Alice" }

    Returns participant_id which is stored in the Django session.
    Duplicate nicknames are auto-suffixed (#2, #3, …).
    """
    if not _check_join_rate_limit(request):
        return JsonResponse({'error': 'Too many join attempts. Wait a minute and try again.'}, status=429)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    code = body.get('code', '').strip().upper()
    nickname_raw = body.get('nickname', '').strip()

    if not code:
        return JsonResponse({'error': 'Game code is required.'}, status=400)

    if not nickname_raw:
        return JsonResponse({'error': 'Nickname is required.'}, status=400)

    if len(nickname_raw) > _NICKNAME_MAX:
        return JsonResponse(
            {'error': f'Nickname must be {_NICKNAME_MAX} characters or fewer.'},
            status=400,
        )

    if not _NICKNAME_RE.match(nickname_raw):
        return JsonResponse(
            {'error': 'Nickname may only contain letters, numbers, and spaces.'},
            status=400,
        )

    session = BrainBuzzSession.objects.filter(code=code).first()
    if session is None:
        return JsonResponse({'error': 'Game not found. Check your code and try again.'}, status=404)

    if session.status == BrainBuzzSession.STATUS_FINISHED:
        return JsonResponse({'error': 'This game has ended.'}, status=409)

    if session.status == BrainBuzzSession.STATUS_CANCELLED:
        return JsonResponse({'error': 'This game has been cancelled.'}, status=409)

    if session.status != BrainBuzzSession.STATUS_LOBBY:
        return JsonResponse({'error': 'This game has already started. Ask your teacher for the next session.'}, status=409)

    resolved_nickname = _resolve_nickname(session, nickname_raw)
    user = request.user if request.user.is_authenticated else None

    participant = BrainBuzzParticipant.objects.create(
        session=session,
        student=user,
        nickname=resolved_nickname,
    )

    _set_participant_id(request, code, participant.id)

    return JsonResponse({
        'participant_id': participant.id,
        'nickname': resolved_nickname,
        'code': code,
        'redirect_url': f'/brainbuzz/play/{code}/',
    })


@require_POST
def api_submit(request, join_code):
    """Student submits an answer for the current question.

    POST body JSON:
      { "participant_id": <int>,
        "question_index": <int>,
        "answer_payload": {"option_label": "A"} | {"text": "..."} }

    Returns correctness and score awarded.
    """
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    session = get_object_or_404(BrainBuzzSession, code=join_code.upper())

    if session.status != BrainBuzzSession.STATUS_ACTIVE:
        return JsonResponse({'error': 'Session is not in progress'}, status=409)

    participant_id = _get_participant_id(request, join_code)
    if not participant_id:
        return JsonResponse({'error': 'Not joined'}, status=403)

    participant = get_object_or_404(BrainBuzzParticipant, id=participant_id, session=session)

    question_index = body.get('question_index')
    answer_payload = body.get('answer_payload', {})
    time_taken_ms = body.get('time_taken_ms', 0)

    if question_index != session.current_index:
        return JsonResponse({'error': 'Wrong question index — this question is no longer active'}, status=409)

    session_question = get_object_or_404(
        BrainBuzzSessionQuestion,
        session=session,
        order=question_index,
    )

    now = timezone.now()
    grace_period_ms = 500
    is_on_time = session.question_deadline is None or (
        now <= session.question_deadline + timedelta(milliseconds=grace_period_ms)
    )
    is_late = session.question_deadline is not None and (
        now > session.question_deadline + timedelta(milliseconds=grace_period_ms)
    )

    existing = BrainBuzzAnswer.objects.filter(
        participant=participant,
        session_question=session_question
    ).first()
    if existing:
        return JsonResponse({
            'error': 'Already submitted for this question',
            'is_correct': existing.is_correct,
            'score_awarded': existing.points_awarded,
        }, status=409)

    is_correct = False
    selected_option = answer_payload.get('option_label')
    short_answer = answer_payload.get('text', '')

    if session_question.question_type in [QUESTION_TYPE_MCQ, QUESTION_TYPE_TRUE_FALSE]:
        if selected_option:
            for opt in session_question.options_json:
                if opt.get('label') == selected_option and opt.get('is_correct'):
                    is_correct = True
                    break
    else:
        # For short answer / fill blank: use flexible matching
        if short_answer and session_question.correct_short_answer:
            is_correct = is_short_answer_correct(
                short_answer,
                session_question.correct_short_answer,
                case_sensitive=False
            )

    # Calculate points using Kahoot-equivalent formula
    points_awarded = calculate_points(
        is_correct=is_correct,
        time_taken_ms=time_taken_ms,
        time_per_question_sec=session.time_per_question_sec,
        points_base=session_question.points_base,
        is_late=is_late
    )

    with transaction.atomic():
        BrainBuzzAnswer.objects.create(
            participant=participant,
            session_question=session_question,
            selected_option_label=selected_option,
            short_answer_text=short_answer if short_answer else None,
            time_taken_ms=time_taken_ms,
            points_awarded=points_awarded,
            is_correct=is_correct,
        )
        
        # Update participant score and last_correct_time
        update_data = {'score': F('score') + points_awarded}
        if is_correct:
            update_data['last_correct_time'] = now
        
        BrainBuzzParticipant.objects.filter(pk=participant.pk).update(**update_data)

    participant.refresh_from_db()
    return JsonResponse({
        'is_correct': is_correct,
        'score_awarded': points_awarded,
        'total_score': participant.score,
    })



@require_GET
def api_leaderboard(request, join_code):
    """Current leaderboard for a session (public — any participant may read)."""
    session = get_object_or_404(BrainBuzzSession, code=join_code.upper())
    entries = list(
        session.participants
        .annotate(
            correct_count=Count('answers', filter=Q(answers__is_correct=True)),
            avg_response_ms=Avg('answers__time_taken_ms'),
        )
        .order_by('-score', 'joined_at')
        .values('id', 'nickname', 'score', 'correct_count', 'avg_response_ms')
    )
    for rank, entry in enumerate(entries, start=1):
        entry['rank'] = rank
        if entry['avg_response_ms'] is None:
            entry['avg_response_ms'] = 0
        else:
            entry['avg_response_ms'] = round(entry['avg_response_ms'])
    return JsonResponse({'leaderboard': entries, 'status': session.status})
