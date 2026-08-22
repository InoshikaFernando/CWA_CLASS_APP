"""The topic and mixed quizzes serve the GLOBAL bank only.

Both views used a plain ``Question.objects.filter(topic=..., level=...)``, which
reads the whole table — so one school's private questions were served to every
other school's students, and to students in no school at all. These tests pin
the rule: the same questions for everyone, and nothing school-private.
"""
import pytest
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from classroom.models import Level, School, SchoolStudent, Subject, Topic
from maths.models import Answer, Question


@pytest.fixture
def bank(db):
    subject = Subject.objects.create(name='Mathematics', slug='mathematics', school=None)
    level = Level.objects.create(level_number=4, display_name='Year 4', school=None)
    number = Topic.objects.create(subject=subject, name='Number', slug='number-scope')
    patterns = Topic.objects.create(subject=subject, name='Number Patterns',
                                    slug='np-scope', parent=number)
    other = Topic.objects.create(subject=subject, name='Fractions',
                                 slug='fr-scope', parent=number)
    patterns.levels.add(level)
    other.levels.add(level)

    admin = CustomUser.objects.create_user('sc_admin', 'sa@example.com', 'pass1234')
    mhm = School.objects.create(name='MHM', slug='mhm-scope', admin=admin)
    rival = School.objects.create(name='Rival', slug='rival-scope', admin=admin)

    def q(text, topic=None, school=None):
        obj = Question.objects.create(
            school=school, level=level, topic=topic or patterns, question_text=text,
            question_type='multiple_choice', difficulty=1, points=1)
        Answer.objects.create(question=obj, answer_text='ok', is_correct=True)
        return obj

    return {
        'level': level, 'patterns': patterns, 'other': other,
        'mhm': mhm, 'rival': rival, 'q': q,
        'global_ids': {q('global one').id, q('global two').id},
        'mhm_ids': {q(f'mhm {i}', school=mhm).id for i in range(5)},
        'rival_ids': {q(f'rival {i}', school=rival).id for i in range(3)},
    }


def student(client, username, school=None):
    user = CustomUser.objects.create_user(username, f'{username}@example.com', 'pass1234')
    role, _ = Role.objects.get_or_create(
        name=Role.STUDENT, defaults={'display_name': 'Student'})
    UserRole.objects.get_or_create(user=user, role=role)
    if school:
        SchoolStudent.objects.create(student=user, school=school, is_active=True)
    client.login(username=username, password='pass1234')
    return user


def served_ids(client, prefix):
    return {q['id'] for key, val in client.session.items()
            if key.startswith(prefix) for q in val['questions']}


def topic_url(bank):
    return reverse('topic_quiz', kwargs={'subject': 'mathematics',
                                         'level_number': 4,
                                         'topic_id': bank['patterns'].id})


@pytest.mark.parametrize('school_key', [None, 'mhm', 'rival'])
def test_topic_quiz_serves_the_global_bank_to_every_student(bank, client, school_key):
    student(client, f'topic_{school_key}', bank[school_key] if school_key else None)

    assert client.get(topic_url(bank)).status_code == 200

    assert served_ids(client, 'tq_') == bank['global_ids']


def test_topic_quiz_with_no_global_questions_says_so(bank, client):
    """A topic that is all school-private is empty for the quiz — and must say
    that, not quietly serve someone else's questions."""
    Question.objects.filter(school__isnull=True).delete()
    student(client, 'topic_empty', bank['mhm'])

    resp = client.get(topic_url(bank), follow=True)

    assert served_ids(client, 'tq_') == set()
    assert any('No questions available' in str(m) for m in resp.context['messages'])


def test_mixed_quiz_serves_the_global_bank_only(bank, client):
    student(client, 'mixed_kid', bank['mhm'])

    url = reverse('mixed_quiz', kwargs={'subject': 'mathematics', 'level_number': 4})
    resp = client.get(url)
    assert resp.status_code == 200

    served = {q.id for q in resp.context['questions']}
    assert served == bank['global_ids']


def test_home_topic_tile_follows_the_quiz(bank, client):
    """A topic with only school-private questions must not link into a quiz
    that will turn the student straight back."""
    bank['q']('mhm only', topic=bank['other'], school=bank['mhm'])
    Question.objects.filter(school__isnull=True, topic=bank['other']).delete()
    student(client, 'home_kid', bank['mhm'])

    resp = client.get(reverse('home'))
    assert resp.status_code == 200

    tiles = {entry['topic_id']: entry['has_questions']
             for year in resp.context['year_data']
             for group in year['strand_data']
             for entry in group['subtopics']}
    assert tiles[bank['patterns'].id] is True     # has global questions
    assert tiles[bank['other'].id] is False       # school-private only
