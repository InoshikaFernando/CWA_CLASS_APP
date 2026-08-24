import json
import logging
import time
import uuid
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.conf import settings
from django.db.models import Q

from audit.services import log_event
from classroom.models import Level as ClassroomLevel, SchoolStudent, Topic as ClassroomTopic
from maths.models import calculate_points
from .basic_facts import (
    SUBTOPIC_CONFIG, SUBTOPIC_LABELS, get_display_level,
    generate_questions, check_answer
)

logger = logging.getLogger(__name__)


def _get_student_school(user):
    """Return the school for a student (via SchoolStudent), or None."""
    membership = SchoolStudent.objects.filter(
        student=user, is_active=True,
    ).select_related('school').first()
    return membership.school if membership else None


def _cleanup_stale_quiz_keys(session, prefix):
    """
    Remove orphaned quiz session keys matching *prefix* (e.g. ``tt_``,
    ``bf_``, ``tq_``, ``mq_``).  Only keys whose suffix is a valid UUID
    are removed — this preserves result keys like ``tt_done_*``,
    ``bf_result_*``, ``tq_result_*``, and ``mq_result_*``.

    Called every time a new quiz starts so that abandoned attempts
    from previous days don't accumulate in the session store.
    """
    stale = []
    plen = len(prefix)
    for k in session.keys():
        if not k.startswith(prefix):
            continue
        suffix = k[plen:]
        # Active quiz keys look like  tt_<uuid>,  bf_<uuid>, …
        # Result / done keys have extra words: tt_done_<uuid>, bf_result_…
        try:
            uuid.UUID(suffix)
            stale.append(k)
        except ValueError:
            pass
    for k in stale:
        del session[k]


def _correct_answer_texts(question):
    """Every ticked answer's text for *question* (non-empty), in stored order.

    Short-answer grading used to look at ``.first()`` only, so a question with
    more than one accepted answer silently rejected all but one of them
    (CPP-374). Mirrors the list ``Question.grade_text_answer`` builds.
    """
    return [
        a.answer_text for a in question.answers.filter(is_correct=True)
        if a.answer_text
    ]


def gradable_for(user, questions_qs):
    """Filter *questions_qs* down to the questions this quiz can actually mark.

    A quiz gives its verdict the instant the student presses Submit, so it may
    only serve questions it can grade on the spot. Two kinds it cannot:

    - ``question_type='extended_answer'`` — written prose, no stored answer;
    - ``validation_type`` of ``ai_graded`` / ``human_graded`` — the author said
      explicitly that a person or a model must judge this one.

    A quiz gives its verdict the instant the student presses Submit, so it may
    only serve questions it can mark then and there. What that leaves out
    depends on the student:

    - ``validation_type='human_graded'`` is hidden from everyone. A teacher has
      to mark it, and no quiz can wait for that.
    - AI-graded questions (``extended_answer``, or ``validation_type=
      'ai_graded'``) are shown to students the quiz can AI-grade: every
      individual student, and school students whose school buys the AI grading
      module. For anyone else they are hidden, because the alternative is
      showing a child a question that will be marked wrong however well they
      answer it.

    Before this, all of them were served to everyone and then graded by exact
    match against a stored answer that, by definition, isn't there. 483
    questions site-wide are in that state, and they are not broken content:
    they carry the diagram and the marking rubric AI grading needs.
    """
    from maths.models import Question
    from worksheets.grading_service import student_can_be_ai_graded

    # Nobody can be marked on these inside a quiz.
    hidden = Q(validation_type=Question.VALIDATION_HUMAN)

    if not student_can_be_ai_graded(user):
        hidden |= (Q(question_type=Question.EXTENDED_ANSWER)
                   | Q(validation_type=Question.VALIDATION_AI))

    return questions_qs.exclude(hidden)


def _log_hidden(user, level_number, topic, shown, total):
    """Say plainly when a quiz was shortened, and by how much.

    A quiz that quietly shrinks from 25 questions to 6 looks like thin content
    rather than what it is — questions waiting on a grader.
    """
    hidden = total - shown
    if not hidden:
        return
    logger.warning(
        'Quiz for %s (year %s%s): %s of %s questions hidden because the quiz '
        'cannot mark them for this student (teacher-graded, or AI-graded '
        'without the module). %s left.',
        getattr(user, 'username', user), level_number,
        f', topic {topic}' if topic else '', hidden, total, shown,
    )


def ai_grade(question, raw, user):
    """AI-grade a written answer. Returns ``(is_correct, feedback, graded)``.

    ``graded`` is False when the grader could not reach a verdict — the API
    failed, or the school's monthly quota ran out mid-quiz. Both come back from
    ``grade_extended_answer`` as ``is_correct: False``, and taking that at face
    value would mark a child wrong for a billing state or an outage. So the
    answer is recorded as ungraded instead and dropped from the score's
    denominator: not right, not wrong, not counted.
    """
    from worksheets.grading_service import grade_extended_answer

    school = _get_student_school(user)
    if not raw:
        return False, 'Write your answer in the box so it can be marked.', True

    result = grade_extended_answer(question, raw, school=school)

    if result.get('quota_exceeded') or result.get('error'):
        logger.warning(
            'AI grading unavailable for Q%s (student %s, school %s): %s — '
            'the answer was left ungraded rather than scored wrong.',
            question.id, getattr(user, 'username', user),
            getattr(school, 'name', None),
            result.get('error') or 'monthly quota reached',
        )
        return False, (
            'This one could not be marked automatically just now, so it has '
            'not been counted. Your teacher will look at it.'), False

    feedback = result.get('feedback') or ''
    extra = result.get('what_to_add')
    if extra and not result.get('is_correct'):
        feedback = f'{feedback} {extra}'.strip()
    return bool(result.get('is_correct')), feedback, True


# ── Basic Facts ─────────────────────────────────────────────────────────────

class BasicFactsHomeView(LoginRequiredMixin, View):
    def get(self, request):
        subtopics = [
            {'key': 'Addition',       'label': 'Addition',       'icon': '➕', 'levels': 7, 'colour': 'blue'},
            {'key': 'Subtraction',    'label': 'Subtraction',    'icon': '➖', 'levels': 7, 'colour': 'purple'},
            {'key': 'Multiplication', 'label': 'Multiplication', 'icon': '✖️', 'levels': 7, 'colour': 'green'},
            {'key': 'Division',       'label': 'Division',       'icon': '➗', 'levels': 7, 'colour': 'orange'},
            {'key': 'PlaceValue',     'label': 'Place Value',    'icon': '🔢', 'levels': 5, 'colour': 'yellow'},
        ]
        return render(request, 'quiz/basic_facts_select.html', {'subtopics': subtopics})


