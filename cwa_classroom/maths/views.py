from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse, Http404, HttpResponseForbidden
import subprocess
import sys
import os
import uuid
from django.conf import settings
from django.views.decorators.http import require_http_methods
import time
from django.db.models import Q, Count, Sum, Max, Min, Avg
import random
from datetime import datetime
import json
import threading
from django.utils.text import slugify
from .models import Question, Answer, StudentAnswer, BasicFactsResult, TimeLog, TopicLevelStatistics, StudentFinalAnswer
from classroom.models import (
    Topic, Level as ClassroomLevel, Subject as ClassroomSubject,
    ClassRoom as ClassroomClassRoom, SchoolStudent,
)  # classroom models
from accounts.models import CustomUser, Role, UserRole
from .forms import StudentSignUpForm, TeacherSignUpForm, TeacherCenterRegistrationForm, IndividualStudentRegistrationForm, StudentBulkRegistrationForm, QuestionForm, AnswerFormSet, UserProfileForm, UserPasswordChangeForm
from .constants import YEAR_TOPICS_MAP, TIMES_TABLES_BY_YEAR

BASIC_FACTS_TOPIC_CONFIG = {
    "addition": {"start_level": 100, "level_count": 7},
    "subtraction": {"start_level": 107, "level_count": 7},
    "multiplication": {"start_level": 114, "level_count": 7},
    "division": {"start_level": 121, "level_count": 7},
    "place-value-facts": {"start_level": 128, "level_count": 5},
}

YEAR_QUESTION_COUNTS = {1: 12, 2: 10, 3: 12, 4: 15, 5: 17, 6: 20, 7: 22, 8: 25, 9: 30}

TOPIC_SESSION_SLUGS = {
    "Measurements": "measurements",
    "Whole Numbers": "whole_numbers",
    "Factors": "factors",
    "Angles": "angles",
    "Place Values": "place_values",
    "Fractions": "fractions",
    "BODMAS/PEMDAS": "bodmas",
    "Date and Time": "date_time",
    "Finance": "finance",
    "Integers": "integers",
    "Trigonometry": "trigonometry",
}

# Add dynamic slugs for all multiplication/division times tables
for _tt in range(1, 13):
    TOPIC_SESSION_SLUGS[f"Multiplication ({_tt}\u00d7)"] = f"mult_{_tt}"
    TOPIC_SESSION_SLUGS[f"Division ({_tt}\u00d7)"] = f"div_{_tt}"


def _get_questions_for_level(user, level):
    """
    Return a Question queryset for *level* scoped to what *user* may see.

    Individual student (no active SchoolStudent membership):
      → global questions only  (school IS NULL)

    School student (active SchoolStudent membership):
      • no local questions exist               → global only
      • local questions exist + global exist   → local ∪ global  (load all)
      • local questions exist + no global      → local only
        (subject not mapped to global questions)

    "Local"  = Question.school == student's school
    "Global" = Question.school IS NULL
    """
    school = None
    membership = SchoolStudent.objects.filter(
        student=user, is_active=True,
    ).select_related('school').first()
    if membership:
        school = membership.school

    base_qs = Question.objects.filter(level=level)

    if school is None:
        return base_qs.filter(school__isnull=True)

    local_qs = base_qs.filter(school=school)
    global_qs = base_qs.filter(school__isnull=True)

    has_local = local_qs.exists()
    has_global = global_qs.exists()

    if has_local and has_global:
        # Load everything the student can see (local ∪ global)
        return base_qs.filter(Q(school=school) | Q(school__isnull=True))
    elif has_local:
        return local_qs
    else:
        return global_qs


def normalize_basic_facts_topic(topic_name):
    return slugify(topic_name or "").lower()


def get_level_number_for_basic_facts(topic_name, display_level):
    slug = normalize_basic_facts_topic(topic_name)
    config = BASIC_FACTS_TOPIC_CONFIG.get(slug)
    if not config:
        return None
    if display_level < 1 or display_level > config["level_count"]:
        return None
    return config["start_level"] + display_level - 1


def get_display_level_for_basic_facts(level_number, topic_name):
    slug = normalize_basic_facts_topic(topic_name)
    config = BASIC_FACTS_TOPIC_CONFIG.get(slug)
    if not config:
        return None
    start = config["start_level"]
    end = start + config["level_count"] - 1
    if start <= level_number <= end:
        return level_number - start + 1
    return None

def calculate_age_from_dob(date_of_birth):
    """
    Calculate age from date of birth (integer years only, ignoring months).
    For example: 6 years and 4 months -> returns 6
    """
    if not date_of_birth:
        return None
    from datetime import date
    today = date.today()
    # Calculate age in years only (integer, no rounding)
    # If birthday hasn't occurred this year, subtract 1
    age = today.year - date_of_birth.year
    if (today.month, today.day) < (date_of_birth.month, date_of_birth.day):
        age -= 1
    return age


def _get_maths_subject():
    """Return the global Mathematics classroom.Subject (create if needed)."""
    subject, _ = ClassroomSubject.objects.get_or_create(
        slug='mathematics',
        school=None,
        defaults={'name': 'Mathematics', 'is_active': True},
    )
    return subject


def get_or_create_classroom_topic(name):
    """Get or create a classroom.Topic by name under the global Mathematics subject."""
    subject = _get_maths_subject()
    base_slug = slugify(name) or f'topic-unnamed'
    topic = Topic.objects.filter(subject=subject, name__iexact=name).first()
    if topic is None:
        # Ensure unique slug
        slug = base_slug
        counter = 1
        while Topic.objects.filter(subject=subject, slug=slug).exists():
            slug = f'{base_slug}-{counter}'
            counter += 1
        topic = Topic.objects.create(
            subject=subject,
            name=name,
            slug=slug,
            is_active=True,
        )
    return topic


def get_or_create_age_level(age):
    """Get or create a classroom.Level for a specific age (for Basic Facts statistics)."""
    # Use level_number = 2000 + age to avoid conflicts with regular (1-99) and Basic Facts (100+) levels
    age_level_number = 2000 + age
    age_level, _ = ClassroomLevel.objects.get_or_create(
        level_number=age_level_number,
        defaults={'display_name': f"Age {age}"},
    )
    return age_level


def get_or_create_formatted_topic(level_number, topic_name):
    """Get or create a classroom.Topic with formatted name for Basic Facts: {level_number}_{topic_name}"""
    formatted_name = f"{level_number}_{topic_name}"
    return get_or_create_classroom_topic(formatted_name)

def select_questions_stratified(all_questions, num_needed):
    """
    Select questions using stratified random sampling.
    Divides questions into blocks and selects one from each block.
    
    Example: If we have 100 questions and need 10:
    - Divide into 10 blocks of 10 questions each
    - Select 1 random question from each block
    - This ensures better coverage across the entire question set
    
    Args:
        all_questions: List of all available questions
        num_needed: Number of questions to select
    
    Returns:
        List of selected questions
    """
    if not all_questions:
        return []
    
    total_questions = len(all_questions)
    
    # If we need all or more questions than available, return all
    if num_needed >= total_questions:
        return list(all_questions)
    
    # Calculate block size: total_questions / num_needed
    # This gives us the number of questions per block
    block_size = total_questions / num_needed
    
    selected_questions = []
    
    # Select one question from each block
    for i in range(num_needed):
        # Calculate the start and end indices for this block
        start_idx = int(i * block_size)
        end_idx = int((i + 1) * block_size)
        
        # Handle the last block to include any remaining questions
        if i == num_needed - 1:
            end_idx = total_questions
        
        # Get the block of questions
        block = all_questions[start_idx:end_idx]
        
        # Select one random question from this block
        if block:
            selected_questions.append(random.choice(block))
    
    return selected_questions



class MockAnswer:
    def __init__(self, text, is_correct=True):
        self.answer_text = text
        self.is_correct = is_correct


def _clear_session_keys(session, *keys):
    for key in keys:
        if key in session:
            del session[key]


def _calculate_previous_best_points(student, level, topic, exclude_session_id):
    previous_sessions_data = StudentAnswer.objects.filter(
        student=student,
        question__level=level,
        question__topic=topic
    ).exclude(session_id=exclude_session_id).exclude(session_id='').values('session_id').annotate(
        total_correct=Sum('is_correct'),
        total_count=Count('id'),
        total_points=Sum('points_earned'),
        time_taken=Max('time_taken_seconds')
    )

    previous_best_points = None
    for session_data in previous_sessions_data:
        sid = session_data['session_id']
        if not sid:
            continue

        session_correct = session_data['total_correct'] or 0
        session_total = session_data['total_count'] or 1
        session_time = session_data['time_taken'] or 0
        session_points_earned = session_data['total_points'] or 0

        if session_time > 0:
            session_percentage = (session_correct / session_total) if session_total else 0
            session_points = (session_percentage * 100 * 60) / session_time if session_time else 0
        else:
            session_points = session_points_earned

        if previous_best_points is None or session_points > previous_best_points:
            previous_best_points = session_points

    return previous_best_points

