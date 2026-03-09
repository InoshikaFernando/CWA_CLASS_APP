import uuid
import json
import time
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from django.conf import settings

from maths.models import Level, Topic, calculate_points
from .basic_facts import (
    SUBTOPIC_CONFIG, SUBTOPIC_LABELS, get_display_level,
    generate_questions, check_answer
)


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
                total_questions=total,
                points=points,
                time_taken_seconds=time_taken,
                questions_data=results,
            )

        # Clean session
        del request.session[session_key]

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
    4: list(range(1, 13)),
    5: list(range(1, 13)),
    6: list(range(1, 13)),
    7: list(range(1, 13)),
    8: list(range(1, 13)),
}


def _generate_times_tables_questions(table, operation, count=12):
    import random
    questions = []
    for i in range(1, count + 1):
        multiplier = i
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
            'id': i,
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
            from classroom.models import ClassRoom, Level as ClassroomLevel
            classrooms = ClassRoom.objects.filter(students=request.user, is_active=True)
            hub_levels = ClassroomLevel.objects.filter(classrooms__in=classrooms, level_number__lte=8)
            if hub_levels.exists():
                year = hub_levels.order_by('-level_number').first().level_number

        available_tables = TIMES_TABLES_BY_YEAR.get(year, list(range(1, 13)))

        return render(request, 'quiz/times_tables_select.html', {
            'available_tables': available_tables,
            'all_tables': range(1, 13),
            'year': year,
        })


class TimesTablesSelectView(LoginRequiredMixin, View):
    def get(self, request, level_number, operation):
        level = get_object_or_404(Level, level_number=level_number)
        year = level_number
        available = TIMES_TABLES_BY_YEAR.get(year, list(range(1, 13)))
        return render(request, 'quiz/times_tables_select.html', {
            'level': level, 'operation': operation,
            'available_tables': available,
        })


class TimesTablesQuizView(LoginRequiredMixin, View):
    def get(self, request, level_number, table, operation):
        questions = _generate_times_tables_questions(table, operation)
        session_id = str(uuid.uuid4())
        request.session[f'tt_{session_id}'] = {
            'table': table, 'operation': operation,
            'level_number': level_number,
            'questions': questions,
            'start_time': time.time(),
            'current': 0,
        }
        first_q = questions[0]
        return render(request, 'quiz/times_tables_quiz.html', {
            'table': table, 'operation': operation,
            'level_number': level_number,
            'session_id': session_id,
            'question': first_q,
            'question_number': 1,
            'total_questions': len(questions),
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
        request.session[session_key] = session_data
        is_last = (current + 1) >= len(questions)

        next_url = None
        if is_last:
            next_url = f'/times-tables/submit/{session_id}/'

        return render(request, 'quiz/partials/tt_feedback.html', {
            'is_correct': is_correct,
            'correct_answer': q['answer'],
            'is_last_question': is_last,
            'next_url': next_url,
            'next_question_url': f'/api/tt-next/{session_id}/' if not is_last else None,
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
            return redirect(f'/times-tables/submit/{session_id}/')

        q = questions[current]
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
        table = session_data.get('table', 0)
        operation = session_data.get('operation', 'multiplication')
        level_number = session_data.get('level_number', 1)
        questions = session_data.get('questions', [])
        start_time = session_data.get('start_time', _time.time())

        score = sum(1 for q in questions if q.get('is_correct', False))
        total = len(questions) or 1
        time_taken = max(1, int(_time.time() - start_time))
        points = calculate_points(score, total, time_taken)

        # Save to DB using table number as level_number
        from maths.models import StudentFinalAnswer
        level_obj = Level.objects.filter(level_number=table).first()
        if level_obj:
            StudentFinalAnswer.objects.create(
                student=request.user,
                topic=None,
                level=level_obj,
                quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
                operation=operation,
                score=score,
                total_questions=total,
                points=points,
                time_taken_seconds=time_taken,
            )

        request.session[f'tt_done_{session_id}'] = session_data
        del request.session[session_key]
        return redirect('times_tables_results_view', session_id=session_id)


class TimesTablesResultsView(LoginRequiredMixin, View):
    def get(self, request, session_id):
        session_data = request.session.get(f'tt_done_{session_id}', {})
        table = session_data.get('table', '?')
        operation = session_data.get('operation', 'multiplication')
        questions = session_data.get('questions', [])
        return render(request, 'quiz/times_tables_results.html', {
            'table': table, 'operation': operation,
            'questions': questions,
            'session_id': session_id,
        })


# ── Topic Quiz (HTMX) ───────────────────────────────────────────────────────

class TopicQuizView(LoginRequiredMixin, View):
    def get(self, request, level_number, topic_id):
        import random as rnd
        level = get_object_or_404(Level, level_number=level_number)
        topic = get_object_or_404(Topic, id=topic_id)

        from maths.models import Question
        questions_qs = list(Question.objects.filter(
            topic=topic, level=level
        ).prefetch_related('answers'))

        if not questions_qs:
            from django.contrib import messages
            messages.warning(request, f'No questions available for {topic.name} — Year {level_number} yet.')
            return redirect('home')

        rnd.shuffle(questions_qs)
        limit = 8 + level_number * 2  # Y1→10, Y2→12, Y3→14, Y4→16, Y5→18, Y6→20, Y7→22, Y8→24
        questions = questions_qs[:limit]

        # Serialise questions for session (just ids + shuffled answer ids)
        session_id = str(uuid.uuid4())
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
        })


class TopicResultsView(LoginRequiredMixin, View):
    def get(self, request, level_number, topic_id):
        level = get_object_or_404(Level, level_number=level_number)
        topic = get_object_or_404(Topic, id=topic_id)

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
        })