class BasicFactsSelectView(LoginRequiredMixin, View):
    def get(self, request, subtopic):
        if subtopic not in SUBTOPIC_CONFIG:
            return redirect('basic_facts_home')
        cfg = SUBTOPIC_CONFIG[subtopic]
        label = SUBTOPIC_LABELS[subtopic]
        start, end = cfg['level_range']

        from maths.models import BasicFactsResult
        levels = []
        for i, num in enumerate(range(start, end + 1)):
            best = BasicFactsResult.get_best_result(request.user, subtopic, num)
            levels.append({
                'level_number': num,
                'display_level': i + 1,
                'best_points': round(best.points, 1) if best else None,
                'best_score': f"{best.score}/{best.total_questions}" if best else None,
            })

        return render(request, 'quiz/basic_facts_select.html', {
            'subtopic': subtopic,
            'label': label,
            'levels': levels,
        })


class BasicFactsQuizView(LoginRequiredMixin, View):
    def get(self, request, subtopic, level_number):
        if subtopic not in SUBTOPIC_CONFIG:
            return redirect('basic_facts_home')

        questions = generate_questions(subtopic, level_number, count=10)
        session_id = str(uuid.uuid4())

        # Remove any abandoned basic-facts sessions before creating a new one
        _cleanup_stale_quiz_keys(request.session, 'bf_')

        # Store in session
        request.session[f'bf_{session_id}'] = {
            'subtopic': subtopic,
            'level_number': level_number,
            'questions': questions,
            'start_time': time.time(),
        }

        return render(request, 'quiz/basic_facts_quiz.html', {
            'subtopic': subtopic,
            'label': SUBTOPIC_LABELS[subtopic],
            'display_level': get_display_level(subtopic, level_number),
            'level_number': level_number,
            'questions': questions,
            'session_id': session_id,
        })

    def post(self, request, subtopic, level_number):
        session_id = request.POST.get('session_id', '')
        session_key = f'bf_{session_id}'
        session_data = request.session.get(session_key)

        if not session_data:
            return redirect('basic_facts_select', subtopic=subtopic)

        questions = session_data['questions']
        start_time = session_data['start_time']
        time_taken = max(1, int(time.time() - start_time))

        # Grade
        results = []
        correct_count = 0
        for q in questions:
            raw = request.POST.get(f'answer_{q["id"]}', '').strip()
            is_correct = check_answer(q, raw) if raw else False
            if is_correct:
                correct_count += 1
            results.append({
                **q,
                'student_answer': raw,
                'is_correct': is_correct,
            })

        total = len(questions)
        points = calculate_points(correct_count, total, time_taken)

        from maths.models import BasicFactsResult
        # Dedup: check recent submission
        recent = BasicFactsResult.objects.filter(
            student=request.user, subtopic=subtopic, level_number=level_number
        ).order_by('-completed_at').first()

        dedup_window = getattr(settings, 'QUIZ_DEDUP_WINDOW_SECONDS', 5)
        if recent:
            age = (timezone.now() - recent.completed_at).total_seconds()
            if age < dedup_window:
                result = recent
            else:
                result = BasicFactsResult.objects.create(
                    student=request.user,
                    subtopic=subtopic,
                    level_number=level_number,
                    score=correct_count,
                    total_points=total,
                    points=points,
                    time_taken_seconds=time_taken,
                    questions_data=results,
                )
        else:
            result = BasicFactsResult.objects.create(
                student=request.user,
                subtopic=subtopic,
                level_number=level_number,
                score=correct_count,
                total_points=total,
                points=points,
                time_taken_seconds=time_taken,
                questions_data=results,
            )

        # Keep only the most recent attempts for this subtopic/level.
        BasicFactsResult.prune_old_attempts(result)

        log_event(
            user=request.user,
            school=_get_student_school(request.user),
            category='data_change',
            action='maths_quiz_completed',
            detail={
                'quiz_type': 'basic_facts',
                'subtopic': subtopic,
                'level_number': level_number,
                'score': correct_count,
                'total_questions': total,
                'points': float(points),
                'time_taken_seconds': time_taken,
                'result_id': result.id,
            },
            request=request,
        )

        # Clean session
        request.session.pop(session_key, None)

        # Store result id for results page
        request.session[f'bf_result_{subtopic}_{level_number}'] = result.id

        return redirect('basic_facts_results', subtopic=subtopic, level_number=level_number)


class BasicFactsResultsView(LoginRequiredMixin, View):
    def get(self, request, subtopic, level_number):
        from maths.models import BasicFactsResult

        result_id = request.session.get(f'bf_result_{subtopic}_{level_number}')
        if result_id:
            result = get_object_or_404(BasicFactsResult, id=result_id, student=request.user)
        else:
            result = BasicFactsResult.objects.filter(
                student=request.user, subtopic=subtopic, level_number=level_number
            ).order_by('-completed_at').first()
            if not result:
                return redirect('basic_facts_select', subtopic=subtopic)

        best = BasicFactsResult.get_best_result(request.user, subtopic, level_number)
        is_new_record = best and best.id == result.id and BasicFactsResult.objects.filter(
            student=request.user, subtopic=subtopic, level_number=level_number
        ).count() > 1

        # Previous best (for comparison)
        prev_best = BasicFactsResult.objects.filter(
            student=request.user, subtopic=subtopic, level_number=level_number
        ).exclude(id=result.id).order_by('-points').first()

        return render(request, 'quiz/basic_facts_results.html', {
            'result': result,
            'subtopic': subtopic,
            'label': SUBTOPIC_LABELS[subtopic],
            'display_level': get_display_level(subtopic, level_number),
            'level_number': level_number,
            'is_new_record': is_new_record,
            'prev_best': prev_best,
            'questions_data': result.questions_data,
            'time_display': _fmt_time(result.time_taken_seconds),
            'next_level_number': level_number + 1 if level_number < SUBTOPIC_CONFIG[subtopic]['level_range'][1] else None,
        })


# ── Times Tables ─────────────────────────────────────────────────────────────

TIMES_TABLES_BY_YEAR = {
    1: [1],
    2: [1, 2, 10],
    3: [1, 2, 3, 4, 5, 10],
    4: list(range(1, 16)),
    5: list(range(1, 16)),
    6: list(range(1, 16)),
    7: list(range(1, 16)),
    8: list(range(1, 16)),
    9: list(range(1, 16)),
    10: list(range(1, 16)),
}


def _generate_times_tables_questions(table, operation, count=12, shuffle=False):
    import random
    multipliers = list(range(1, count + 1))
    if shuffle:
        random.shuffle(multipliers)
    questions = []
    for idx, multiplier in enumerate(multipliers, 1):
        if operation == 'multiplication':
            question_text = f'{table} × {multiplier} = ?'
            answer = table * multiplier
        else:
            product = table * multiplier
            question_text = f'{product} ÷ {table} = ?'
            answer = multiplier

        # Generate 3 distractors
        distractors = set()
        while len(distractors) < 3:
            d = answer + random.choice([-table*2, -table, table, table*2, random.randint(1,5)])
            if d != answer and d > 0:
                distractors.add(d)

        choices = [answer] + list(distractors)[:3]
        random.shuffle(choices)

        questions.append({
            'id': idx,
            'question': question_text,
            'answer': answer,
            'choices': choices,
        })
    return questions