def update_topic_statistics(level_num=None, topic_name=None):
    """
    Helper function to update topic-level statistics
    This should be called when a student completes an exercise or beats their record
    
    For Basic Facts (level_number >= 100):
    - Level is based on student's age (from date_of_birth)
    - Topic is formatted as {level_number}_{topic_name} (e.g., "100_Addition")
    """
    try:
        import math
        from datetime import date
        
        # Separate Basic Facts and Year levels
        year_answers = StudentAnswer.objects.filter(
            question__topic__isnull=False,
            question__level__level_number__lt=100  # Year levels (2-9)
        ).select_related('question', 'question__level', 'question__topic', 'student')
        
        basic_facts_answers = StudentAnswer.objects.filter(
            question__topic__isnull=False,
            question__level__level_number__gte=100  # Basic Facts (>= 100)
        ).select_related('question', 'question__level', 'question__topic', 'student')
        
        # Process Year levels (existing logic)
        if level_num is None or level_num < 100:
            # Filter by level if specified
            if level_num is not None:
                year_answers = year_answers.filter(question__level__level_number=level_num)
            
            # Filter by topic if specified
            if topic_name is not None:
                year_answers = year_answers.filter(question__topic__name=topic_name)
            
            # Get unique level-topic combinations for Year levels
            unique_combinations = year_answers.values(
                'question__level__level_number',
                'question__topic__name'
            ).distinct()
            
            
            for combo in unique_combinations:
                level_num_val = combo['question__level__level_number']
                topic_name_val = combo['question__topic__name']
                
                try:
                    level_obj = ClassroomLevel.objects.get(level_number=level_num_val)
                    topic_obj = Topic.objects.filter(name=topic_name_val).first()

                    if not topic_obj:
                        continue

                    # Get available questions count
                    available_questions = Question.objects.filter(
                        level=level_obj,
                        topic=topic_obj
                    ).count()
                    
                    standard_limit = YEAR_QUESTION_COUNTS.get(level_num_val, 10)
                    question_limit = min(available_questions, standard_limit) if available_questions > 0 else standard_limit
                    
                    # Get all students who have completed this topic-level
                    student_best_points = {}
                    
                    # Get all unique student-session combinations for this level-topic
                    student_sessions = year_answers.filter(
                        question__level__level_number=level_num_val,
                        question__topic__name=topic_name_val
                    ).values('student', 'session_id').distinct()
                    
                    for student_session in student_sessions:
                        student_id = student_session['student']
                        session_id = student_session['session_id']
                        
                        if not session_id:
                            continue
                        
                        # Get all answers for this student-session combination
                        session_answers = year_answers.filter(
                            student_id=student_id,
                            session_id=session_id,
                            question__level__level_number=level_num_val,
                            question__topic__name=topic_name_val
                        )
                        
                        # Only count full attempts
                        if session_answers.count() < question_limit:
                            continue
                        
                        # Calculate points for this attempt
                        first_answer = session_answers.first()
                        if first_answer and first_answer.time_taken_seconds > 0:
                            total_correct = sum(1 for a in session_answers if a.is_correct)
                            total_questions = session_answers.count()
                            time_seconds = first_answer.time_taken_seconds
                            
                            percentage = (total_correct / total_questions) if total_questions else 0
                            final_points = (percentage * 100 * 60) / time_seconds if time_seconds else 0
                        else:
                            final_points = sum(a.points_earned for a in session_answers)
                        
                        # Track best points for each student
                        if student_id not in student_best_points:
                            student_best_points[student_id] = final_points
                        else:
                            student_best_points[student_id] = max(student_best_points[student_id], final_points)
                    
                    # Calculate statistics
                    if len(student_best_points) >= 2:  # Need at least 2 students
                        points_list = list(student_best_points.values())
                        avg = sum(points_list) / len(points_list)
                        
                        # Calculate standard deviation
                        variance = sum((x - avg) ** 2 for x in points_list) / len(points_list)
                        sigma = math.sqrt(variance)
                        
                        # Update or create statistics record
                        stats, created = TopicLevelStatistics.objects.get_or_create(
                            level=level_obj,
                            topic=topic_obj,
                            defaults={
                                'average_points': round(avg, 2),
                                'sigma': round(sigma, 2),
                                'student_count': len(student_best_points)
                            }
                        )
                        
                        if not created:
                            stats.average_points = round(avg, 2)
                            stats.sigma = round(sigma, 2)
                            stats.student_count = len(student_best_points)
                            stats.save()
                except Exception:
                    pass  # Skip errors for individual combinations
        
        # Process Basic Facts levels (group by age and formatted topic)
        if level_num is None or level_num >= 100:
            # Filter by level if specified
            if level_num is not None:
                basic_facts_answers = basic_facts_answers.filter(question__level__level_number=level_num)
            
            # Filter by topic if specified
            if topic_name is not None:
                basic_facts_answers = basic_facts_answers.filter(question__topic__name=topic_name)
            
            # Group Basic Facts by (age, level_number, topic_name)
            # We need to process each combination of (student_age, question_level, question_topic)
            from collections import defaultdict
            age_level_topic_combinations = defaultdict(lambda: defaultdict(lambda: {'students': set(), 'sessions': []}))
            
            # Get all unique student-session combinations for Basic Facts
            student_sessions = basic_facts_answers.values('student', 'session_id', 'question__level__level_number', 'question__topic__name').distinct()
            
            for student_session in student_sessions:
                student_id = student_session['student']
                session_id = student_session['session_id']
                level_num_val = student_session['question__level__level_number']
                topic_name_val = student_session['question__topic__name']
                
                if not session_id:
                    continue
                
                # Get student to calculate age
                try:
                    student = CustomUser.objects.get(id=student_id)
                    age = calculate_age_from_dob(student.date_of_birth)
                    if not age:
                        continue  # Skip if no date of birth
                except CustomUser.DoesNotExist:
                    continue
                
                # Format topic name: {level_number}_{topic_name}
                formatted_topic_name = f"{level_num_val}_{topic_name_val}"
                
                # Store session info
                age_level_topic_combinations[age][formatted_topic_name]['students'].add(student_id)
                age_level_topic_combinations[age][formatted_topic_name]['sessions'].append({
                    'student_id': student_id,
                    'session_id': session_id,
                    'level_number': level_num_val,
                    'topic_name': topic_name_val
                })
            
            # Process each age-topic combination
            for age, topics_dict in age_level_topic_combinations.items():
                for formatted_topic_name, data in topics_dict.items():
                    # Get level_number and original topic_name from formatted name
                    # Format is: {level_number}_{topic_name}
                    parts = formatted_topic_name.rsplit('_', 1)
                    if len(parts) != 2:
                        continue
                    level_num_val = int(parts[0])
                    original_topic_name = parts[1]
                    
                    # Get or create age level and formatted topic
                    age_level = get_or_create_age_level(age)
                    formatted_topic = get_or_create_formatted_topic(level_num_val, original_topic_name)
                    
                    # Get available questions count (for the original level and topic)
                    original_level = ClassroomLevel.objects.filter(level_number=level_num_val).first()
                    original_topic = Topic.objects.filter(name=original_topic_name).first()
                    
                    if not original_level or not original_topic:
                        continue
                    
                    available_questions = Question.objects.filter(
                        level=original_level,
                        topic=original_topic
                    ).count()
                    
                    # Basic Facts typically have 10 questions per level
                    question_limit = min(available_questions, 10) if available_questions > 0 else 10
                    
                    # Calculate best points for each student
                    student_best_points = {}
                    
                    for session_info in data['sessions']:
                        student_id = session_info['student_id']
                        session_id = session_info['session_id']
                        level_num_val = session_info['level_number']
                        topic_name_val = session_info['topic_name']
                        
                        # Get all answers for this student-session combination
                        session_answers = basic_facts_answers.filter(
                            student_id=student_id,
                            session_id=session_id,
                            question__level__level_number=level_num_val,
                            question__topic__name=topic_name_val
                        )
                        
                        # Only count full attempts
                        if session_answers.count() < question_limit:
                            continue
                        
                        # Calculate points for this attempt
                        first_answer = session_answers.first()
                        if first_answer and first_answer.time_taken_seconds > 0:
                            total_correct = sum(1 for a in session_answers if a.is_correct)
                            total_questions = session_answers.count()
                            time_seconds = first_answer.time_taken_seconds
                            
                            percentage = (total_correct / total_questions) if total_questions else 0
                            final_points = (percentage * 100 * 60) / time_seconds if time_seconds else 0
                        else:
                            final_points = sum(a.points_earned for a in session_answers)
                        
                        # Track best points for each student
                        if student_id not in student_best_points:
                            student_best_points[student_id] = final_points
                        else:
                            student_best_points[student_id] = max(student_best_points[student_id], final_points)
                    
                    # Calculate statistics
                    if len(student_best_points) >= 2:  # Need at least 2 students
                        points_list = list(student_best_points.values())
                        avg = sum(points_list) / len(points_list)
                        
                        # Calculate standard deviation
                        variance = sum((x - avg) ** 2 for x in points_list) / len(points_list)
                        sigma = math.sqrt(variance)
                        
                        # Update or create statistics record
                        stats, created = TopicLevelStatistics.objects.get_or_create(
                            level=age_level,
                            topic=formatted_topic,
                            defaults={
                                'average_points': round(avg, 2),
                                'sigma': round(sigma, 2),
                                'student_count': len(student_best_points)
                            }
                        )
                        
                        if not created:
                            stats.average_points = round(avg, 2)
                            stats.sigma = round(sigma, 2)
                            stats.student_count = len(student_best_points)
                            stats.save()
    except Exception:
        pass  # Silently fail if statistics can't be updated

def signup_student(request):
    if request.method == "POST":
        form = StudentSignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            role, _ = Role.objects.get_or_create(name=Role.STUDENT, defaults={'display_name': 'Student'})
            UserRole.objects.get_or_create(user=user, role=role)
            login(request, user)
            return redirect("maths:dashboard")
    else:
        form = StudentSignUpForm()
    return render(request, "maths/signup.html", {"form": form, "type": "Student"})

def signup_teacher(request):
    if request.method == "POST":
        form = TeacherSignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            role, _ = Role.objects.get_or_create(name=Role.TEACHER, defaults={'display_name': 'Teacher'})
            UserRole.objects.get_or_create(user=user, role=role)
            login(request, user)
            return redirect("maths:dashboard")
    else:
        form = TeacherSignUpForm()
    return render(request, "maths/signup.html", {"form": form, "type": "Teacher"})

@login_required
def dashboard(request):
    if request.user.is_teacher:
        return redirect('home')

    # ── Time log (read heartbeat-accumulated time) ────────────────────────
    try:
        time_log = get_or_create_time_log(request.user)
    except Exception:
        time_log = None

    # ── Whether student is enrolled in any class (for "Browse classes" link) ──
    not_in_any_class = not ClassroomClassRoom.objects.filter(
        students=request.user, is_active=True
    ).exists()

    # ── Best score ────────────────────────────────────────────────────────
    from django.db.models import Max
    best_pts = StudentFinalAnswer.objects.filter(
        student=request.user
    ).aggregate(best=Max('points'))['best']
    best_score = round(float(best_pts), 1) if best_pts else None

    # ── Year data (all year levels 1–99, marked accessible/locked) ────────
    from collections import defaultdict

    # Use classroom.Level as the authoritative level list
    all_year_levels = ClassroomLevel.objects.filter(level_number__lt=100).order_by('level_number')

    # One query: classroom level_id → set of classroom topic_ids that have questions
    topics_with_q_by_level = defaultdict(set)
    for row in Question.objects.values('level_id', 'topic_id').distinct():
        topics_with_q_by_level[row['level_id']].add(row['topic_id'])

    year_data = []
    for level in all_year_levels:
        accessible = True  # all students see all levels
        topics_with_q = topics_with_q_by_level[level.id]  # level.id is classroom.Level.id

        # Build hierarchical strand_data via classroom.Topic (level IS a ClassroomLevel)
        strand_data = []
        cl_topics = (
            Topic.objects
            .filter(levels=level, is_active=True)
            .select_related('parent')
            .order_by('parent__order', 'parent__name', 'order', 'name')
        )
        strand_dict = {}
        for ct in cl_topics:
            if ct.parent_id is None:
                if ct.id not in strand_dict:
                    strand_dict[ct.id] = {'strand': ct, 'subtopics': []}
            else:
                key = ct.parent_id
                if key not in strand_dict:
                    strand_dict[key] = {'strand': ct.parent, 'subtopics': []}
                has_q = ct.id in topics_with_q
                strand_dict[key]['subtopics'].append({
                    'topic': ct,
                    'topic_id': ct.id,
                    'has_questions': has_q,
                })
        strand_data = [g for g in strand_dict.values() if g['subtopics']]

        # Fallback: classroom.Level.topics (flat, no hierarchy)
        if not strand_data:
            flat_subtopics = []
            for ct in level.topics.order_by('name'):
                flat_subtopics.append({
                    'topic': ct,
                    'topic_id': ct.id,
                    'has_questions': ct.id in topics_with_q,
                })
            if flat_subtopics:
                strand_data = [{'strand': None, 'subtopics': flat_subtopics}]

        subtopic_count = sum(len(g['subtopics']) for g in strand_data)
        year_data.append({
            'level': level,
            'accessible': accessible,
            'subtopic_count': subtopic_count,
            'strand_data': strand_data,
        })

    from classroom.views import _format_seconds
    return render(request, 'student/home.html', {
        'year_data': year_data,
        'time_log': time_log,
        'best_score': best_score,
        'not_in_any_class': not_in_any_class,
        'time_daily': _format_seconds(time_log.daily_total_seconds if time_log else 0),
        'time_weekly': _format_seconds(time_log.weekly_total_seconds if time_log else 0),
    })