# ── Mixed Quiz ───────────────────────────────────────────────────────────────

class MixedQuizView(LoginRequiredMixin, View):
    def get(self, request, level_number):
        import random as rnd
        level = get_object_or_404(Level, level_number=level_number)
        from maths.models import Question

        # Stratified sample across all topics for this level (maths.Topic has no is_active)
        topics = Topic.objects.filter(levels=level)
        all_questions = []
        for topic in topics:
            qs = list(Question.objects.filter(topic=topic, level=level).prefetch_related('answers'))
            rnd.shuffle(qs)
            all_questions.extend(qs[:5])  # max 5 per topic

        rnd.shuffle(all_questions)

        if not all_questions:
            from django.contrib import messages
            messages.warning(request, f'No questions available for Year {level_number} yet.')
            return redirect('home')

        session_id = str(uuid.uuid4())
        request.session[f'mq_{session_id}'] = {
            'level_number': level_number,
            'question_ids': [q.id for q in all_questions],
            'start_time': time.time(),
        }

        return render(request, 'quiz/mixed_quiz.html', {
            'level': level, 'questions': all_questions,
            'session_id': session_id,
            'total': len(all_questions),
        })

    def post(self, request, level_number):
        import random as rnd
        level = get_object_or_404(Level, level_number=level_number)
        session_id = request.POST.get('session_id', '')
        session_data = request.session.get(f'mq_{session_id}', {})
        start_time = session_data.get('start_time', time.time())
        time_taken = max(1, int(time.time() - start_time))

        from maths.models import Question, Answer
        from maths.models import StudentAnswer, StudentFinalAnswer
        question_ids = session_data.get('question_ids', [])
        questions = Question.objects.filter(id__in=question_ids).prefetch_related('answers', 'topic')

        correct_count = 0
        topic_results = {}  # {topic_name: {'correct': 0, 'total': 0}}
        answer_records = []

        for q in questions:
            topic_name = q.topic.name
            if topic_name not in topic_results:
                topic_results[topic_name] = {'correct': 0, 'total': 0}
            topic_results[topic_name]['total'] += 1

            is_correct = False
            if q.question_type in ('multiple_choice', 'true_false'):
                answer_id = request.POST.get(f'answer_{q.id}')
                if answer_id:
                    answer = Answer.objects.filter(id=answer_id, question=q).first()
                    is_correct = bool(answer and answer.is_correct)
            else:
                from quiz.basic_facts import check_answer as _ca
                raw = request.POST.get(f'text_{q.id}', '').strip()
                correct_ans = q.answers.filter(is_correct=True).first()
                if correct_ans:
                    alts = [a.strip() for a in correct_ans.answer_text.split(',')]
                    is_correct = raw.lower() in [a.lower() for a in alts]

            if is_correct:
                correct_count += 1
                topic_results[topic_name]['correct'] += 1

            answer_records.append(StudentAnswer(
                student=request.user,
                question=q,
                topic=q.topic,
                level=level,
                is_correct=is_correct,
            ))

        total = len(question_ids) or 1
        points = calculate_points(correct_count, total, time_taken)

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
            )

        if f'mq_{session_id}' in request.session:
            del request.session[f'mq_{session_id}']

        request.session[f'mq_result_{level_number}'] = {
            'result_id': result.id,
            'topic_results': topic_results,
            'time_taken': time_taken,
        }
        return redirect('mixed_results', level_number=level_number)