class TimesTablesHomeView(LoginRequiredMixin, View):
    def get(self, request):
        # Determine student's year level from their hub classrooms
        year = 4  # default
        if request.user.is_student or request.user.is_individual_student:
            from classroom.models import ClassRoom
            classrooms = ClassRoom.objects.filter(students=request.user, is_active=True)
            hub_levels = ClassroomLevel.objects.filter(classrooms__in=classrooms, level_number__lt=100)
            if hub_levels.exists():
                year = hub_levels.order_by('-level_number').first().level_number

        available_tables = TIMES_TABLES_BY_YEAR.get(year, list(range(1, 16)))

        return render(request, 'quiz/times_tables_select.html', {
            'available_tables': available_tables,
            'all_tables': range(1, 16),
            'year': year,
        })


class TimesTablesSelectView(LoginRequiredMixin, View):
    def get(self, request, level_number, operation):
        level = get_object_or_404(ClassroomLevel, level_number=level_number)
        year = level_number
        available = TIMES_TABLES_BY_YEAR.get(year, list(range(1, 16)))
        return render(request, 'quiz/times_tables_select.html', {
            'level': level, 'operation': operation,
            'available_tables': available,
            'all_tables': range(1, 16),
            'year': year,
        })


class TimesTablesQuizView(LoginRequiredMixin, View):
    def get(self, request, level_number, table, operation):
        shuffled = request.GET.get('shuffle') == '1'
        questions = _generate_times_tables_questions(table, operation, shuffle=shuffled)
        session_id = str(uuid.uuid4())

        # Remove any abandoned times-tables sessions
        _cleanup_stale_quiz_keys(request.session, 'tt_')

        request.session[f'tt_{session_id}'] = {
            'table': table, 'operation': operation,
            'level_number': level_number,
            'questions': questions,
            'start_time': time.time(),
            'question_shown_at': time.time(),
            'thinking_time': 0.0,
            'current': 0,
            'shuffled': shuffled,
        }
        first_q = questions[0]
        return render(request, 'quiz/times_tables_quiz.html', {
            'table': table, 'operation': operation,
            'level_number': level_number,
            'session_id': session_id,
            'question': first_q,
            'question_number': 1,
            'total_questions': len(questions),
            'shuffled': shuffled,
        })


class TimesTablesAnswerView(LoginRequiredMixin, View):
    """HTMX endpoint — receive answer, return feedback partial."""
    def post(self, request):
        session_id = request.POST.get('session_id', '')
        session_key = f'tt_{session_id}'
        session_data = request.session.get(session_key)
        if not session_data:
            return render(request, 'quiz/partials/topic_feedback.html', {
                'error': 'Session expired. Please start again.'
            })

        questions = session_data['questions']
        current = session_data['current']
        q = questions[current]

        try:
            selected = int(request.POST.get('answer', 0))
        except ValueError:
            selected = 0

        is_correct = (selected == q['answer'])
        q['student_answer'] = selected
        q['is_correct'] = is_correct
        questions[current] = q
        session_data['current'] = current + 1

        if 'question_shown_at' in session_data:
            session_data['thinking_time'] = session_data.get('thinking_time', 0.0) + (time.time() - session_data['question_shown_at'])

        request.session[session_key] = session_data
        is_last = (current + 1) >= len(questions)

        next_url = None
        if is_last:
            next_url = reverse('times_tables_submit', kwargs={'session_id': session_id})

        return render(request, 'quiz/partials/tt_feedback.html', {
            'is_correct': is_correct,
            'correct_answer': q['answer'],
            'is_last_question': is_last,
            'next_url': next_url,
            'next_question_url': reverse('api_tt_next', kwargs={'session_id': session_id}) if not is_last else None,
            'session_id': session_id,
        })


class TimesTablesNextView(LoginRequiredMixin, View):
    """HTMX endpoint — return next question partial."""
    def get(self, request, session_id):
        session_key = f'tt_{session_id}'
        session_data = request.session.get(session_key)
        if not session_data:
            return render(request, 'quiz/partials/tt_question.html', {'error': 'Session expired.'})

        questions = session_data['questions']
        current = session_data['current']
        if current >= len(questions):
            return redirect(reverse('times_tables_submit', kwargs={'session_id': session_id}))

        q = questions[current]
        session_data['question_shown_at'] = time.time()
        request.session[session_key] = session_data
        return render(request, 'quiz/partials/tt_question.html', {
            'question': q,
            'question_number': current + 1,
            'total_questions': len(questions),
            'session_id': session_id,
        })


class TimesTablesSubmitView(LoginRequiredMixin, View):
    def get(self, request, session_id):
        import time as _time
        session_key = f'tt_{session_id}'
        session_data = request.session.get(session_key, {})

        # Guard: if session data is missing (e.g. page refresh after submit),
        # redirect to results page instead of processing with empty data.
        if not session_data:
            return redirect('times_tables_results_view', session_id=session_id)

        table = session_data.get('table', 0)
        operation = session_data.get('operation', 'multiplication')
        level_number = session_data.get('level_number', 1)
        questions = session_data.get('questions', [])
        start_time = session_data.get('start_time', _time.time())

        shuffled = session_data.get('shuffled', False)
        score = sum(1 for q in questions if q.get('is_correct', False))
        total = len(questions) or 1
        thinking_time = session_data.get('thinking_time', 0.0)
        if thinking_time > 0:
            time_taken = max(1, int(thinking_time))
        else:
            time_taken = max(1, int(_time.time() - start_time))
        points = calculate_points(score, total, time_taken)

        # Save to DB
        from maths.models import StudentFinalAnswer
        level_obj = ClassroomLevel.objects.filter(level_number=table).first()

        prev_best = StudentFinalAnswer.objects.filter(
            student=request.user,
            quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
            table_number=table,
            operation=operation,
            shuffled=shuffled,
        ).order_by('-points').first()

        sfa = StudentFinalAnswer.objects.create(
            student=request.user,
            topic=None,
            level=level_obj,
            table_number=table,
            quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
            operation=operation,
            score=score,
            total_questions=total,
            points=points,
            time_taken_seconds=time_taken,
            shuffled=shuffled,
            questions_data=questions,
        )

        # Keep only the most recent attempts for this table/operation.
        StudentFinalAnswer.prune_old_attempts(sfa)

        log_event(
            user=request.user,
            school=_get_student_school(request.user),
            category='data_change',
            action='maths_quiz_completed',
            detail={
                'quiz_type': 'times_table',
                'table_number': table,
                'operation': operation,
                'score': score,
                'total_questions': total,
                'points': float(points),
                'time_taken_seconds': time_taken,
                'result_id': sfa.id,
            },
            request=request,
        )

        is_new_record = prev_best is None or points > (prev_best.points or 0)

        session_data['score'] = score
        session_data['total'] = total
        session_data['time_taken'] = time_taken
        session_data['points'] = points
        session_data['is_new_record'] = is_new_record
        session_data['prev_best_points'] = prev_best.points if prev_best else None
        request.session[f'tt_done_{session_id}'] = session_data
        request.session.pop(session_key, None)

        return redirect('times_tables_results_view', session_id=session_id)