@login_required
def dashboard_detail(request):
    """Detailed dashboard view showing progress table"""
    if request.user.is_teacher:
        return redirect('home')
    levels = ClassroomLevel.objects.all()

    # Separate Basic Facts levels (>= 100) from Year levels (< 100)
    basic_facts_levels = ClassroomLevel.objects.filter(level_number__gte=100)
    year_levels = levels.filter(level_number__lt=100)
    
    # Group year levels by year and topics
    levels_by_year = {}
    for level in year_levels:
        year = level.level_number
        if year not in levels_by_year:
            levels_by_year[year] = []
        levels_by_year[year].append(level)
    
    # Sort years
    sorted_years = sorted(levels_by_year.keys())
    
    # Group Basic Facts levels by subtopic
    basic_facts_by_subtopic = {}
    for level in basic_facts_levels:
        subtopics = level.topics.filter(name__in=['Addition', 'Subtraction', 'Multiplication', 'Division', 'Place Value Facts'])
        if subtopics.exists():
            subtopic_name = subtopics.first().name
            if subtopic_name not in basic_facts_by_subtopic:
                basic_facts_by_subtopic[subtopic_name] = []
            basic_facts_by_subtopic[subtopic_name].append(level)
    
    for subtopic in basic_facts_by_subtopic:
        basic_facts_by_subtopic[subtopic].sort(key=lambda x: x.level_number)
    
    # Calculate student progress by level (same as dashboard)
    from django.db.models import Count, Min, Max, Avg, Sum
    
    # Get all student answers for all levels
    student_answers = StudentAnswer.objects.filter(
        student=request.user
    ).select_related('question', 'question__level', 'question__topic')
    
    # Group by level, topic, and session_id to count attempts
    # This allows us to show separate entries for Measurements and Place Values
    progress_by_level = []
    
    # PRIMARY: Get all level-topic combinations from StudentFinalAnswer table
    # This is the source of truth for completed quizzes
    final_answer_combinations = StudentFinalAnswer.objects.filter(
        student=request.user
    ).values(
        'level__level_number',
        'topic__name'
    ).distinct()
    
    # Build level_topic_data from StudentFinalAnswer (primary source)
    level_topic_data = {}
    for item in final_answer_combinations:
        level_num = item['level__level_number']
        topic_name = item['topic__name']
        key = (level_num, topic_name)
        if key not in level_topic_data:
            level_topic_data[key] = set()
    
    # FALLBACK: Also get combinations from StudentAnswer (for records not yet in StudentFinalAnswer)
    student_answers_with_topics = student_answers.filter(question__topic__isnull=False)
    unique_level_topic_sessions = student_answers_with_topics.values(
        'question__level__level_number', 
        'question__topic__name',
        'session_id'
    ).distinct()
    
    # Add StudentAnswer combinations (only if not already in level_topic_data)
    for item in unique_level_topic_sessions:
        level_num = item['question__level__level_number']
        topic_name = item['question__topic__name']
        session_id = item['session_id']
        
        if not session_id or not topic_name:
            continue
        
        key = (level_num, topic_name)
        if key not in level_topic_data:
            level_topic_data[key] = set()
        level_topic_data[key].add(session_id)
    
    # Calculate stats for each level + topic combination
    # PRIMARY: Use StudentFinalAnswer table (more efficient and accurate)
    # FALLBACK: Use StudentAnswer records if no StudentFinalAnswer records exist
    
    for (level_num, topic_name), session_ids in level_topic_data.items():
        attempts_data = []
        completed_session_ids = []
        
        # Get level info
        try:
            level_obj = ClassroomLevel.objects.get(level_number=level_num)
            level_name = f"Level {level_num}" if level_num >= 100 else f"Year {level_num}"
        except ClassroomLevel.DoesNotExist:
            level_obj = None
            level_name = f"Level {level_num}"
            topic_name = "Unknown"

        # Get topic object
        topic_obj = Topic.objects.filter(name=topic_name).first() if level_obj else None
        
        # PRIMARY: Try to get results from StudentFinalAnswer table
        if level_obj and topic_obj:
            final_answer_records = StudentFinalAnswer.objects.filter(
                student=request.user,
                level=level_obj,
                topic=topic_obj
            ).order_by('-points_earned')
            
            if final_answer_records.exists():
                # Use StudentFinalAnswer records
                for fa in final_answer_records:
                    # Look up time from StudentAnswer for this session
                    session_time = 0
                    sa_with_time = StudentAnswer.objects.filter(
                        student=request.user,
                        session_id=fa.session_id,
                        time_taken_seconds__gt=0
                    ).values_list('time_taken_seconds', flat=True).first()
                    if sa_with_time:
                        session_time = sa_with_time
                    attempts_data.append({
                        'points': float(fa.points) or float(fa.points_earned),
                        'time_seconds': fa.time_taken_seconds or session_time,
                        'date': fa.completed_at
                    })
                    completed_session_ids.append(fa.session_id)
            else:
                # FALLBACK: Use StudentAnswer records (old method)
                # Get the actual number of questions available for this topic/level
                try:
                    available_questions = Question.objects.filter(
                        level=level_obj,
                        topic=topic_obj
                    ).count()
                except Exception:
                    available_questions = 0
                
                # Use the minimum of: standard limit OR all available questions
                standard_limit = YEAR_QUESTION_COUNTS.get(level_num, 10)
                question_limit = min(available_questions, standard_limit) if available_questions > 0 else standard_limit
                
                # Allow partial results if they're close to the limit (90% or more)
                partial_threshold = int(question_limit * 0.9)  # 90% of required questions
                
                # Remove duplicates from session_ids
                unique_session_ids = list(set(session_ids))
                
                for session_id in unique_session_ids:
                    # Filter by level, topic, and session_id directly
                    session_answers = student_answers_with_topics.filter(
                        session_id=session_id,
                        question__level__level_number=level_num,
                        question__topic__name=topic_name
                    )
                    
                    # Count attempts that meet the full limit OR are close to it (partial threshold)
                    answer_count = session_answers.count()
                    if answer_count < partial_threshold:
                        continue
                    completed_session_ids.append(session_id)
                    
                    # Calculate points using the formula: percentage * 100 * 60 / time_seconds
                    first_answer = session_answers.first()
                    if first_answer and first_answer.time_taken_seconds > 0:
                        total_correct = sum(1 for a in session_answers if a.is_correct)
                        total_questions = session_answers.count()
                        time_seconds = first_answer.time_taken_seconds
                        
                        percentage = (total_correct / total_questions) if total_questions else 0
                        final_points = (percentage * 100 * 60) / time_seconds if time_seconds else 0
                        attempts_data.append({
                            'points': round(final_points, 2),
                            'time_seconds': time_seconds,
                            'date': first_answer.answered_at
                        })
                    else:
                        total_points = sum(a.points_earned for a in session_answers)
                        first_answer_date = first_answer.answered_at if first_answer else None
                        attempts_data.append({
                            'points': total_points,
                            'time_seconds': 0,
                            'date': first_answer_date
                        })
        
        if attempts_data:
            points_list = [a['points'] for a in attempts_data]
            best_score = max(points_list)
            best_attempt = max(attempts_data, key=lambda x: x['points'])
            
            # Try to get best result from StudentFinalAnswer table (more efficient)
            best_result = None
            try:
                if level_obj:
                    if level_num < 100:
                        # Year levels: use level and topic directly
                        topic_obj = Topic.objects.filter(name=topic_name).first()
                        if topic_obj:
                            best_result = StudentFinalAnswer.get_best_result(
                                student=request.user,
                                topic=topic_obj,
                                level=level_obj
                            )
                            if best_result:
                                best_score = float(best_result.points) or float(best_result.points_earned)
                    else:
                        # Basic Facts: use age-based level and formatted topic
                        age = calculate_age_from_dob(request.user.date_of_birth)
                        if age:
                            age_level = get_or_create_age_level(age)
                            formatted_topic = get_or_create_formatted_topic(level_num, topic_name)
                            if age_level and formatted_topic:
                                best_result = StudentFinalAnswer.get_best_result(
                                    student=request.user,
                                    topic=formatted_topic,
                                    level=age_level
                                )
                                if best_result:
                                    best_score = float(best_result.points) or float(best_result.points_earned)
            except Exception:
                pass  # Fallback to calculated best_score if StudentFinalAnswer lookup fails
            
            # Get statistics for this topic-level to determine color
            color_class = 'light-green'  # Default color
            try:
                if level_obj:
                    if level_num < 100:
                        # Year levels: use level and topic directly
                        topic_obj = Topic.objects.filter(name=topic_name).first()
                        if topic_obj:
                            stats = TopicLevelStatistics.objects.filter(
                                level=level_obj,
                                topic=topic_obj
                            ).first()
                            if stats:
                                color_class = stats.get_color_class(best_score)
                    elif level_num >= 100:
                        # Basic Facts: use age-based level and formatted topic
                        # Calculate student's age
                        age = calculate_age_from_dob(request.user.date_of_birth)
                        if age:
                            # Format topic as {level_number}_{topic_name}
                            formatted_topic_name = f"{level_num}_{topic_name}"
                            formatted_topic = Topic.objects.filter(name=formatted_topic_name).first()
                            if formatted_topic:
                                # Get age level (2000 + age)
                                age_level = ClassroomLevel.objects.filter(level_number=2000 + age).first()
                                if age_level:
                                    stats = TopicLevelStatistics.objects.filter(
                                        level=age_level,
                                        topic=formatted_topic
                                    ).first()
                                    if stats:
                                        color_class = stats.get_color_class(best_score)
            except Exception:
                pass  # If statistics don't exist, use default color
            
            progress_by_level.append({
                'level_number': level_num,
                'level_name': level_name,
                'topic_name': topic_name,
                'total_attempts': len(completed_session_ids),
                'best_points': best_score,
                'best_time_seconds': best_attempt['time_seconds'],
                'best_date': best_attempt['date'],
                'min_points': min(points_list),
                'max_points': max(points_list),
                'avg_points': round(sum(points_list) / len(points_list), 1),
                'color_class': color_class
            })
    
    # ── Fallback: SFA records with NULL topic (legacy/imported data) ─────────
    # These are typically imported from the old system before the topic FK was set.
    # Exclude any level+topic combinations we've already added above.
    already_added = {(p['level_number'], p['topic_name']) for p in progress_by_level}
    null_topic_sfas = StudentFinalAnswer.objects.filter(
        student=request.user,
        topic__isnull=True,
        level__isnull=False,   # skip records with no level — nothing useful to display
        points__gt=0,
    ).order_by('-points')
    if null_topic_sfas.exists():
        from collections import defaultdict as _dd
        by_level = _dd(list)
        sfa_by_level_obj = {}
        for sfa in null_topic_sfas:
            lvl_num = sfa.level.level_number if sfa.level_id else None
            by_level[lvl_num].append(float(sfa.points))
            if lvl_num not in sfa_by_level_obj:
                sfa_by_level_obj[lvl_num] = sfa
        for lvl_num, pts in by_level.items():
            topic_label = 'Various'
            if (lvl_num, topic_label) in already_added:
                continue
            if lvl_num is None:
                lvl_name = 'Unknown Level'
            elif lvl_num < 100:
                lvl_name = f'Year {lvl_num}'
            else:
                lvl_name = f'Level {lvl_num}'
            first_sfa = sfa_by_level_obj[lvl_num]
            progress_by_level.append({
                'level_number': lvl_num if lvl_num is not None else 0,
                'level_name': lvl_name,
                'topic_name': topic_label,
                'total_attempts': len(pts),
                'best_points': round(max(pts), 1),
                'best_time_seconds': first_sfa.time_taken_seconds,
                'best_date': first_sfa.completed_at,
                'min_points': round(min(pts), 1),
                'max_points': round(max(pts), 1),
                'avg_points': round(sum(pts) / len(pts), 1),
                'color_class': 'light-green',
            })

    # Sort by level number
    progress_by_level.sort(key=lambda x: x['level_number'])
    
    # Get Basic Facts progress from database
    basic_facts_progress = {}
    for subtopic_name, levels in basic_facts_by_subtopic.items():
        basic_facts_progress[subtopic_name] = []
        for level in levels:
            level_num = level.level_number
            
            # Get all attempts from database for this level
            # NOTE: production data stores level_number (int) not level FK
            db_results = BasicFactsResult.objects.filter(
                student=request.user,
                level_number=level_num
            ).order_by('-points')
            
            if db_results.exists():
                # Get best result (highest points)
                best_result = db_results.first()
                
                display_level = level_num
                if 100 <= level_num <= 106:  # Addition
                    display_level = level_num - 99
                elif 107 <= level_num <= 113:  # Subtraction
                    display_level = level_num - 106
                elif 114 <= level_num <= 120:  # Multiplication
                    display_level = level_num - 113
                elif 121 <= level_num <= 127:  # Division
                    display_level = level_num - 120
                elif 128 <= level_num <= 132:  # Place Value Facts
                    display_level = level_num - 127
                
                # Count total attempts (unique sessions)
                total_attempts = db_results.values('session_id').distinct().count()
                
                # Get color class for Basic Facts based on age and formatted topic
                color_class = 'light-green'  # Default color
                try:
                    # Calculate student's age
                    age = calculate_age_from_dob(request.user.date_of_birth)
                    if age:
                        # Get the topic name from the level's topics (Addition, Subtraction, etc.)
                        subtopics = level.topics.filter(name__in=['Addition', 'Subtraction', 'Multiplication', 'Division', 'Place Value Facts'])
                        if subtopics.exists():
                            topic_name = subtopics.first().name
                            # Format topic as {level_number}_{topic_name}
                            formatted_topic_name = f"{level_num}_{topic_name}"
                            formatted_topic = Topic.objects.filter(name=formatted_topic_name).first()
                            if formatted_topic:
                                # Get age level (2000 + age)
                                age_level = ClassroomLevel.objects.filter(level_number=2000 + age).first()
                                if age_level:
                                    stats = TopicLevelStatistics.objects.filter(
                                        level=age_level,
                                        topic=formatted_topic
                                    ).first()
                                    if stats:
                                        color_class = stats.get_color_class(float(best_result.points))
                except Exception:
                    pass  # If statistics don't exist, use default color
                
                basic_facts_progress[subtopic_name].append({
                    'display_level': display_level,
                    'level_number': level_num,
                    'best_points': float(best_result.points),
                    'best_time_seconds': best_result.time_taken_seconds,
                    'best_date': best_result.completed_at,
                    'total_attempts': total_attempts,
                    'color_class': color_class  # Add color class for Basic Facts
                })
            else:
                # Check session for old data (for migration/backward compatibility)
                results_key = f"basic_facts_results_{request.user.id}_{level_num}"
                results_list = request.session.get(results_key, [])
                
                if results_list:
                    # Migrate session data to database (one-time migration)
                    try:
                        for result_entry in results_list:
                            # Fix old format points if needed
                            points = result_entry.get('points', 0)
                            if points > 100:
                                points = points / 10
                            
                            # Check if this session_id already exists in DB
                            session_id = result_entry.get('session_id', '')
                            if session_id and not BasicFactsResult.objects.filter(
                                student=request.user,
                                level=level,
                                session_id=session_id
                            ).exists():
                                # Migrate to database
                                date_str = result_entry.get('date', '')
                                if isinstance(date_str, str):
                                    try:
                                        completed_date = datetime.fromisoformat(date_str)
                                    except:
                                        from django.utils import timezone
                                        completed_date = timezone.now()
                                else:
                                    from django.utils import timezone
                                    completed_date = date_str if date_str else timezone.now()
                                
                                BasicFactsResult.objects.create(
                                    student=request.user,
                                    level=level,
                                    session_id=session_id,
                                    score=result_entry.get('score', 0),
                                    total_points=result_entry.get('total_points', 10),
                                    time_taken_seconds=result_entry.get('time_taken_seconds', 0),
                                    points=points,
                                    completed_at=completed_date
                                )
                        
                        # After migration, get from database again
                        db_results = BasicFactsResult.objects.filter(
                            student=request.user,
                            level_number=level_num
                        ).order_by('-points')
                        
                        if db_results.exists():
                            best_result = db_results.first()
                            display_level = level_num
                            if 100 <= level_num <= 106:
                                display_level = level_num - 99
                            elif 107 <= level_num <= 113:
                                display_level = level_num - 106
                            elif 114 <= level_num <= 120:
                                display_level = level_num - 113
                            elif 121 <= level_num <= 127:
                                display_level = level_num - 120
                            elif 128 <= level_num <= 132:
                                display_level = level_num - 127
                            
                            total_attempts = db_results.values('session_id').distinct().count()
                            
                            basic_facts_progress[subtopic_name].append({
                                'display_level': display_level,
                                'level_number': level_num,
                                'best_points': float(best_result.points),
                                'best_time_seconds': best_result.time_taken_seconds,
                                'best_date': best_result.completed_at,
                                'total_attempts': total_attempts
                            })
                    except Exception as e:
                        # If migration fails, fall back to session display
                        pass
        
        # Sort by display_level
        basic_facts_progress[subtopic_name].sort(key=lambda x: x['display_level'])
    
    return render(request, "maths/student_dashboard.html", {
        "levels_by_year": levels_by_year,
        "sorted_years": sorted_years,
        "basic_facts_by_subtopic": basic_facts_by_subtopic,
        "basic_facts_progress": basic_facts_progress,
        "has_class": ClassroomClassRoom.objects.filter(students=request.user, is_active=True).exists(),
        "progress_by_level": progress_by_level,
        "show_progress_table": True,
        "show_all_content": False,
        "year_topics_map": YEAR_TOPICS_MAP
    })