class MixedResultsView(LoginRequiredMixin, View):
    def get(self, request, level_number):
        level = get_object_or_404(Level, level_number=level_number)
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

        from maths.models import Question, Answer
        question_id = data.get('question_id')
        q = get_object_or_404(Question, id=question_id)
        current = session_data['current']
        questions = session_data['questions']

        # Grade
        is_correct = False
        correct_answer_text = ''
        correct_answer_id = None

        if q.question_type in ('multiple_choice', 'true_false'):
            answer_id = data.get('answer_id')
            answer = Answer.objects.filter(id=answer_id, question=q).first()
            is_correct = bool(answer and answer.is_correct)
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
        else:
            raw = data.get('text_answer', '').strip()
            correct_ans = q.answers.filter(is_correct=True).first()
            if correct_ans:
                alts = [a.strip().lower() for a in correct_ans.answer_text.split(',')]
                from django.conf import settings
                tolerance = getattr(settings, 'ANSWER_NUMERIC_TOLERANCE', 0.05)
                is_correct = raw.lower() in alts
                if not is_correct:
                    try:
                        is_correct = abs(float(raw) - float(alts[0])) <= tolerance
                    except ValueError:
                        pass
                correct_answer_text = correct_ans.answer_text.split(',')[0]

        # Update session
        if is_correct:
            session_data['correct'] += 1
        session_data['current'] = current + 1
        request.session[session_key] = session_data

        # Save individual answer
        from maths.models import StudentAnswer
        import uuid as _uuid
        StudentAnswer.objects.create(
            student=request.user,
            question=q,
            topic=q.topic,
            level=q.level,
            is_correct=is_correct,
            attempt_id=_uuid.UUID(session_id) if len(session_id) == 36 else _uuid.uuid4(),
        )

        is_last = session_data['current'] >= len(questions)
        next_url = None

        if is_last:
            # Save final result
            start_time = session_data.get('start_time', time.time())
            time_taken = max(1, int(time.time() - start_time))
            total = len(questions)
            correct = session_data['correct']
            points = calculate_points(correct, total, time_taken)

            from maths.models import StudentFinalAnswer
            from maths.models import Level as _Level
            level = _Level.objects.filter(level_number=session_data['level_number']).first()
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
            )
            request.session[f'tq_result_{q.topic.id}_{session_data["level_number"]}'] = result.id
            del request.session[session_key]
            next_url = f'/level/{session_data["level_number"]}/topic/{q.topic.id}/results/'

            # Update topic-level statistics (mean/sigma)
            from maths.models import TopicLevelStatistics
            TopicLevelStatistics.recalculate(q.topic, level)

        return JsonResponse({
            'is_correct': is_correct,
            'correct_answer_id': correct_answer_id,
            'correct_answer_text': correct_answer_text,
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
            return redirect(f'/level/{session_data["level_number"]}/topic/{session_data["topic_id"]}/results/')

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


# ── Helpers ──────────────────────────────────────────────────────────────────

def _fmt_time(seconds):
    if not seconds:
        return '0s'
    if seconds < 60:
        return f'{seconds}s'
    m, s = divmod(seconds, 60)
    return f'{m}m {s}s'