class TimesTablesResultsView(LoginRequiredMixin, View):
    def get(self, request, session_id):
        session_data = request.session.get(f'tt_done_{session_id}', {})
        # Session expired (e.g. user hit /results/ directly or refreshed long
        # after submit) — bounce home rather than render an empty page that
        # would trip {% url %} reversal with placeholder values.
        if not session_data:
            return redirect('times_tables_home')
        table = session_data.get('table', 0)
        operation = session_data.get('operation', 'multiplication')
        questions = session_data.get('questions', [])
        score = session_data.get('score', sum(1 for q in questions if q.get('is_correct')))
        total = session_data.get('total', len(questions) or 1)
        time_taken = session_data.get('time_taken', 0)
        points = session_data.get('points', 0.0)
        percentage = round((score / total) * 100) if total else 0
        return render(request, 'quiz/times_tables_results.html', {
            'table': table,
            'operation': operation,
            'questions': questions,
            'session_id': session_id,
            'score': score,
            'total': total,
            'time_display': _fmt_time(time_taken),
            'points': points,
            'percentage': percentage,
            'is_new_record': session_data.get('is_new_record', False),
            'prev_best_points': session_data.get('prev_best_points'),
            'level_number': session_data.get('level_number', 1),
            'shuffled': session_data.get('shuffled', False),
        })


# ── Topic Quiz (HTMX) ───────────────────────────────────────────────────────

class TopicQuizView(LoginRequiredMixin, View):
    def get(self, request, subject, level_number, topic_id):
        import random as rnd
        level = get_object_or_404(ClassroomLevel, level_number=level_number)
        topic = get_object_or_404(ClassroomTopic, id=topic_id)

        from maths.models import Question
        # Global bank only. A plain .filter() here reads every school's private
        # questions too, so one school's content was being served to every other
        # school's students — and to students in no school at all. The gradable
        # filter then drops what this student's quiz cannot mark; both narrow
        # the same pool, so the hidden-count log counts against the global bank
        # rather than against questions the student was never entitled to.
        in_topic = Question.objects.global_only().filter(topic=topic, level=level)
        questions_qs = list(
            gradable_for(request.user, in_topic).prefetch_related('answers'))
        _log_hidden(request.user, level_number, topic.id,
                    len(questions_qs), in_topic.count())

        if not questions_qs:
            from django.contrib import messages
            messages.warning(request, f'No questions available for {topic.name} — Year {level_number} yet.')
            return redirect('home')

        rnd.shuffle(questions_qs)
        limit = 8 + level_number * 2  # Y1→10, Y2→12, Y3→14, Y4→16, Y5→18, Y6→20, Y7→22, Y8→24
        questions = questions_qs[:limit]

        # Serialise questions for session (just ids + shuffled answer ids)
        session_id = str(uuid.uuid4())

        # Remove any abandoned topic-quiz sessions
        _cleanup_stale_quiz_keys(request.session, 'tq_')

        q_data = []
        for q in questions:
            answers = list(q.answers.all())
            rnd.shuffle(answers)
            q_data.append({
                'id': q.id,
                'answer_ids': [a.id for a in answers],
            })
        request.session[f'tq_{session_id}'] = {
            'topic_id': topic_id,
            'level_number': level_number,
            'subject': subject,
            'questions': q_data,
            'current': 0,
            'correct': 0,
            'start_time': time.time(),
        }

        # Render first question
        first_q = questions[0]
        first_answers = list(first_q.answers.all())
        rnd.shuffle(first_answers)

        return render(request, 'quiz/topic_quiz.html', {
            'topic': topic, 'level': level,
            'session_id': session_id,
            'question': first_q,
            'answers': first_answers,
            'question_number': 1,
            'total_questions': len(questions),
            'subject': subject,
        })


class TopicResultsView(LoginRequiredMixin, View):
    def get(self, request, subject, level_number, topic_id):
        level = get_object_or_404(ClassroomLevel, level_number=level_number)
        topic = get_object_or_404(ClassroomTopic, id=topic_id)

        result_id = request.session.get(f'tq_result_{topic_id}_{level_number}')
        from maths.models import StudentFinalAnswer
        if result_id:
            result = StudentFinalAnswer.objects.filter(id=result_id, student=request.user).first()
        else:
            result = StudentFinalAnswer.objects.filter(
                student=request.user, topic=topic, level=level
            ).order_by('-completed_at').first()

        return render(request, 'quiz/topic_results.html', {
            'topic': topic, 'level': level, 'result': result,
            'time_display': _fmt_time(result.time_taken_seconds) if result else '—',
            'subject': subject,
        })


# ── Mixed Quiz ───────────────────────────────────────────────────────────────

