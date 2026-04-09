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
    
    level = get_object_or_404(ClassroomLevel, level_number=level_number)
    
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
    level = get_object_or_404(ClassroomLevel, level_number=level_number)
    questions = _get_questions_for_level(request.user, level)

    return render(request, "maths/level_questions.html", {
        "level": level,
        "questions": questions
    })