@login_required
def measurements_progress(request, level_number):
    """Show detailed measurements progress with attempt history and graph"""
    level = get_object_or_404(ClassroomLevel, level_number=level_number)
    
    # Get all student answers for Measurements topic for this level
    student_answers = StudentAnswer.objects.filter(
        student=request.user,
        question__level=level,
        question__level__topics__name="Measurements"
    ).select_related('question', 'question__level').order_by('answered_at')
    
    question_limit = YEAR_QUESTION_COUNTS.get(level_number, 10)
    
    # Get unique session IDs for this level
    unique_sessions = student_answers.values_list('session_id', flat=True).distinct()
    unique_sessions = [s for s in unique_sessions if s]  # Filter out empty strings
    
    # Build attempt history
    attempt_history = []
    for session_id in unique_sessions:
        session_answers = student_answers.filter(session_id=session_id)
        
        # Only count completed attempts
        if session_answers.count() != question_limit:
            continue
        
        # Calculate points for this attempt
        first_answer = session_answers.first()
        if first_answer and first_answer.time_taken_seconds > 0:
            total_correct = sum(1 for a in session_answers if a.is_correct)
            total_questions = session_answers.count()
            time_seconds = first_answer.time_taken_seconds
            
            percentage = (total_correct / total_questions) if total_questions else 0
            final_points = (percentage * 100 * 60) / time_seconds if time_seconds else 0
            points = round(final_points, 2)
        else:
            points = sum(a.points_earned for a in session_answers)
        
        # Get attempt date
        attempt_date = session_answers.first().answered_at if session_answers.exists() else None
        
        attempt_history.append({
            'session_id': session_id,
            'attempt_number': len(attempt_history) + 1,
            'points': points,
            'date': attempt_date
        })
    
    # Sort by date
    attempt_history.sort(key=lambda x: x['date'] if x['date'] else datetime.min)
    
    # Re-number attempts after sorting
    for i, attempt in enumerate(attempt_history):
        attempt['attempt_number'] = i + 1
    
    # Calculate stats
    if attempt_history:
        points_list = [a['points'] for a in attempt_history]
        stats = {
            'total_attempts': len(attempt_history),
            'min_points': min(points_list),
            'max_points': max(points_list),
            'avg_points': round(sum(points_list) / len(points_list), 2)
        }
        
        # Prepare data for graph (attempt numbers and points)
        graph_data = {
            'attempt_numbers': [a['attempt_number'] for a in attempt_history],
            'points': points_list,
            'dates': [a['date'].strftime('%Y-%m-%d') if a['date'] else '' for a in attempt_history]
        }
    else:
        stats = {
            'total_attempts': 0,
            'min_points': 0,
            'max_points': 0,
            'avg_points': 0
        }
        graph_data = {
            'attempt_numbers': [],
            'points': [],
            'dates': []
        }
    
    # Convert graph data to JSON for JavaScript
    graph_data_json = {
        'attempt_numbers': json.dumps(graph_data['attempt_numbers']),
        'points': json.dumps(graph_data['points']),
        'dates': json.dumps(graph_data['dates'])
    }
    
    return render(request, "maths/measurements_progress.html", {
        "level": level,
        "attempt_history": attempt_history,
        "stats": stats,
        "graph_data": graph_data_json
    })

@login_required
def topic_list(request):
    topics = Topic.objects.all()
    return render(request, "maths/topics.html", {"topics": topics})

@login_required
def level_list(request, topic_id):
    topic = get_object_or_404(Topic, pk=topic_id)
    levels = topic.levels.all()
    return render(request, "maths/levels.html", {"topic": topic, "levels": levels})

@login_required
def level_detail(request, level_number):
    level = get_object_or_404(ClassroomLevel, level_number=level_number)
    topics = level.topics.all()
    return render(request, "maths/level_detail.html", {
        "level": level,
        "topics": topics
    })

def teacher_center_registration(request):
    """Handle teacher registration for creating a center/school"""
    if request.method == "POST":
        form = TeacherCenterRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            role, _ = Role.objects.get_or_create(name=Role.TEACHER, defaults={'display_name': 'Teacher'})
            UserRole.objects.get_or_create(user=user, role=role)
            login(request, user)
            messages.success(request, f"Welcome! You can now create classes for {form.cleaned_data['center_name']}")
            return redirect("maths:dashboard")
    else:
        form = TeacherCenterRegistrationForm()
    return render(request, "maths/teacher_center_registration.html", {"form": form})

def individual_student_registration(request):
    """Handle individual student registration"""
    if request.method == "POST":
        form = IndividualStudentRegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            role, _ = Role.objects.get_or_create(name=Role.STUDENT, defaults={'display_name': 'Student'})
            UserRole.objects.get_or_create(user=user, role=role)
            login(request, user)
            messages.success(request, "Welcome! You now have access to all levels.")
            return redirect("maths:dashboard")
    else:
        form = IndividualStudentRegistrationForm()
    return render(request, "maths/individual_student_registration.html", {"form": form})

@login_required
def bulk_student_registration(request):
    """Handle bulk student registration for teachers"""
    if not request.user.is_teacher:
        return redirect("maths:dashboard")
    
    if request.method == "POST":
        form = StudentBulkRegistrationForm(request.POST)
        if form.is_valid():
            students_data = form.cleaned_data['student_data']
            created_count = 0
            
            with transaction.atomic():
                for student_info in students_data:
                    try:
                        user = CustomUser.objects.create_user(
                            username=student_info['username'],
                            email=student_info['email'],
                            password=student_info['password'],
                        )
                        student_role, _ = Role.objects.get_or_create(name=Role.STUDENT, defaults={'display_name': 'Student'})
                        UserRole.objects.get_or_create(user=user, role=student_role)
                        created_count += 1
                    except Exception as e:
                        messages.error(request, f"Failed to create user {student_info['username']}: {str(e)}")
            
            messages.success(request, f"Successfully created {created_count} student accounts.")
            return redirect("maths:dashboard")
    else:
        form = StudentBulkRegistrationForm()
    
    return render(request, "maths/bulk_student_registration.html", {"form": form})