class MixedQuizView(LoginRequiredMixin, View):
    def get(self, request, subject, level_number):
        import random as rnd
        level = get_object_or_404(ClassroomLevel, level_number=level_number)
        from maths.models import Question

        # Stratified sample across all topics for this level
        topics = level.topics.all()
        all_questions = []
        # Counted over the whole pool, not the 5-per-topic sample, so the log
        # below reports what the level holds rather than what this draw took.
        pool_total = pool_gradable = 0
        for topic in topics:
            # Global bank only (see TopicQuizView), then drop the ungradable.
            in_topic = Question.objects.global_only().filter(topic=topic, level=level)
            gradable = gradable_for(request.user, in_topic)
            pool_total += in_topic.count()
            pool_gradable += gradable.count()
            qs = list(gradable.prefetch_related('answers'))
            rnd.shuffle(qs)
            all_questions.extend(qs[:5])  # max 5 per topic

        rnd.shuffle(all_questions)
        _log_hidden(request.user, level_number, None, pool_gradable, pool_total)

        if not all_questions:
            from django.contrib import messages
            messages.warning(request, f'No questions available for Year {level_number} yet.')
            return redirect('home')

        session_id = str(uuid.uuid4())

        # Remove any abandoned mixed-quiz sessions
        _cleanup_stale_quiz_keys(request.session, 'mq_')

        request.session[f'mq_{session_id}'] = {
            'level_number': level_number,
            'question_ids': [q.id for q in all_questions],
            'start_time': time.time(),
        }

        return render(request, 'quiz/mixed_quiz.html', {
            'level': level, 'questions': all_questions,
            'session_id': session_id,
            'total': len(all_questions),
            'subject': subject,
        })

    def post(self, request, subject, level_number):
        import random as rnd
        level = get_object_or_404(ClassroomLevel, level_number=level_number)
        session_id = request.POST.get('session_id', '')
        session_data = request.session.get(f'mq_{session_id}', {})
        start_time = session_data.get('start_time', time.time())
        time_taken = max(1, int(time.time() - start_time))

        from maths.models import Question, Answer
        from maths.models import StudentAnswer, StudentFinalAnswer
        question_ids = session_data.get('question_ids', [])
        questions = Question.objects.filter(id__in=question_ids).prefetch_related('answers', 'topic')

        correct_count = 0
        # What the paper is worth, as opposed to how many questions were fully
        # right: a part-graded question (a fill-in-the-blank sentence) adds the
        # share of its gaps the student filled correctly. See the note on the
        # topic quiz's session credit.
        credit_total = 0.0
        ungraded = 0        # answers no grader could reach a verdict on
        topic_results = {}  # {topic_name: {'correct': 0, 'total': 0}}
        answer_records = []
        review_data = []  # per-question review payload for later viewing

        for q in questions:
            topic_name = q.topic.name
            if topic_name not in topic_results:
                topic_results[topic_name] = {'correct': 0, 'total': 0}
            topic_results[topic_name]['total'] += 1

            is_correct = False
            student_answer = ''
            # What the student actually chose/typed, kept for the StudentAnswer
            # row below — see the note on the topic-quiz save path (CPP-377).
            selected_answer_obj = None
            typed_answer = ''
            # Set only by the part-graded types (fill_blank, table_of_values).
            partial = None
            if q.question_type in ('multiple_choice', 'true_false'):
                answer_id = request.POST.get(f'answer_{q.id}')
                if answer_id:
                    answer = Answer.objects.filter(id=answer_id, question=q).first()
                    is_correct = bool(answer and answer.is_correct)
                    student_answer = answer.answer_text if answer else ''
                    selected_answer_obj = answer
            elif (q.question_type == Question.EXTENDED_ANSWER
                  or q.validation_type == Question.VALIDATION_AI):
                # Written answer — same AI grader as the topic quiz. One it
                # could not reach a verdict on is dropped from the total rather
                # than counted wrong.
                raw = request.POST.get(f'text_{q.id}', '').strip()
                student_answer = typed_answer = raw
                is_correct, _feedback, graded = ai_grade(q, raw, request.user)
                if not graded:
                    ungraded += 1
            else:
                # Every typed answer grades on the model, which routes by
                # answer_format (text / algebra / equation / set) and by
                # question_type (a fill-in-the-blank sentence posts one value per
                # gap as JSON) internally.
                raw = request.POST.get(f'text_{q.id}', '').strip()
                typed_answer = raw
                # A blanks payload is JSON — unreadable in the review list — so
                # what is SHOWN back is the readable form; what is STORED on the
                # StudentAnswer row stays the raw payload it was graded from.
                student_answer = q.display_text_answer(raw)
                # A sentence of gaps is several answers: marked gap by gap so a
                # nearly-right one keeps most of its marks. None for the
                # single-answer types, which grade as they always have.
                partial = q.grade_text_answer_parts(raw)
                is_correct = (partial.is_correct if partial is not None
                              else q.grade_text_answer(raw))

            if is_correct:
                correct_count += 1
                topic_results[topic_name]['correct'] += 1
            credit_total += (partial.fraction if partial is not None
                             else (1.0 if is_correct else 0.0))

            review_entry = {
                'id': q.id,
                'question': q.question_text,
                'topic': topic_name,
                'student_answer': student_answer,
                # Every correct row, not just the first — a list answer must not
                # be shown to the student as only its first value.
                'correct_answer': q.correct_answer_display(),
                'is_correct': is_correct,
            }
            if partial is not None:
                review_entry.update(partial.as_answer_data())
            review_data.append(review_entry)

            answer_records.append(StudentAnswer(
                student=request.user,
                question=q,
                selected_answer=selected_answer_obj,
                text_answer=typed_answer,
                is_correct=is_correct,
            ))

        # Ungraded answers (AI grading down or out of quota) are not part of
        # the paper — see ai_grade().
        total = max(1, len(question_ids) - ungraded)
        # Scored on credit rather than the count — see credit_total above.
        points = calculate_points(credit_total, total, time_taken)

        from django.db import transaction
        with transaction.atomic():
            StudentAnswer.objects.bulk_create(answer_records, ignore_conflicts=True)
            attempt_num = StudentFinalAnswer.get_next_attempt_number(request.user, None, level)
            result = StudentFinalAnswer.objects.create(
                student=request.user,
                topic=None,
                level=level,
                quiz_type=StudentFinalAnswer.QUIZ_TYPE_MIXED,
                score=correct_count,
                total_questions=total,
                points=points,
                time_taken_seconds=time_taken,
                attempt_number=attempt_num,
                questions_data=review_data,
            )
            StudentFinalAnswer.prune_old_attempts(result)

        log_event(
            user=request.user,
            school=_get_student_school(request.user),
            category='data_change',
            action='maths_quiz_completed',
            detail={
                'quiz_type': 'mixed',
                'level_number': level_number,
                'score': correct_count,
                'total_questions': total,
                'points': float(points),
                'time_taken_seconds': time_taken,
                'result_id': result.id,
            },
            request=request,
        )

        if f'mq_{session_id}' in request.session:
            del request.session[f'mq_{session_id}']

        request.session[f'mq_result_{level_number}'] = {
            'result_id': result.id,
            'topic_results': topic_results,
            'time_taken': time_taken,
        }
        return redirect('mixed_results', subject=subject, level_number=level_number)


class MixedResultsView(LoginRequiredMixin, View):
    def get(self, request, subject, level_number):
        level = get_object_or_404(ClassroomLevel, level_number=level_number)
        data = request.session.get(f'mq_result_{level_number}', {})
        from maths.models import StudentFinalAnswer
        result = None
        if data.get('result_id'):
            result = StudentFinalAnswer.objects.filter(id=data['result_id']).first()
        topic_results = data.get('topic_results', {})
        return render(request, 'quiz/mixed_results.html', {
            'level': level, 'result': result,
            'topic_results': topic_results,
            'time_display': _fmt_time(data.get('time_taken', 0)),
            'subject': subject,
        })


# ── API: Topic quiz answer submission ────────────────────────────────────────

class SubmitTopicAnswerView(LoginRequiredMixin, View):
    def post(self, request):
        from django.http import JsonResponse
        data = json.loads(request.body)
        session_id = data.get('session_id', '')
        session_key = f'tq_{session_id}'
        session_data = request.session.get(session_key)

        if not session_data:
            return JsonResponse({'error': 'Session expired'}, status=400)

        from maths.models import Question, Answer, _split_answer_list
        question_id = data.get('question_id')
        q = get_object_or_404(Question, id=question_id)
        current = session_data['current']
        questions = session_data['questions']

        # Grade
        is_correct = False
        correct_answer_text = ''
        correct_answer_id = None
        # Grader-written explanation, for question types where the mark needs
        # one (see the pattern and AI branches below). Empty for everything else.
        feedback = ''
        # Set when no verdict could be reached (AI grading down or out of
        # quota). Such an answer is dropped from the score rather than counted
        # against the student.
        ungraded = False
        # Set by the part-graded types (a fill-in-the-blank sentence is several
        # answers, not one), so an answer that is nine tenths right can be
        # scored and explained as nine tenths right. None = one answer, marked
        # all or nothing.
        partial = None
        # The option the student actually clicked. Persisted on StudentAnswer
        # below: without it the row records only *that* an answer scored zero,
        # never *what* was chosen, which makes a "this was marked wrong
        # unfairly" report impossible to check against the data (CPP-377).
        selected_answer_obj = None

        if q.question_type in ('multiple_choice', 'true_false'):
            answer_id = data.get('answer_id')
            answer = Answer.objects.filter(id=answer_id, question=q).first()
            is_correct = bool(answer and answer.is_correct)
            selected_answer_obj = answer
            correct_ans = q.answers.filter(is_correct=True).first()
            if correct_ans:
                correct_answer_text = correct_ans.answer_text
                correct_answer_id = correct_ans.id
        elif q.question_type == 'drag_drop':
            ordered_ids = data.get('ordered_answer_ids', [])
            correct_order = list(q.answers.order_by('order').values_list('id', flat=True))
            is_correct = [int(x) for x in ordered_ids] == correct_order
            correct_answer_text = ' -> '.join(
                q.answers.order_by('order').values_list('answer_text', flat=True)
            )
        elif q.question_type == 'prime_factorization' and q.target_number:
            # Correct iff every entered value is prime AND their product == target_number.
            # Order doesn't matter; submitted as 'x'/'×'/'*'/',' separated digits.
            import re as _re
            raw = data.get('text_answer', '').strip()
            tokens = [t for t in _re.split(r'[x×*,\s]+', raw) if t]
            def _is_prime(n):
                if n < 2:
                    return False
                if n < 4:
                    return True
                if n % 2 == 0:
                    return False
                i = 3
                while i * i <= n:
                    if n % i == 0:
                        return False
                    i += 2
                return True
            try:
                nums = [int(t) for t in tokens]
                product = 1
                for x in nums:
                    product *= x
                is_correct = bool(nums) and product == q.target_number and all(_is_prime(x) for x in nums)
            except ValueError:
                is_correct = False
            correct_ans = q.answers.filter(is_correct=True).first()
            correct_answer_text = correct_ans.answer_text if correct_ans else ''
        elif q.question_type == 'measure' and q.numeric_answer is not None:
            # Tolerance-graded numeric answer (measure the angle / read the
            # scale). The correct value lives in numeric_answer, not an Answer
            # row, so this MUST be graded here — the text/Answer-row fallback
            # below would find no correct row and mark every answer wrong.
            # Mirrors maths.plugin.grade_answer so quiz/homework grade alike.
            from maths.geometry_grading import grade_measure
            raw = data.get('text_answer', '').strip()
            is_correct = grade_measure(q, raw)
            num = q.numeric_answer.normalize()
            correct_answer_text = f'{num:f}{q.answer_unit or ""}'
        elif q.question_type == 'number_line' and q.number_line_spec:
            # Mark a value on / read a value off a number line. Mark mode posts a
            # JSON {"marks":[...]} in text_answer; read mode posts the typed value.
            # Graded by the spec (set comparison / numeric tolerance), never an
            # Answer row — mirrors maths.plugin.grade_answer.
            from maths.geometry_grading import grade_number_line
            raw = data.get('text_answer', '')
            is_correct = grade_number_line(q.number_line_spec, raw)
            correct_answer_text = ', '.join(
                str(v) for v in (q.number_line_data or {}).get('target_values', [])
            )
        elif q.question_type == Question.FILL_BLANK and q.blank_spec:
            # A fill-in-the-blank sentence posts one value per gap as JSON in
            # text_answer, graded gap by gap against blank_spec. It needs its
            # own branch (rather than the typed fallback below) because its
            # answers live in the spec, not in Answer rows: the fallback would
            # log it as a question with no stored answer and try to compare the
            # JSON payload as a number.
            raw = data.get('text_answer', '')
            partial = q.grade_text_answer_parts(raw)
            if partial is None:
                # Spec and payload don't line up — no honest per-gap verdict, so
                # fall back to the all-or-nothing grader.
                is_correct = q.grade_text_answer(raw)
            else:
                is_correct = partial.is_correct
            correct_answer_text = q.correct_answer_display()
        elif q.answer_format in ('algebra', 'equation'):
            # Algebra (expand & simplify) and equation (algebraic-equivalence)
            # answers are both graded on the model, which routes by answer_format.
            raw = data.get('text_answer', '').strip()
            is_correct = q.grade_text_answer(raw)
            correct_answer_text = q.correct_answer_display()
        elif (q.question_type == Question.EXTENDED_ANSWER
              or q.validation_type == Question.VALIDATION_AI):
            # A written answer, judged by Claude against the question's rubric.
            # Only reachable when gradable_for() offered the question, so the
            # student is one the quiz can AI-grade.
            raw = data.get('text_answer', '').strip()
            is_correct, feedback, graded = ai_grade(q, raw, request.user)
            if not graded:
                ungraded = True
            correct_answer_text = ''
        elif q.answer_format == Question.ANSWER_FORMAT_PATTERN:
            # "Create your own number pattern" — no stored answer exists, so the
            # typed numbers are graded against what the question asks for. The
            # grader also explains itself, and that explanation is the only
            # useful feedback such a question can give.
            from maths.pattern_grading import grade_pattern
            raw = data.get('text_answer', '').strip()
            grade = grade_pattern(q.question_text, raw)
            is_correct = grade.is_correct
            feedback = grade.feedback
            # There is no "the" answer, so this is a worked example. The client
            # shows it only when the student got the question wrong.
            correct_answer_text = q.correct_answer_display()
        else:
            raw = data.get('text_answer', '').strip()
            correct_texts = _correct_answer_texts(q)
            if not correct_texts:
                # Nothing to grade against: every student who ever answers this
                # question scores zero, whatever they type. That is a content
                # defect, not a student mistake — so say so in the log rather
                # than letting it fail silently for years. Fix it by adding the
                # answer, or by setting answer_format='pattern' if the question
                # asks the student to invent one.
                logger.warning(
                    'Question %s (%r) has no stored correct answer — the typed '
                    'answer %r was scored wrong because there is nothing to '
                    'match it against.',
                    q.id, q.question_text[:80], raw[:80],
                )
            else:
                is_correct = q.grade_text_answer(raw)
                if not is_correct and q.answer_format != Question.ANSWER_FORMAT_SET:
                    # Numeric answers also grade within a small tolerance.
                    tolerance = getattr(settings, 'ANSWER_NUMERIC_TOLERANCE', 0.05)
                    for text in correct_texts:
                        # Only a single-value answer has a float to compare
                        # against. Taking the first value of "32, 2" accepted a
                        # bare "32" — half the answer — which is the same hole
                        # the comma rule had (CPP-378). Commas are stripped
                        # rather than split on, so "1,000" == 1000 still grades.
                        if len(_split_answer_list(text)) > 1:
                            continue
                        try:
                            if abs(float(raw.replace(',', ''))
                                   - float(text.replace(',', ''))) <= tolerance:
                                is_correct = True
                                break
                        except ValueError:
                            continue
                # Every correct row, in full — showing only the first value told
                # the student the answer was "54" when it is 54 and 63 (CPP-376).
                correct_answer_text = q.correct_answer_display()

        # Capture the student's submitted answer (as text) for later review, and
        # in the typed/ordered forms the StudentAnswer row stores.
        ordered_answer_ids = None
        typed_answer = ''
        if q.question_type in ('multiple_choice', 'true_false'):
            # Reuses the Answer already fetched by the grader above rather than
            # re-querying it.
            student_answer_text = (
                selected_answer_obj.answer_text if selected_answer_obj else ''
            )
        elif q.question_type == 'drag_drop':
            _texts = dict(q.answers.values_list('id', 'answer_text'))
            _raw_ids = data.get('ordered_answer_ids', [])
            student_answer_text = ' -> '.join(
                str(_texts.get(int(i), i)) for i in _raw_ids
            )
            ordered_answer_ids = [int(i) for i in _raw_ids]
        else:
            typed_answer = data.get('text_answer', '').strip()
            # A fill-in-the-blank sentence posts its gaps as a JSON payload,
            # which is unreadable in the review list — so what is SHOWN back is
            # the readable form ("15, live"); what is STORED on the StudentAnswer
            # row stays the raw payload it was graded from. Every other answer
            # passes through unchanged.
            student_answer_text = q.display_text_answer(typed_answer)

        # Update session
        #
        # 'correct' counts questions answered fully correctly — what "7 of 10"
        # on the results page means. 'credit' is what the paper is WORTH: the
        # same 1 for a right answer and 0 for a wrong one, but the share of its
        # gaps for a partly-right fill-in-the-blank sentence. Kept apart so
        # partial credit reaches the points without inflating the count.
        credit = (partial.fraction if partial is not None
                  else (1.0 if is_correct else 0.0))
        if 'credit' not in session_data:
            # A quiz already in flight when this shipped has no 'credit' key —
            # seed it from the count so far (before this answer) so its earlier
            # questions aren't silently dropped from the total.
            session_data['credit'] = float(session_data['correct'])
        if is_correct:
            session_data['correct'] += 1
        if not ungraded:
            session_data['credit'] += credit
        if ungraded:
            session_data['ungraded'] = session_data.get('ungraded', 0) + 1
        session_data['current'] = current + 1
        # Record this question for later review, but guard against a replayed or
        # double-clicked POST re-recording a question already answered — that
        # would duplicate rows in the saved questions_data.
        review = session_data.setdefault('review', [])
        if not any(r.get('id') == q.id for r in review):
            entry = {
                'id': q.id,
                'question': q.question_text,
                'student_answer': student_answer_text,
                'correct_answer': correct_answer_text,
                'is_correct': is_correct,
            }
            if partial is not None:
                # What the attempt was worth, and which gaps cost the marks —
                # so the review page can explain a partly-right answer months
                # later without re-grading it.
                entry.update(partial.as_answer_data())
            review.append(entry)
        request.session[session_key] = session_data

        # Save individual answer
        from maths.models import StudentAnswer
        import uuid as _uuid
        attempt = _uuid.UUID(session_id) if len(session_id) == 36 else _uuid.uuid4()
        StudentAnswer.objects.update_or_create(
            student=request.user,
            question=q,
            attempt_id=attempt,
            defaults={
                'is_correct': is_correct,
                'selected_answer': selected_answer_obj,
                'text_answer': typed_answer,
                'ordered_answer_ids': ordered_answer_ids,
            },
        )

        is_last = session_data['current'] >= len(questions)
        next_url = None

        if is_last:
            # Save final result
            start_time = session_data.get('start_time', time.time())
            time_taken = max(1, int(time.time() - start_time))
            # Questions nobody could mark are not part of the paper: scoring a
            # student 7/8 because the grader was down is a mark they did not
            # lose. max(1, ...) keeps calculate_points from dividing by zero on
            # the (pathological) all-ungraded quiz.
            total = max(1, len(questions) - session_data.get('ungraded', 0))
            correct = session_data['correct']
            # Scored on credit, not the count: a paper with one gap wrong in a
            # ten-gap chart is 9.9/10 of a paper, not 9/10.
            points = calculate_points(
                session_data.get('credit', correct), total, time_taken)

            from maths.models import StudentFinalAnswer
            level = ClassroomLevel.objects.filter(level_number=session_data['level_number']).first()
            attempt_num = StudentFinalAnswer.get_next_attempt_number(request.user, q.topic, level)
            result = StudentFinalAnswer.objects.create(
                student=request.user,
                topic=q.topic,
                level=level,
                quiz_type=StudentFinalAnswer.QUIZ_TYPE_TOPIC,
                score=correct,
                total_questions=total,
                points=points,
                time_taken_seconds=time_taken,
                attempt_number=attempt_num,
                questions_data=session_data.get('review', []),
            )
            StudentFinalAnswer.prune_old_attempts(result)
            log_event(
                user=request.user,
                school=_get_student_school(request.user),
                category='data_change',
                action='maths_quiz_completed',
                detail={
                    'quiz_type': 'topic',
                    'topic_id': q.topic.id,
                    'topic_name': q.topic.name,
                    'level_number': session_data['level_number'],
                    'score': correct,
                    'total_questions': total,
                    'points': float(points),
                    'time_taken_seconds': time_taken,
                    'result_id': result.id,
                },
                request=request,
            )

            request.session[f'tq_result_{q.topic.id}_{session_data["level_number"]}'] = result.id
            request.session.pop(session_key, None)
            next_url = reverse('topic_results', kwargs={
                'subject': session_data['subject'],
                'level_number': session_data['level_number'],
                'topic_id': q.topic.id,
            })

            # Update topic-level statistics (mean/sigma)
            from maths.models import TopicLevelStatistics
            TopicLevelStatistics.recalculate(q.topic, level)

        payload = partial.as_answer_data() if partial is not None else {}
        return JsonResponse({
            'is_correct': is_correct,
            'correct_answer_id': correct_answer_id,
            'correct_answer_text': correct_answer_text,
            'feedback': feedback,
            'ungraded': ungraded,
            # Part-graded answers only: what this answer was worth and which
            # gaps were wrong, so the page can say "9 of the 10 blanks are
            # right" and name the tenth instead of a flat "Incorrect".
            'credit': payload.get('score_fraction'),
            'parts_correct': payload.get('parts_correct'),
            'parts_total': payload.get('parts_total'),
            'parts_noun': payload.get('parts_noun'),
            'parts': payload.get('parts'),
            'what_was_correct': payload.get('what_was_correct'),
            'explanation': q.explanation,
            'is_last_question': is_last,
            'next_url': next_url,
        })