@login_required
def user_profile(request):
    """User profile page for viewing and editing profile information"""
    user = request.user
    profile_form = UserProfileForm(instance=user)
    password_form = UserPasswordChangeForm(user=user)
    
    if request.method == "POST":
        action = request.POST.get('action')
        
        if action == 'update_profile':
            profile_form = UserProfileForm(request.POST, instance=user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Profile updated successfully!")
                return redirect("maths:user_profile")
        
        elif action == 'change_password':
            password_form = UserPasswordChangeForm(user=user, data=request.POST)
            if password_form.is_valid():
                password_form.save()
                update_session_auth_hash(request, password_form.user)
                messages.success(request, "Password changed successfully!")
                return redirect("maths:user_profile")
    
    return render(request, "maths/user_profile.html", {
        "profile_form": profile_form,
        "password_form": password_form,
        "user": user
    })

def get_or_create_time_log(user):
    """Get or create TimeLog for user and handle resets (using local time)"""
    from django.utils.timezone import localtime
    time_log, created = TimeLog.objects.get_or_create(student=user)
    if created:
        # Initialize with current date/week (local time)
        from django.utils import timezone
        now_local = localtime(timezone.now())
        time_log.last_reset_date = now_local.date()
        iso = now_local.isocalendar()
        time_log.last_reset_week = iso[0] * 100 + iso[1]  # year*100+week to avoid year-rollover bug
        time_log.save()
    else:
        # Check and reset if needed
        time_log.reset_daily_if_needed()
        time_log.reset_weekly_if_needed()
    return time_log

def update_time_log_from_activities(user):
    """Update TimeLog by summing time_taken_seconds from completed quiz sessions.

    Uses StudentFinalAnswer (topic/times-table/mixed quizzes) and
    BasicFactsResult as the source of truth — these record actual time
    the student spent working on quizzes, not browsing time.
    """
    from django.utils import timezone
    from django.utils.timezone import localtime
    from datetime import timedelta

    time_log = get_or_create_time_log(user)

    now_local = localtime(timezone.now())
    today = now_local.date()
    days_since_monday = now_local.weekday()
    week_start = today - timedelta(days=days_since_monday)

    # Sum time from StudentFinalAnswer (topic, times-table, mixed quizzes)
    daily_sfa = weekly_sfa = 0
    for r in StudentFinalAnswer.objects.filter(student=user, time_taken_seconds__gt=0):
        r_date = localtime(r.completed_at).date()
        if r_date == today:
            daily_sfa += r.time_taken_seconds
        if r_date >= week_start:
            weekly_sfa += r.time_taken_seconds

    # Sum time from BasicFactsResult
    daily_bf = weekly_bf = 0
    for r in BasicFactsResult.objects.filter(student=user, time_taken_seconds__gt=0):
        r_date = localtime(r.completed_at).date()
        if r_date == today:
            daily_bf += r.time_taken_seconds
        if r_date >= week_start:
            weekly_bf += r.time_taken_seconds

    time_log.daily_total_seconds = daily_sfa + daily_bf
    time_log.weekly_total_seconds = weekly_sfa + weekly_bf
    time_log.save(update_fields=['daily_total_seconds', 'weekly_total_seconds', 'last_activity'])

    return time_log

@login_required
@require_http_methods(["GET", "POST"])
def update_time_log(request):
    """AJAX endpoint to get current time log (heartbeat-accumulated time)"""
    if not request.user.is_authenticated or request.user.is_teacher:
        return JsonResponse({'error': 'Not authorized'}, status=401)

    try:
        time_log = get_or_create_time_log(request.user)

        return JsonResponse({
            'success': True,
            'daily_seconds': time_log.daily_total_seconds,
            'weekly_seconds': time_log.weekly_total_seconds
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)

@login_required
def add_question(request, level_number):
    """Add a new question to a specific level"""
    if not request.user.is_teacher:
        messages.error(request, "Only teachers can add questions.")
        return redirect("maths:dashboard")
    
    level = get_object_or_404(Level, level_number=level_number)
    
    if request.method == "POST":
        question_form = QuestionForm(request.POST)
        answer_formset = AnswerFormSet(request.POST)
        
        if question_form.is_valid() and answer_formset.is_valid():
            with transaction.atomic():
                # Save the question
                question = question_form.save(commit=False)
                question.level = level
                question.save()
                
                # Save the answers
                for form in answer_formset:
                    if form.cleaned_data.get('answer_text'):
                        answer = form.save(commit=False)
                        answer.question = question
                        answer.save()
                
                messages.success(request, f"Question added successfully to {level}!")
                return redirect("maths:level_questions", level_number=level.level_number)
    else:
        question_form = QuestionForm()
        answer_formset = AnswerFormSet()
    
    return render(request, "maths/add_question.html", {
        "question_form": question_form,
        "answer_formset": answer_formset,
        "level": level
    })

@login_required
def level_questions(request, level_number):
    """Display all questions for a specific level"""
    level = get_object_or_404(Level, level_number=level_number)
    questions = _get_questions_for_level(request.user, level)

    return render(request, "maths/level_questions.html", {
        "level": level,
        "questions": questions
    })

def generate_basic_facts_question(level_num):
    """Generate a single question for Basic Facts levels"""
    if 100 <= level_num <= 106:  # Addition
        if level_num == 100:
            a, b = random.randint(1, 5), random.randint(1, 5)
            return f"{a} + {b} = ?", str(a + b)
        elif level_num == 101:
            a, b = random.randint(0, 9), random.randint(0, 9)
            return f"{a} + {b} = ?", str(a + b)
        elif level_num == 102:
            # No carry over
            a1, a2 = random.randint(1, 4), random.randint(0, 4)
            b1, b2 = random.randint(1, 4), random.randint(0, 9 - a2)
            a, b = a1 * 10 + a2, b1 * 10 + b2
            return f"{a} + {b} = ?", str(a + b)
        elif level_num == 103:
            # With carry over (units digits sum >= 10)
            a = random.randint(15, 99)
            a_units = a % 10
            b_tens = random.randint(1, 8)
            # Need b_units such that a_units + b_units >= 10 (requires carry over)
            # b_units should be >= (10 - a_units) and <= 9
            min_b_units = max(1, 10 - a_units)
            max_b_units = 9
            if min_b_units <= max_b_units:
                b_units = random.randint(min_b_units, max_b_units)
            else:
                # If a_units is 0, we'd need b_units >= 10 which is impossible
                # Regenerate a so a_units > 0, or use fallback approach
                # Regenerate a to ensure a_units is not 0
                while a_units == 0:
                    a = random.randint(15, 99)
                    a_units = a % 10
                min_b_units = max(1, 10 - a_units)
                b_units = random.randint(min_b_units, 9)
            b = b_tens * 10 + b_units
            return f"{a} + {b} = ?", str(a + b)
        elif level_num == 104:
            a, b = random.randint(100, 999), random.randint(100, 999)
            return f"{a} + {b} = ?", str(a + b)
        elif level_num == 105:
            a, b = random.randint(1000, 9999), random.randint(1000, 9999)
            return f"{a} + {b} = ?", str(a + b)
        elif level_num == 106:
            a, b = random.randint(10000, 99999), random.randint(10000, 99999)
            return f"{a} + {b} = ?", str(a + b)
    
    elif 107 <= level_num <= 113:  # Subtraction
        if level_num == 107:
            a = random.randint(5, 9)
            b = random.randint(1, a)
            return f"{a} - {b} = ?", str(a - b)
        elif level_num == 108:
            a = random.randint(10, 99)
            a_units = a % 10
            b = random.randint(0, a_units)
            return f"{a} - {b} = ?", str(a - b)
        elif level_num == 109:
            # Subtraction with borrowing (a_units < b_units)
            a = random.randint(10, 99)
            a_units = a % 10
            # b must be > a_units to require borrowing, but <= 9
            # If a_units is 9, there's no valid b (would need b > 9)
            # So we ensure a_units < 9, or adjust the range
            min_b = a_units + 1
            max_b = 9
            if min_b <= max_b:
                b = random.randint(min_b, max_b)
            else:
                # If a_units is 9, we can't create a borrowing scenario with single digits
                # So generate a new 'a' that allows borrowing, or use a fallback
                # Regenerate a with units digit < 9
                while a_units >= 9:
                    a = random.randint(10, 99)
                    a_units = a % 10
                b = random.randint(a_units + 1, 9)
            return f"{a} - {b} = ?", str(a - b)
        elif level_num == 110:
            a = random.randint(20, 99)
            b = random.randint(10, a)
            return f"{a} - {b} = ?", str(a - b)
        elif level_num == 111:
            a, b = random.randint(10, 99), random.randint(10, 99)
            return f"{a} - {b} = ?", str(a - b)
        elif level_num == 112:
            a = random.randint(100, 999)
            b = random.randint(100, a)
            return f"{a} - {b} = ?", str(a - b)
        elif level_num == 113:
            a = random.randint(1000, 9999)
            b = random.randint(1000, a)
            return f"{a} - {b} = ?", str(a - b)
    
    elif 114 <= level_num <= 120:  # Multiplication
        if level_num == 114:
            multiplier = random.choice([1, 10])
            base = random.randint(1, 99)
            return f"{base} × {multiplier} = ?", str(base * multiplier)
        elif level_num == 115:
            multiplier = random.choice([1, 10, 100])
            base = random.randint(1, 99)
            return f"{base} × {multiplier} = ?", str(base * multiplier)
        elif level_num == 116:
            multiplier = random.choice([5, 10])
            base = random.randint(1, 99)
            return f"{base} × {multiplier} = ?", str(base * multiplier)
        elif level_num == 117:
            multiplier = random.choice([2, 3, 5, 10])
            base = random.randint(1, 99)
            return f"{base} × {multiplier} = ?", str(base * multiplier)
        elif level_num == 118:
            multiplier = random.choice([2, 3, 4, 5, 10])
            base = random.randint(10, 999)
            return f"{base} × {multiplier} = ?", str(base * multiplier)
        elif level_num == 119:
            multiplier = random.choice([2, 3, 4, 5, 6, 7, 10])
            base = random.randint(10, 999)
            return f"{base} × {multiplier} = ?", str(base * multiplier)
        elif level_num == 120:
            multiplier = random.choice([2, 3, 4, 5, 6, 7, 8, 9, 10])
            base = random.randint(100, 999)
            return f"{base} × {multiplier} = ?", str(base * multiplier)
    
    elif 121 <= level_num <= 127:  # Division
        if level_num == 121:
            divisor = random.choice([1, 10])
            if divisor == 10:
                quotient = random.randint(1, 9)
                dividend = quotient * 10
            else:
                dividend = random.randint(10, 99)
                quotient = dividend
            return f"{dividend} ÷ {divisor} = ?", str(quotient)
        elif level_num == 122:
            divisor = random.choice([1, 10, 100])
            if divisor == 100:
                quotient = random.randint(1, 9)
                dividend = quotient * 100
            elif divisor == 10:
                quotient = random.randint(10, 99)
                dividend = quotient * 10
            else:
                dividend = random.randint(100, 999)
                quotient = dividend
            return f"{dividend} ÷ {divisor} = ?", str(quotient)
        elif level_num == 123:
            divisor = random.choice([5, 10])
            quotient = random.randint(10, 99) if divisor == 10 else random.randint(10, 199)
            dividend = quotient * divisor
            return f"{dividend} ÷ {divisor} = ?", str(quotient)
        elif level_num == 124:
            divisor = random.choice([2, 3, 5, 10])
            quotient = random.randint(10, 99)
            dividend = quotient * divisor
            return f"{dividend} ÷ {divisor} = ?", str(quotient)
        elif level_num == 125:
            divisor = random.choice([2, 3, 4, 5, 10])
            quotient = random.randint(10, 99)
            dividend = quotient * divisor
            return f"{dividend} ÷ {divisor} = ?", str(quotient)
        elif level_num == 126:
            divisor = random.choice([2, 3, 4, 5, 6, 7, 10])
            quotient = random.randint(10, 99)
            dividend = quotient * divisor
            return f"{dividend} ÷ {divisor} = ?", str(quotient)
        elif level_num == 127:
            divisor = random.choice([2, 3, 4, 5, 6, 7, 8, 9, 10, 11])
            quotient = random.randint(10, 99)
            dividend = quotient * divisor
            return f"{dividend} ÷ {divisor} = ?", str(quotient)
    
    elif 128 <= level_num <= 132:  # Place Value Facts
        target_values = {128: 10, 129: 100, 130: 1000, 131: 10000, 132: 100000}
        target = target_values.get(level_num)
        
        if target is None:
            return None, None
        
        # Randomly choose question format: 0 = a + b = ?, 1 = a + ? = target, 2 = ? + b = target
        question_type = random.randint(0, 2)
        
        if level_num == 128:  # Combinations for 10
            if question_type == 0:
                # a + b = ?
                a = random.randint(1, 9)
                b = target - a
                return f"{a} + {b} = ?", str(target)
            elif question_type == 1:
                # a + ? = 10
                a = random.randint(1, 9)
                b = target - a
                return f"{a} + ? = {target}", str(b)
            else:
                # ? + b = 10
                b = random.randint(1, 9)
                a = target - b
                return f"? + {b} = {target}", str(a)
        
        elif level_num == 129:  # Combinations for 100
            if question_type == 0:
                # a + b = ?
                # Can be simple (e.g., 40 + 60) or complex (e.g., 63 + 37)
                use_complex = random.choice([True, False])
                if use_complex:
                    # Generate numbers that add to 100 with varied digits
                    a = random.randint(10, 99)
                    b = target - a
                    if b < 10 or b > 99:
                        # Fallback to simple case
                        a = random.randint(10, 90)
                        b = target - a
                else:
                    # Simple case: multiples of 10
                    a_tens = random.randint(1, 9)
                    a = a_tens * 10
                    b = target - a
                return f"{a} + {b} = ?", str(target)
            elif question_type == 1:
                # a + ? = 100
                a = random.randint(10, 99)
                b = target - a
                return f"{a} + ? = {target}", str(b)
            else:
                # ? + b = 100
                b = random.randint(10, 99)
                a = target - b
                return f"? + {b} = {target}", str(a)
        
        elif level_num == 130:  # Combinations for 1000
            if question_type == 0:
                # a + b = ?
                a = random.randint(100, 999)
                b = target - a
                return f"{a} + {b} = ?", str(target)
            elif question_type == 1:
                # a + ? = 1000
                a = random.randint(100, 999)
                b = target - a
                return f"{a} + ? = {target}", str(b)
            else:
                # ? + b = 1000
                b = random.randint(100, 999)
                a = target - b
                return f"? + {b} = {target}", str(a)
        
        elif level_num == 131:  # Combinations for 10000
            if question_type == 0:
                # a + b = ?
                a = random.randint(1000, 9999)
                b = target - a
                return f"{a} + {b} = ?", str(target)
            elif question_type == 1:
                # a + ? = 10000
                a = random.randint(1000, 9999)
                b = target - a
                return f"{a} + ? = {target}", str(b)
            else:
                # ? + b = 10000
                b = random.randint(1000, 9999)
                a = target - b
                return f"? + {b} = {target}", str(a)
        
        elif level_num == 132:  # Combinations for 100000
            if question_type == 0:
                # a + b = ?
                a = random.randint(10000, 99999)
                b = target - a
                return f"{a} + {b} = ?", str(target)
            elif question_type == 1:
                # a + ? = 100000
                a = random.randint(10000, 99999)
                b = target - a
                return f"{a} + ? = {target}", str(b)
            else:
                # ? + b = 100000
                b = random.randint(10000, 99999)
                a = target - b
                return f"? + {b} = {target}", str(a)
    
    return None, None

class DynamicQuestion:
    """Simple class to mimic Question object for Basic Facts"""
    def __init__(self, question_text, correct_answer, question_id):
        self.id = question_id
        self.question_text = question_text
        self.correct_answer = correct_answer
        self.question_type = 'short_answer'
        self.points = 1
        self.image = None
        self.explanation = None
        self.answers = type('obj', (object,), {'all': lambda: []})()

@login_required
def basic_facts_subtopic(request, subtopic_name):
    """Show level selection page for a Basic Facts subtopic"""
    # Validate subtopic name
    valid_subtopics = ['Addition', 'Subtraction', 'Multiplication', 'Division', 'Place Value Facts']
    if subtopic_name not in valid_subtopics:
        messages.error(request, "Invalid subtopic.")
        return redirect("maths:dashboard")
    
    # Get all levels for this subtopic
    topic = get_object_or_404(Topic, name=subtopic_name)
    levels = Level.objects.filter(
        topics=topic,
        level_number__gte=100
    ).order_by('level_number')
    
    # Handle form submission
    if request.method == 'POST':
        level_number = request.POST.get('level_number')
        if level_number:
            try:
                level = Level.objects.get(level_number=int(level_number), topics=topic)
                topic_slug = normalize_basic_facts_topic(subtopic_name)
                display_level = get_display_level_for_basic_facts(level.level_number, subtopic_name)
                if topic_slug and display_level:
                    return redirect(
                        'maths:take_basic_facts_quiz',
                        basic_topic=topic_slug,
                        display_level=display_level
                    )
                return redirect('maths:take_quiz', level_number=level.level_number)
            except (Level.DoesNotExist, ValueError):
                messages.error(request, "Invalid level selected.")
    
    # Get subtopic icon
    subtopic_icons = {
        'Addition': '➕',
        'Subtraction': '➖',
        'Multiplication': '✖️',
        'Division': '➗',
        'Place Value Facts': '🔢'
    }
    
    return render(request, "maths/basic_facts_subtopic.html", {
        "subtopic_name": subtopic_name,
        "levels": levels,
        "subtopic_icon": subtopic_icons.get(subtopic_name, '🧮')
    })


@login_required
def take_basic_facts_quiz(request, basic_topic, display_level):
    """
    Friendly URL wrapper for Basic Facts quizzes.
    Converts /level/addition/6/quiz to the underlying numeric level.
    """
    level_number = get_level_number_for_basic_facts(basic_topic, display_level)
    if not level_number:
        raise Http404("Invalid Basic Facts level.")
    return take_quiz(request, level_number)


@login_required
def take_quiz(request, level_number):
    """Allow students to take a quiz for a specific level"""
    level = get_object_or_404(ClassroomLevel, level_number=level_number)
    
    # For Basic Facts levels, generate questions dynamically
    is_basic_facts = level_number >= 100
    session_questions_key = f"quiz_questions_{level_number}"
    
    # Timer handling - start timer on first load
    timer_session_key = f"quiz_timer_{level_number}"
    timer_start = request.session.get(timer_session_key)
    
    # Check if there's a recently completed quiz (within last 30 seconds) to show results on refresh
    if is_basic_facts and request.method == "GET":
        from django.utils import timezone
        from datetime import timedelta
        recent_result = BasicFactsResult.objects.filter(
            student=request.user,
            level=level
        ).order_by('-completed_at').first()
        
        if recent_result:
            # Check if completed within last 30 seconds
            # Convert completed_at to timezone-aware if needed
            completed_at = recent_result.completed_at
            if timezone.is_naive(completed_at):
                completed_at = timezone.make_aware(completed_at)
            
            time_since_completion = timezone.now() - completed_at
            if time_since_completion.total_seconds() < 30:
                # Show completion screen with stored results
                previous_results = BasicFactsResult.objects.filter(
                    student=request.user,
                    level=level
                ).exclude(session_id=recent_result.session_id).order_by('-points')
                
                previous_best_points = float(previous_results.first().points) if previous_results.exists() else None
                beat_record = previous_best_points is not None and float(recent_result.points) > previous_best_points
                is_first_attempt = previous_best_points is None
                
                return render(request, "maths/take_quiz.html", {
                    "level": level,
                    "completed": True,
                    "total_score": recent_result.score,
                    "total_points": recent_result.total_points,
                    "total_time_seconds": recent_result.time_taken_seconds,
                    "final_points": float(recent_result.points),
                    "previous_best_points": round(previous_best_points, 2) if previous_best_points is not None else None,
                    "beat_record": beat_record,
                    "is_first_attempt": is_first_attempt,
                    "question_review_data": [],  # Can't retrieve review data after session cleared
                    "is_basic_facts": True
                })
    
    if is_basic_facts:
        if request.method == "GET":
            # Reset timer on every new quiz load
            request.session[timer_session_key] = time.time()

            # Generate 10 questions
            questions_data = []
            for i in range(10):
                q_text, correct_answer = generate_basic_facts_question(level_number)
                if q_text:
                    questions_data.append({
                        'text': q_text,
                        'correct_answer': correct_answer,
                        'index': i
                    })
            request.session[session_questions_key] = questions_data
            
            # Create DynamicQuestion objects for template
            questions = [DynamicQuestion(q['text'], q['correct_answer'], q['index']) for q in questions_data]
        else:
            # POST - retrieve from session
            questions_data = request.session.get(session_questions_key, [])
            questions = [DynamicQuestion(q['text'], q['correct_answer'], q['index']) for q in questions_data]
    else:
        # For regular quizzes, get questions from database and store in session
        if request.method == "GET":
            # Reset timer on every new quiz load
            request.session[timer_session_key] = time.time()

            # Get all questions for this level scoped to the student's school.
            # Loads local ∪ global if both exist; local-only or global-only otherwise.
            all_questions = list(
                _get_questions_for_level(request.user, level).prefetch_related('answers')
            )
            
            question_limit = YEAR_QUESTION_COUNTS.get(level.level_number, 10)
            
            # Select random questions using stratified sampling
            if len(all_questions) > question_limit:
                questions = select_questions_stratified(all_questions, question_limit)
            else:
                questions = all_questions
            
            # Shuffle the questions
            random.shuffle(questions)
            
            # Randomize answer order for each question (answers already prefetched)
            for question in questions:
                if question.question_type in ['multiple_choice', 'true_false']:
                    # Store shuffled answer IDs in a temporary attribute
                    answers_list = list(question.answers.all())
                    random.shuffle(answers_list)
                    question.shuffled_answers = answers_list
            
            # Store question IDs in session
            request.session[session_questions_key] = [q.id for q in questions]
        else:
            # POST - retrieve question IDs from session and load questions
            # Use bulk query with prefetch_related to avoid N+1 queries
            question_ids = request.session.get(session_questions_key, [])
            if question_ids:
                questions = list(Question.objects.filter(
                    id__in=question_ids,
                    level=level
                ).prefetch_related('answers'))
                
                # Create a dict for quick lookup and maintain order
                questions_dict = {q.id: q for q in questions}
                questions = [questions_dict[qid] for qid in question_ids if qid in questions_dict]
                
                # Randomize answer order for MCQs (answers already prefetched)
                for question in questions:
                    if question.question_type in ['multiple_choice', 'true_false']:
                        answers_list = list(question.answers.all())
                        random.shuffle(answers_list)
                        question.shuffled_answers = answers_list
            else:
                questions = []
    
    if request.method == "POST":
        # Check if quiz was already completed (prevent duplicate submissions)
        if is_basic_facts:
            from django.utils import timezone
            from datetime import timedelta
            recent_result = BasicFactsResult.objects.filter(
                student=request.user,
                level=level
            ).order_by('-completed_at').first()
            
            if recent_result:
                # Check if completed within last 5 seconds (likely a duplicate submission)
                completed_at = recent_result.completed_at
                if timezone.is_naive(completed_at):
                    completed_at = timezone.make_aware(completed_at)
                
                time_since_completion = timezone.now() - completed_at
                if time_since_completion.total_seconds() < 5:
                    # This is likely a duplicate submission, show the existing result
                    previous_results = BasicFactsResult.objects.filter(
                        student=request.user,
                        level=level
                    ).exclude(session_id=recent_result.session_id).order_by('-points')
                    
                    previous_best_points = float(previous_results.first().points) if previous_results.exists() else None
                    beat_record = previous_best_points is not None and float(recent_result.points) > previous_best_points
                    is_first_attempt = previous_best_points is None
                    
                    return render(request, "maths/take_quiz.html", {
                        "level": level,
                        "completed": True,
                        "total_score": recent_result.score,
                        "total_points": recent_result.total_points,
                        "total_time_seconds": recent_result.time_taken_seconds,
                        "final_points": float(recent_result.points),
                        "previous_best_points": round(previous_best_points, 2) if previous_best_points is not None else None,
                        "beat_record": beat_record,
                        "is_first_attempt": is_first_attempt,
                        "question_review_data": [],
                        "is_basic_facts": True
                    })
        
        # Get time elapsed
        now_ts = time.time()
        start_ts = request.session.get(timer_session_key, now_ts)
        time_taken_seconds = max(1, int(now_ts - start_ts))
        
        score = 0
        total_points = 0
        correct_count = 0
        # Create a session id for this quiz attempt to track best records
        import uuid
        session_id = str(uuid.uuid4())

        # Store question/answer review data for Basic Facts popup
        question_review_data = [] if is_basic_facts else None

        for question in questions:
            total_points += question.points
            
            if is_basic_facts:
                # Handle dynamic Basic Facts questions
                student_answer = request.POST.get(f'question_{question.id}', '').strip()
                # Normalize answer (remove spaces, handle negative signs)
                student_answer_normalized = student_answer.replace(' ', '')
                correct_answer_normalized = question.correct_answer.replace(' ', '')
                
                is_correct = (student_answer_normalized == correct_answer_normalized)
                if is_correct:
                    score += question.points
                    correct_count += 1

                # Store question/answer data for review popup
                question_review_data.append({
                    'question_text': question.question_text,
                    'student_answer': student_answer,
                    'correct_answer': question.correct_answer,
                    'is_correct': is_correct,
                    'points': question.points if is_correct else 0
                })
                
                # For Basic Facts, results are stored in database after quiz completion
            elif question.question_type == 'multiple_choice':
                answer_id = request.POST.get(f'question_{question.id}')
                if answer_id:
                    try:
                        selected_answer = Answer.objects.get(id=answer_id, question=question)
                        is_correct = selected_answer.is_correct
                        if is_correct:
                            score += question.points
                            correct_count += 1

                        # Save student answer
                        StudentAnswer.objects.update_or_create(
                            student=request.user,
                            question=question,
                            defaults={
                                'selected_answer': selected_answer,
                                'is_correct': is_correct,
                                'points_earned': question.points if is_correct else 0,
                                'session_id': session_id,
                                'time_taken_seconds': time_taken_seconds
                            }
                        )
                    except Answer.DoesNotExist:
                        pass
        
        # For Basic Facts, store results in database for persistent tracking
        if is_basic_facts:
            # Calculate points same as measurements, but divide by 10 for Basic Facts
            percentage = (score / total_points) if total_points else 0
            final_points_calc = ((percentage * 100 * 60) / time_taken_seconds) / 10 if time_taken_seconds else 0
            final_points_calc = round(final_points_calc, 2)
            
            # Save to database with retry logic
            from maths.utils import retry_on_db_lock
            
            @retry_on_db_lock(max_retries=5)
            def save_basic_facts_result():
                BasicFactsResult.objects.create(
                    student=request.user,
                    level=level,
                    session_id=session_id,
                    score=score,
                    total_points=total_points,
                    time_taken_seconds=time_taken_seconds,
                    points=final_points_calc
                )
            
            save_basic_facts_result()
            
            # Also keep in session for backward compatibility (optional)
            basic_facts_results_key = f"basic_facts_results_{request.user.id}_{level_number}"
            results_list = request.session.get(basic_facts_results_key, [])
            from django.utils import timezone
            result_entry = {
                'session_id': session_id,
                'score': score,
                'total_points': total_points,
                'time_taken_seconds': time_taken_seconds,
                'points': final_points_calc,
                'date': timezone.now().isoformat()
            }
            results_list.append(result_entry)
            request.session[basic_facts_results_key] = results_list
            
            # Clear questions from session
            if session_questions_key in request.session:
                del request.session[session_questions_key]
        
        # Clear timer from session
        if timer_session_key in request.session:
            del request.session[timer_session_key]
        
        # Calculate points using the formula: percentage * 100 * 60 / time_seconds
        # For Basic Facts, divide by 10
        percentage = (score / total_points) if total_points else 0
        if is_basic_facts:
            final_points = ((percentage * 100 * 60) / time_taken_seconds) / 10 if time_taken_seconds else 0
        else:
            final_points = (percentage * 100 * 60) / time_taken_seconds if time_taken_seconds else 0
        final_points = round(final_points, 2)
        
        # Compute previous best record for this level
        if is_basic_facts:
            # For Basic Facts, check database for previous results (excluding current session)
            previous_results = BasicFactsResult.objects.filter(
                student=request.user,
                level=level
            ).exclude(session_id=session_id).order_by('-points')
            
            if previous_results.exists():
                previous_best_points = float(previous_results.first().points)
            else:
                previous_best_points = None
        else:
            # For regular levels, save to StudentFinalAnswer with "Quiz" topic
            if not is_basic_facts:
                # Get or create "Quiz" topic for mixed quizzes
                quiz_topic = get_or_create_classroom_topic("Quiz")
                
                # Save to StudentFinalAnswer table with retry logic
                from maths.utils import save_student_final_answer
                save_student_final_answer(
                    student=request.user,
                    session_id=session_id,
                    topic=quiz_topic,
                    level=level,
                    points_earned=final_points,
                    score=correct_count,
                    total_questions=len(questions),
                    points=final_points,
                    time_taken_seconds=time_taken_seconds,
                    quiz_type='mixed',
                )
                
                # Update topic statistics asynchronously
                def update_stats_async():
                    try:
                        update_topic_statistics(level_num=level.level_number, topic_name="Quiz")
                    except Exception:
                        pass
                
                thread = threading.Thread(target=update_stats_async)
                thread.daemon = True
                thread.start()
            
            # For regular levels, check database records - optimized with aggregation
            previous_sessions_data = StudentAnswer.objects.filter(
                student=request.user,
                question__level=level
            ).exclude(session_id=session_id).exclude(session_id='').values('session_id').annotate(
                total_correct=Sum('is_correct'),
                total_count=Count('id'),
                total_points=Sum('points_earned'),
                time_taken=Max('time_taken_seconds')
            )

            previous_best_points = None
            for session_data in previous_sessions_data:
                session_id_val = session_data['session_id']
                if not session_id_val:
                    continue
                
                session_correct = session_data['total_correct'] or 0
                session_total = session_data['total_count'] or 1
                session_time = session_data['time_taken'] or 0
                session_points_earned = session_data['total_points'] or 0
                
                if session_time > 0:
                    session_percentage = (session_correct / session_total) if session_total else 0
                    session_points = (session_percentage * 100 * 60) / session_time if session_time else 0
                else:
                    session_points = session_points_earned
                
                if previous_best_points is None or session_points > previous_best_points:
                    previous_best_points = session_points

        # For Basic Facts, show completion screen like measurements
        if is_basic_facts:
            beat_record = previous_best_points is not None and final_points > previous_best_points
            is_first_attempt = previous_best_points is None
            
            return render(request, "maths/take_quiz.html", {
                "level": level,
                "completed": True,
                "total_score": score,
                "total_points": total_points,
                "total_time_seconds": time_taken_seconds,
                "final_points": final_points,
                "previous_best_points": round(previous_best_points, 2) if previous_best_points is not None else None,
                "beat_record": beat_record,
                "is_first_attempt": is_first_attempt,
                "question_review_data": question_review_data,
                "is_basic_facts": True
            })
        
        # For regular levels, show results page with all questions and answers
        if not is_basic_facts:
            # Get or create "Quiz" topic
            quiz_topic = get_or_create_classroom_topic("Quiz")
            
            # Get student answers for this session to show results
            student_answers_dict = {}
            student_answers_query = StudentAnswer.objects.filter(
                student=request.user,
                question__level=level,
                session_id=session_id
            ).select_related('question', 'selected_answer')
            
            for sa in student_answers_query:
                student_answers_dict[sa.question_id] = sa
            
            # Create question review data with explanations
            question_review_data = []
            for question in questions:
                student_answer_obj = student_answers_dict.get(question.id)
                is_correct = student_answer_obj.is_correct if student_answer_obj else False
                selected_answer_text = ""
                correct_answer_text = ""
                
                if question.question_type == 'multiple_choice' or question.question_type == 'true_false':
                    if student_answer_obj and student_answer_obj.selected_answer:
                        selected_answer_text = student_answer_obj.selected_answer.answer_text
                    # Get correct answer
                    correct_answer = question.answers.filter(is_correct=True).first()
                    if correct_answer:
                        correct_answer_text = correct_answer.answer_text
                elif question.question_type == 'short_answer':
                    if student_answer_obj:
                        selected_answer_text = student_answer_obj.text_answer or ""
                    # For short answer, we'd need to store the correct answer somewhere
                    # For now, just show the student's answer
                
                question_review_data.append({
                    'question': question,
                    'question_text': question.question_text,
                    'question_image': question.image,
                    'student_answer': selected_answer_text,
                    'correct_answer': correct_answer_text,
                    'is_correct': is_correct,
                    'points': question.points if is_correct else 0,
                    'explanation': question.explanation or ""
                })
            
            beat_record = previous_best_points is not None and final_points > previous_best_points
            is_first_attempt = previous_best_points is None
            
            # Clear questions from session
            if session_questions_key in request.session:
                del request.session[session_questions_key]
            
            return render(request, "maths/take_quiz.html", {
                "level": level,
                "completed": True,
                "total_score": score,
                "total_points": total_points,
                "total_time_seconds": time_taken_seconds,
                "final_points": final_points,
                "previous_best_points": round(previous_best_points, 2) if previous_best_points is not None else None,
                "beat_record": beat_record,
                "is_first_attempt": is_first_attempt,
                "question_review_data": question_review_data,
                "is_basic_facts": False
            })
    
    # For regular quizzes (non-Basic Facts), show all questions at once
    # Start timer on first load
    if not timer_start:
        request.session[timer_session_key] = time.time()
    
    # For Basic Facts, keep the original all-at-once approach
    # Start timer on first load
    if not timer_start:
        request.session[timer_session_key] = time.time()
    
    return render(request, "maths/take_quiz.html", {
        "level": level,
        "questions": questions
    })

@login_required
def practice_questions(request, level_number):
    """Practice questions with random selection from all topics"""
    level = get_object_or_404(ClassroomLevel, level_number=level_number)

    # Get all questions for this level
    all_questions = level.maths_questions_by_level.all()
    
    # Select random questions (limit to 10 for practice)
    if all_questions.count() > 10:
        questions = select_questions_stratified(list(all_questions), 10)
    else:
        questions = list(all_questions)
    
    # Shuffle the questions
    random.shuffle(questions)
    
    return render(request, "maths/topic_quiz.html", {
        "level": level,
        "questions": questions,
        "total_questions": all_questions.count()
    })



@login_required
@require_http_methods(["POST"])
def submit_topic_answer(request):
    """AJAX endpoint to save a student's answer for a topic question.
    Returns correctness info so the client never needs to know answers upfront."""
    data = json.loads(request.body)
    question_id = data.get('question_id')
    answer_id = data.get('answer_id')
    text_answer = data.get('text_answer')
    attempt_id = data.get('attempt_id', '')

    try:
        question = Question.objects.get(id=question_id)

        if answer_id:
            answer = Answer.objects.get(id=answer_id, question=question)
            StudentAnswer.objects.update_or_create(
                student=request.user,
                question=question,
                defaults={
                    'selected_answer': answer,
                    'is_correct': answer.is_correct,
                    'points_earned': question.points if answer.is_correct else 0,
                    'session_id': attempt_id
                }
            )
            # Find the correct answer text to return to client
            correct_answer_text = ''
            if not answer.is_correct:
                correct_obj = question.answers.filter(is_correct=True).first()
                if correct_obj:
                    correct_answer_text = correct_obj.answer_text

            return JsonResponse({
                'success': True,
                'is_correct': answer.is_correct,
                'correct_answer_id': question.answers.filter(is_correct=True).first().id if not answer.is_correct else None,
                'correct_answer_text': correct_answer_text,
                'explanation': question.explanation or '',
            })

        elif text_answer and question.question_type == 'short_answer':
            StudentAnswer.objects.update_or_create(
                student=request.user,
                question=question,
                defaults={
                    'text_answer': text_answer,
                    'is_correct': True,
                    'points_earned': question.points,
                    'session_id': attempt_id
                }
            )
            return JsonResponse({'success': True, 'is_correct': True, 'explanation': question.explanation or ''})

    except (Question.DoesNotExist, Answer.DoesNotExist):
        return JsonResponse({'success': False, 'error': 'Invalid question or answer'}, status=400)

    return JsonResponse({'success': False, 'error': 'Missing data'}, status=400)


@login_required
def topic_questions(request, level_number, topic_name):
    """Generic view for all topic-based questions (Measurements, Whole Numbers,
    Factors, Angles, Place Values, Fractions, BODMAS/PEMDAS, Date and Time,
    Finance, Integers, Trigonometry). Accepts level_number and topic_name.
    All questions are prefetched on initial load and rendered client-side for
    faster question navigation."""
    level = get_object_or_404(ClassroomLevel, level_number=level_number)

    topic_obj = Topic.objects.filter(name=topic_name).first()
    if not topic_obj:
        topic_obj = get_or_create_classroom_topic(topic_name)

    all_questions_query = Question.objects.filter(
        level=level,
        topic=topic_obj
    ).prefetch_related('answers')

    question_limit = YEAR_QUESTION_COUNTS.get(level.level_number, 10)

    # Times table topics always have exactly 12 questions — serve them all
    if topic_name.startswith("Multiplication (") or topic_name.startswith("Division ("):
        question_limit = max(question_limit, 12)

    topic_slug = TOPIC_SESSION_SLUGS.get(topic_name, slugify(topic_name))
    timer_session_key = f"{topic_slug}_timer_start"
    questions_session_key = f"{topic_slug}_question_ids"

    # Handle completion (GET ?completed=1) - keep server-side for scoring
    completed = request.GET.get('completed') == '1'
    if completed:
        question_ids = request.session.get(questions_session_key, [])
        if question_ids:
            questions_dict = {q.id: q for q in Question.objects.filter(
                id__in=question_ids,
                level=level,
                topic=topic_obj
            ).prefetch_related('answers')}
            all_questions = [questions_dict[qid] for qid in question_ids if qid in questions_dict]
        else:
            all_questions = []

        attempt_id = request.session.get('current_attempt_id', '')
        student_answers = StudentAnswer.objects.filter(
            student=request.user,
            question__level=level,
            question__topic=topic_obj,
            session_id=attempt_id
        )
        total_score = sum(answer.points_earned for answer in student_answers)
        total_points = sum(q.points for q in all_questions) if all_questions else 0
        if total_points == 0 and student_answers.exists():
            answered_question_ids = student_answers.values_list('question_id', flat=True).distinct()
            answered_questions = Question.objects.filter(
                id__in=answered_question_ids, level=level, topic=topic_obj
            )
            total_points = sum(q.points for q in answered_questions)
        now_ts = time.time()
        start_ts = request.session.get(timer_session_key) or now_ts
        total_time_seconds = max(1, int(now_ts - start_ts))

        student_answers.update(time_taken_seconds=total_time_seconds)

        def update_stats_async():
            try:
                update_topic_statistics(level_num=level.level_number, topic_name=topic_obj.name)
            except Exception:
                pass

        thread = threading.Thread(target=update_stats_async)
        thread.daemon = True
        thread.start()

        percentage = (total_score / total_points) if total_points else 0
        final_points = (percentage * 100 * 60) / total_time_seconds if total_time_seconds else 0
        final_points = round(final_points, 2)

        correct_count = sum(1 for a in student_answers if a.is_correct)
        question_count = len(all_questions) or student_answers.count()

        from maths.utils import save_student_final_answer
        save_student_final_answer(
            student=request.user,
            session_id=attempt_id,
            topic=topic_obj,
            level=level,
            points_earned=final_points,
            score=correct_count,
            total_questions=question_count,
            points=final_points,
            time_taken_seconds=total_time_seconds,
            quiz_type='topic',
        )

        current_attempt_id = attempt_id

        _clear_session_keys(
            request.session,
            timer_session_key, questions_session_key, 'current_attempt_id',
        )

        previous_best_points = _calculate_previous_best_points(
            request.user, level, topic_obj, current_attempt_id
        )

        beat_record = previous_best_points is not None and final_points > previous_best_points
        is_first_attempt = previous_best_points is None

        return render(request, "maths/topic_quiz.html", {
            "level": level,
            "completed": True,
            "total_score": total_score,
            "total_points": total_points,
            "total_time_seconds": total_time_seconds,
            "final_points": final_points,
            "topic": topic_obj,
            "student_answers": student_answers,
            "all_questions": all_questions,
            "previous_best_points": round(previous_best_points, 2) if previous_best_points is not None else None,
            "beat_record": beat_record,
            "is_first_attempt": is_first_attempt
        })

    # Fresh start: select questions, store in session, and prefetch all for client-side rendering
    _clear_session_keys(
        request.session,
        timer_session_key, questions_session_key, 'current_attempt_id',
    )

    request.session[timer_session_key] = time.time()
    request.session['current_attempt_id'] = str(uuid.uuid4())

    all_questions_list = []
    for q in all_questions_query:
        answer_count = q.answers.count()
        correct_count = q.answers.filter(is_correct=True).count()
        wrong_count = q.answers.filter(is_correct=False).count()
        if answer_count == 0:
            continue
        if correct_count == 0:
            continue
        if q.question_type in ['multiple_choice', 'true_false'] and wrong_count == 0:
            continue
        all_questions_list.append(q)

    if len(all_questions_list) > question_limit:
        selected_questions = select_questions_stratified(all_questions_list, question_limit)
    else:
        selected_questions = all_questions_list

    random.shuffle(selected_questions)
    request.session[questions_session_key] = [q.id for q in selected_questions]

    # Serialize all questions and their answers as JSON for client-side rendering
    questions_json_data = []
    for q in selected_questions:
        answers_list = list(q.answers.all())
        random.shuffle(answers_list)
        answers_data = [{
            'id': a.id,
            'answer_text': a.answer_text,
        } for a in answers_list]
        questions_json_data.append({
            'id': q.id,
            'question_text': q.question_text,
            'question_type': q.question_type,
            'image_url': q.image.url if q.image else None,
            'points': q.points,
            'answers': answers_data,
        })

    return render(request, "maths/topic_quiz.html", {
        "level": level,
        "topic": topic_obj,
        "total_questions": len(selected_questions),
        "questions_json": json.dumps(questions_json_data),
        "attempt_id": request.session.get('current_attempt_id', ''),
        "prefetched": True,
    })


def measurements_questions(request, level_number):
    return topic_questions(request, level_number, "Measurements")


def whole_numbers_questions(request, level_number):
    return topic_questions(request, level_number, "Whole Numbers")


def factors_questions(request, level_number):
    return topic_questions(request, level_number, "Factors")


def angles_questions(request, level_number):
    return topic_questions(request, level_number, "Angles")


def place_values_questions(request, level_number):
    return topic_questions(request, level_number, "Place Values")


def fractions_questions(request, level_number):
    return topic_questions(request, level_number, "Fractions")


def bodmas_questions(request, level_number):
    return topic_questions(request, level_number, "BODMAS/PEMDAS")


def date_time_questions(request, level_number):
    return topic_questions(request, level_number, "Date and Time")


def finance_questions(request, level_number):
    return topic_questions(request, level_number, "Finance")


def integers_questions(request, level_number):
    return topic_questions(request, level_number, "Integers")


def trigonometry_questions(request, level_number):
    return topic_questions(request, level_number, "Trigonometry")


def _get_or_create_times_table_questions(level, topic_obj, table_number, operation):
    """Ensure Question and Answer objects exist in the DB for a given times table.
    Creates them on first access so that submit_topic_answer works seamlessly.
    operation: 'multiplication' or 'division'
    Returns the list of Question objects (12 questions: X*1 through X*12)."""
    existing = list(
        Question.objects.filter(level=level, topic=topic_obj)
        .prefetch_related('answers')
        .order_by('id')
    )
    if len(existing) >= 12:
        return existing[:12]

    # Need to create questions
    questions = []
    for i in range(1, 13):
        if operation == 'multiplication':
            q_text = f"{table_number} \u00d7 {i} = ?"
            correct_answer = table_number * i
        else:  # division
            product = table_number * i
            q_text = f"{product} \u00f7 {table_number} = ?"
            correct_answer = i

        # Check if this specific question already exists
        q = Question.objects.filter(
            level=level, topic=topic_obj, question_text=q_text
        ).first()
        if q:
            questions.append(q)
            continue

        q = Question.objects.create(
            level=level,
            topic=topic_obj,
            question_text=q_text,
            question_type='multiple_choice',
            difficulty=1,
            points=1,
            explanation=f"{q_text.replace(' = ?', '')} = {correct_answer}",
        )

        # Create correct answer
        Answer.objects.create(
            question=q, answer_text=str(correct_answer), is_correct=True, order=0
        )

        # Create 3 wrong answers (nearby plausible numbers)
        wrong_answers = set()
        # Strategy: offset by -2, -1, +1, +2 from correct, and random nearby
        candidates = [
            correct_answer - 2, correct_answer - 1,
            correct_answer + 1, correct_answer + 2,
            correct_answer + table_number, correct_answer - table_number,
            correct_answer * 2, correct_answer + 10,
        ]
        for c in candidates:
            if c > 0 and c != correct_answer and c not in wrong_answers:
                wrong_answers.add(c)
            if len(wrong_answers) >= 3:
                break
        # Fallback if we don't have 3 yet
        offset = 3
        while len(wrong_answers) < 3:
            candidate = correct_answer + offset
            if candidate > 0 and candidate != correct_answer and candidate not in wrong_answers:
                wrong_answers.add(candidate)
            offset += 1

        for idx, wa in enumerate(sorted(wrong_answers)[:3], start=1):
            Answer.objects.create(
                question=q, answer_text=str(wa), is_correct=False, order=idx
            )

        questions.append(q)

    return questions


@login_required
def multiplication_selection(request, level_number):
    """Show times table selection grid for Multiplication."""
    level = get_object_or_404(ClassroomLevel, level_number=level_number)

    tables = TIMES_TABLES_BY_YEAR.get(level_number, [])
    return render(request, "maths/times_table_selection.html", {
        "level": level,
        "tables": tables,
        "operation": "multiplication",
        "operation_display": "Multiplication",
        "operation_symbol": "\u00d7",
        "operation_icon": "\u2716\ufe0f",
    })


@login_required
def division_selection(request, level_number):
    """Show times table selection grid for Division."""
    level = get_object_or_404(ClassroomLevel, level_number=level_number)

    tables = TIMES_TABLES_BY_YEAR.get(level_number, [])
    return render(request, "maths/times_table_selection.html", {
        "level": level,
        "tables": tables,
        "operation": "division",
        "operation_display": "Division",
        "operation_symbol": "\u00f7",
        "operation_icon": "\u2797",
    })


@login_required
def times_table_quiz(request, level_number, table_number, operation):
    """Run a times table quiz. Generates questions on-the-fly and delegates to
    the standard topic_questions flow so scoring, progress tracking, and the
    submit_topic_answer endpoint all work identically to other topics."""
    level = get_object_or_404(ClassroomLevel, level_number=level_number)
    tables = TIMES_TABLES_BY_YEAR.get(level_number, [])
    if table_number not in tables:
        messages.error(request, f"{table_number} times table is not available for Year {level_number}.")
        return redirect("maths:dashboard")

    if operation == 'multiplication':
        topic_name = f"Multiplication ({table_number}\u00d7)"
    else:
        topic_name = f"Division ({table_number}\u00d7)"

    # Get or create Topic (classroom.Topic)
    topic_obj = Topic.objects.filter(name=topic_name).first()
    if not topic_obj:
        topic_obj = get_or_create_classroom_topic(topic_name)

    # Ensure questions exist in DB
    _get_or_create_times_table_questions(level, topic_obj, table_number, operation)

    # Delegate to the standard topic_questions view
    return topic_questions(request, level_number, topic_name)


def multiplication_quiz(request, level_number, table_number):
    return times_table_quiz(request, level_number, table_number, 'multiplication')


def division_quiz(request, level_number, table_number):
    return times_table_quiz(request, level_number, table_number, 'division')