class TopicNextQuestionView(LoginRequiredMixin, View):
    """HTMX: return next question partial."""
    def get(self, request, session_id):
        import random as rnd
        session_key = f'tq_{session_id}'
        session_data = request.session.get(session_key)
        if not session_data:
            return render(request, 'quiz/partials/topic_question.html', {'error': 'Session expired.'})

        current = session_data['current']
        questions = session_data['questions']
        if current >= len(questions):
            return redirect(reverse('topic_results', kwargs={
                'subject': session_data['subject'],
                'level_number': session_data['level_number'],
                'topic_id': session_data['topic_id'],
            }))

        q_info = questions[current]
        from maths.models import Question
        q = get_object_or_404(Question, id=q_info['id'])
        answers = list(q.answers.all())
        rnd.shuffle(answers)

        return render(request, 'quiz/partials/topic_question.html', {
            'question': q,
            'answers': answers,
            'question_number': current + 1,
            'total_questions': len(questions),
            'session_id': session_id,
        })


# ── Attempt history (student / teacher / parent) ─────────────────────────────

def _can_view_student_quiz(user, student):
    """Whether *user* may view *student*'s saved quiz attempts.

    Allowed for the student themselves, a teacher who has the student in one of
    their classes, and a parent with an active link to the student.
    """
    if user.is_superuser or user.pk == student.pk:
        return True
    from classroom.models import ClassStudent, ParentStudent
    from homework.views import _teacher_classrooms
    if ClassStudent.objects.filter(
        classroom__in=_teacher_classrooms(user), student=student, is_active=True,
    ).exists():
        return True
    return ParentStudent.objects.filter(
        parent=user, student=student, is_active=True,
    ).exists()


def _normalize_quiz_review(items):
    """Flatten any of the saved ``questions_data`` shapes into a common form.

    Topic/mixed quizzes already store ``correct_answer``; times-tables store the
    answer under ``answer``; basic-facts under ``display_answer``/``answer``.
    """
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        correct = it.get('correct_answer')
        if correct in (None, ''):
            correct = it.get('display_answer', it.get('answer', ''))
        out.append({
            'question': it.get('question', ''),
            'student_answer': it.get('student_answer', ''),
            'correct_answer': correct,
            'is_correct': bool(it.get('is_correct')),
        })
    return out


def _sfa_label(sfa):
    if sfa.quiz_type == sfa.QUIZ_TYPE_TIMES_TABLE:
        op = (sfa.operation or 'multiplication').title()
        return f'{op} — {sfa.table_number} times table'
    if sfa.quiz_type == sfa.QUIZ_TYPE_MIXED:
        return f'Mixed quiz — {sfa.level}' if sfa.level else 'Mixed quiz'
    if sfa.topic:
        return f'{sfa.topic.name} — {sfa.level}' if sfa.level else sfa.topic.name
    return 'Quiz'


def _collect_quiz_attempts(student):
    """Recent quiz attempts for ``student`` across all quiz types, newest first.

    Returns a list of light dicts the history template can render directly, each
    carrying a ``review`` route (kind + pk) into :class:`QuizAttemptReviewView`.
    """
    from maths.models import StudentFinalAnswer, BasicFactsResult
    from quiz.basic_facts import SUBTOPIC_LABELS

    rows = []
    sfas = (
        StudentFinalAnswer.objects
        .filter(student=student)
        .select_related('topic', 'level')
        .order_by('-completed_at')[:40]
    )
    for s in sfas:
        rows.append({
            'kind': 'sfa',
            'pk': s.id,
            'label': _sfa_label(s),
            'quiz_type': s.get_quiz_type_display(),
            'score': s.score,
            'total': s.total_questions,
            'percentage': s.percentage,
            'points': float(s.points or 0),
            'completed_at': s.completed_at,
            'has_review': bool(s.questions_data),
        })

    bfs = (
        BasicFactsResult.objects
        .filter(student=student)
        .order_by('-completed_at')[:40]
    )
    for b in bfs:
        label = SUBTOPIC_LABELS.get(b.subtopic, b.subtopic or 'Basic Facts')
        rows.append({
            'kind': 'bf',
            'pk': b.id,
            'label': f'{label} — Level {b.level_number}',
            'quiz_type': 'Basic Facts',
            'score': b.score,
            'total': b.total_questions,
            'percentage': b.percentage,
            'points': float(b.points or 0),
            'completed_at': b.completed_at,
            'has_review': bool(b.questions_data),
        })

    rows.sort(key=lambda r: r['completed_at'] or timezone.now(), reverse=True)
    return rows


class QuizAttemptHistoryView(LoginRequiredMixin, View):
    """List a student's recent quiz attempts (kept to the last 10 per series)."""
    template_name = 'quiz/attempt_history.html'

    def get(self, request, student_id=None):
        from django.http import Http404
        from django.contrib.auth import get_user_model
        if student_id is None:
            student = request.user
        else:
            student = get_object_or_404(get_user_model(), pk=student_id)
        if not _can_view_student_quiz(request.user, student):
            raise Http404
        return render(request, self.template_name, {
            'student': student,
            'attempts': _collect_quiz_attempts(student),
            'viewing_other': student.pk != request.user.pk,
        })


class QuizAttemptReviewView(LoginRequiredMixin, View):
    """Show the questions + answers for a single saved quiz attempt."""
    template_name = 'quiz/attempt_review.html'

    def get(self, request, kind, pk):
        from django.http import Http404
        from maths.models import StudentFinalAnswer, BasicFactsResult

        if kind == 'sfa':
            attempt = get_object_or_404(
                StudentFinalAnswer.objects.select_related('topic', 'level', 'student'),
                pk=pk,
            )
            label = _sfa_label(attempt)
            quiz_type = attempt.get_quiz_type_display()
        elif kind == 'bf':
            attempt = get_object_or_404(
                BasicFactsResult.objects.select_related('student'), pk=pk,
            )
            from quiz.basic_facts import SUBTOPIC_LABELS
            label = (
                f'{SUBTOPIC_LABELS.get(attempt.subtopic, attempt.subtopic)} '
                f'— Level {attempt.level_number}'
            )
            quiz_type = 'Basic Facts'
        else:
            raise Http404

        if not _can_view_student_quiz(request.user, attempt.student):
            raise Http404

        return render(request, self.template_name, {
            'student': attempt.student,
            'label': label,
            'quiz_type': quiz_type,
            'score': attempt.score,
            'total': getattr(attempt, 'total_questions', None),
            'percentage': attempt.percentage,
            'points': float(attempt.points or 0),
            'completed_at': attempt.completed_at,
            'time_display': _fmt_time(attempt.time_taken_seconds),
            'review': _normalize_quiz_review(attempt.questions_data),
            'viewing_other': attempt.student_id != request.user.pk,
        })


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_time(seconds):
    if not seconds:
        return '0s'
    if seconds < 60:
        return f'{seconds}s'
    m, s = divmod(seconds, 60)
    return f'{m}m {s}s'
