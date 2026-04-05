"""Playwright UI tests for CPP-151: Multi-School Subject Display & Shared Progress.

Setup:
  - Two schools: school_alpha and school_beta
  - One global subject (mathematics) with 3 global questions
  - school_alpha has a local subject (local_alpha, global_subject=global_subj) with 2 local questions
  - school_beta has a local subject (local_beta, global_subject=global_subj) with 2 local questions
  - One student (dual_student) enrolled in BOTH schools via SchoolStudent
  - No class enrollment — subjects should still be visible (CPP-151 display rule)

UI scenarios verified:
  1. Hub loads and shows two named school sections.
  2. Each school section contains its local subject card.
  3. Subject cards are rendered (even without class enrollment).
  4. Progress bar appears when questions exist.
  5. Answering a global question → both school sections reflect the completed count.
  6. Global completed count does NOT double (remains 1, not 2).
  7. Answering a local-alpha question → only school_alpha card shows the increase;
     school_beta card remains unchanged.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import Page, expect

from .conftest import TEST_PASSWORD, _RUN_ID, _assign_role, _get_or_create_role


# ===========================================================================
# Fixtures — entirely self-contained; do not rely on conftest school/subject
# ===========================================================================

@pytest.fixture
def hub_admin(db):
    """Superuser for creating school hierarchies."""
    from accounts.models import CustomUser

    u = CustomUser.objects.create_superuser(
        username=f'hub_ms_admin_{_RUN_ID}',
        password=TEST_PASSWORD,
        email=f'hub_ms_admin_{_RUN_ID}@test.local',
        profile_completed=True,
        must_change_password=False,
    )
    yield u
    u.delete()


@pytest.fixture
def global_subject(db):
    """A global Mathematics subject (school=None)."""
    from classroom.models import Subject

    subj, _ = Subject.objects.get_or_create(
        slug=f'hub-ms-global-{_RUN_ID}',
        defaults={'name': f'Hub MS Mathematics {_RUN_ID}', 'is_active': True, 'school': None},
    )
    yield subj
    subj.delete()


@pytest.fixture
def school_alpha(db, hub_admin):
    """First school with an active subscription."""
    from billing.models import InstitutePlan, ModuleSubscription, SchoolSubscription
    from classroom.models import School

    school = School.objects.create(
        name=f'Alpha School {_RUN_ID}',
        slug=f'alpha-school-{_RUN_ID}',
        admin=hub_admin,
        is_active=True,
    )
    plan, _ = InstitutePlan.objects.get_or_create(
        slug=f'ms-plan-alpha-{_RUN_ID}',
        defaults={
            'name': f'Plan Alpha {_RUN_ID}',
            'price': 0,
            'stripe_price_id': 'price_test_ms_alpha',
            'class_limit': 50,
            'student_limit': 500,
            'invoice_limit_yearly': 500,
            'extra_invoice_rate': 0,
        },
    )
    sub = SchoolSubscription.objects.create(school=school, plan=plan, status='active')
    for module_key, _ in ModuleSubscription.MODULE_CHOICES:
        ModuleSubscription.objects.create(
            school_subscription=sub, module=module_key, is_active=True,
        )
    yield school
    school.delete()
    plan.delete()


@pytest.fixture
def school_beta(db, hub_admin):
    """Second school with an active subscription."""
    from billing.models import InstitutePlan, ModuleSubscription, SchoolSubscription
    from classroom.models import School

    school = School.objects.create(
        name=f'Beta School {_RUN_ID}',
        slug=f'beta-school-{_RUN_ID}',
        admin=hub_admin,
        is_active=True,
    )
    plan, _ = InstitutePlan.objects.get_or_create(
        slug=f'ms-plan-beta-{_RUN_ID}',
        defaults={
            'name': f'Plan Beta {_RUN_ID}',
            'price': 0,
            'stripe_price_id': 'price_test_ms_beta',
            'class_limit': 50,
            'student_limit': 500,
            'invoice_limit_yearly': 500,
            'extra_invoice_rate': 0,
        },
    )
    sub = SchoolSubscription.objects.create(school=school, plan=plan, status='active')
    for module_key, _ in ModuleSubscription.MODULE_CHOICES:
        ModuleSubscription.objects.create(
            school_subscription=sub, module=module_key, is_active=True,
        )
    yield school
    school.delete()
    plan.delete()


@pytest.fixture
def local_subject_alpha(db, school_alpha, global_subject):
    """Local subject for school_alpha, derived from global_subject."""
    from classroom.models import Subject

    subj = Subject.objects.create(
        name=f'Alpha Maths {_RUN_ID}',
        slug=f'alpha-maths-{_RUN_ID}',
        school=school_alpha,
        is_active=True,
        global_subject=global_subject,
    )
    yield subj
    subj.delete()


@pytest.fixture
def local_subject_beta(db, school_beta, global_subject):
    """Local subject for school_beta, derived from global_subject."""
    from classroom.models import Subject

    subj = Subject.objects.create(
        name=f'Beta Maths {_RUN_ID}',
        slug=f'beta-maths-{_RUN_ID}',
        school=school_beta,
        is_active=True,
        global_subject=global_subject,
    )
    yield subj
    subj.delete()


@pytest.fixture
def dept_alpha(db, school_alpha, local_subject_alpha, hub_admin):
    """Department for school_alpha with local_subject_alpha."""
    from classroom.models import Department, DepartmentSubject

    dept = Department.objects.create(
        school=school_alpha,
        name=f'Alpha Dept {_RUN_ID}',
        slug=f'alpha-dept-{_RUN_ID}',
        head=hub_admin,
    )
    DepartmentSubject.objects.create(department=dept, subject=local_subject_alpha)
    yield dept
    dept.delete()


@pytest.fixture
def dept_beta(db, school_beta, local_subject_beta, hub_admin):
    """Department for school_beta with local_subject_beta."""
    from classroom.models import Department, DepartmentSubject

    dept = Department.objects.create(
        school=school_beta,
        name=f'Beta Dept {_RUN_ID}',
        slug=f'beta-dept-{_RUN_ID}',
        head=hub_admin,
    )
    DepartmentSubject.objects.create(department=dept, subject=local_subject_beta)
    yield dept
    dept.delete()


@pytest.fixture
def global_level(db, global_subject):
    """A Level linked to global_subject (uses high number to avoid clashes)."""
    from classroom.models import Level

    lvl, created = Level.objects.get_or_create(
        level_number=975,
        defaults={'display_name': 'Hub MS Level 975', 'subject': global_subject},
    )
    if lvl.subject_id != global_subject.id:
        Level.objects.filter(pk=lvl.pk).update(subject=global_subject)
        lvl.refresh_from_db()
    yield lvl
    if created:
        lvl.delete()


@pytest.fixture
def local_level_alpha(db, local_subject_alpha):
    """A Level linked to local_subject_alpha."""
    from classroom.models import Level

    lvl, created = Level.objects.get_or_create(
        level_number=974,
        defaults={'display_name': 'Hub MS Level 974', 'subject': local_subject_alpha},
    )
    if lvl.subject_id != local_subject_alpha.id:
        Level.objects.filter(pk=lvl.pk).update(subject=local_subject_alpha)
        lvl.refresh_from_db()
    yield lvl
    if created:
        lvl.delete()


@pytest.fixture
def local_level_beta(db, local_subject_beta):
    """A Level linked to local_subject_beta."""
    from classroom.models import Level

    lvl, created = Level.objects.get_or_create(
        level_number=973,
        defaults={'display_name': 'Hub MS Level 973', 'subject': local_subject_beta},
    )
    if lvl.subject_id != local_subject_beta.id:
        Level.objects.filter(pk=lvl.pk).update(subject=local_subject_beta)
        lvl.refresh_from_db()
    yield lvl
    if created:
        lvl.delete()


def _make_question(level, school, text):
    from maths.models import Answer, Question

    q = Question.objects.create(
        level=level, school=school,
        question_text=text,
        question_type='multiple_choice',
        difficulty=1, points=1,
    )
    Answer.objects.create(question=q, answer_text='Yes', is_correct=True, order=1)
    Answer.objects.create(question=q, answer_text='No', is_correct=False, order=2)
    return q


@pytest.fixture
def global_questions(db, global_level):
    """3 global questions (school=None) linked to global_level."""
    qs = [
        _make_question(global_level, school=None, text=f'Global Q{i} {_RUN_ID}')
        for i in range(3)
    ]
    yield qs
    from maths.models import Question
    Question.objects.filter(id__in=[q.id for q in qs]).delete()


@pytest.fixture
def local_questions_alpha(db, local_level_alpha, school_alpha):
    """2 local questions for school_alpha."""
    qs = [
        _make_question(local_level_alpha, school=school_alpha, text=f'Alpha Q{i} {_RUN_ID}')
        for i in range(2)
    ]
    yield qs
    from maths.models import Question
    Question.objects.filter(id__in=[q.id for q in qs]).delete()


@pytest.fixture
def local_questions_beta(db, local_level_beta, school_beta):
    """2 local questions for school_beta."""
    qs = [
        _make_question(local_level_beta, school=school_beta, text=f'Beta Q{i} {_RUN_ID}')
        for i in range(2)
    ]
    yield qs
    from maths.models import Question
    Question.objects.filter(id__in=[q.id for q in qs]).delete()


@pytest.fixture
def dual_student(
    db,
    school_alpha, school_beta,
    dept_alpha, dept_beta,
    local_subject_alpha, local_subject_beta,
):
    """A STUDENT enrolled in both school_alpha and school_beta.

    No ClassStudent rows — subjects must still be visible (CPP-151 rule).
    """
    from accounts.models import CustomUser, Role
    from classroom.models import SchoolStudent

    user = CustomUser.objects.create_user(
        username=f'dual_student_{_RUN_ID}',
        password=TEST_PASSWORD,
        email=f'dual_student_{_RUN_ID}@test.local',
        first_name='Dual',
        profile_completed=True,
        must_change_password=False,
    )
    _assign_role(user, Role.STUDENT)
    SchoolStudent.objects.create(school=school_alpha, student=user)
    SchoolStudent.objects.create(school=school_beta, student=user)
    yield user
    user.delete()


def _create_answer(student, question, is_correct):
    from maths.models import StudentAnswer

    return StudentAnswer.objects.create(
        student=student,
        question=question,
        is_correct=is_correct,
        points_earned=question.points if is_correct else 0,
        attempt_id=uuid.uuid4(),
    )


# ===========================================================================
# Tests
# ===========================================================================

class TestHubMultiSchoolDisplay:
    """Verify the hub layout for a student enrolled in two schools."""

    @pytest.mark.django_db(transaction=True)
    def test_hub_loads_for_dual_enrolled_student(
        self, page: Page, live_server, dual_student,
        global_questions, local_questions_alpha, local_questions_beta,
    ):
        """Hub page returns 200 and contains the student's first name."""
        from .conftest import do_login
        do_login(page, live_server.url, dual_student)
        page.goto(f'{live_server.url}/hub/')
        page.wait_for_load_state('networkidle')
        # The hub greeting heading (h1) contains "Dual" — confirm hub loaded
        expect(page.locator('h1', has_text='Dual').first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_hub_shows_school_alpha_section(
        self, page: Page, live_server, dual_student,
        school_alpha, local_subject_alpha,
        global_questions, local_questions_alpha, local_questions_beta,
    ):
        """Hub page contains a heading or section label with school_alpha's name."""
        from .conftest import do_login
        do_login(page, live_server.url, dual_student)
        page.goto(f'{live_server.url}/hub/')
        page.wait_for_load_state('networkidle')
        expect(page.get_by_text(school_alpha.name, exact=False).first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_hub_shows_school_beta_section(
        self, page: Page, live_server, dual_student,
        school_beta, local_subject_beta,
        global_questions, local_questions_alpha, local_questions_beta,
    ):
        """Hub page contains a heading or section label with school_beta's name."""
        from .conftest import do_login
        do_login(page, live_server.url, dual_student)
        page.goto(f'{live_server.url}/hub/')
        page.wait_for_load_state('networkidle')
        expect(page.get_by_text(school_beta.name, exact=False).first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_hub_shows_local_alpha_subject_card(
        self, page: Page, live_server, dual_student,
        local_subject_alpha,
        global_questions, local_questions_alpha, local_questions_beta,
    ):
        """local_subject_alpha's name is visible on the hub under school_alpha."""
        from .conftest import do_login
        do_login(page, live_server.url, dual_student)
        page.goto(f'{live_server.url}/hub/')
        page.wait_for_load_state('networkidle')
        expect(page.get_by_text(local_subject_alpha.name, exact=False).first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_hub_shows_local_beta_subject_card(
        self, page: Page, live_server, dual_student,
        local_subject_beta,
        global_questions, local_questions_alpha, local_questions_beta,
    ):
        """local_subject_beta's name is visible on the hub under school_beta."""
        from .conftest import do_login
        do_login(page, live_server.url, dual_student)
        page.goto(f'{live_server.url}/hub/')
        page.wait_for_load_state('networkidle')
        expect(page.get_by_text(local_subject_beta.name, exact=False).first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_hub_shows_progress_bar_on_alpha_card(
        self, page: Page, live_server, dual_student,
        local_subject_alpha,
        global_questions, local_questions_alpha, local_questions_beta,
    ):
        """Progress bar (question count label) is rendered on school_alpha subject card.

        The template renders '0/5 questions' when no answers exist yet (3 global + 2 local).
        """
        from .conftest import do_login
        do_login(page, live_server.url, dual_student)
        page.goto(f'{live_server.url}/hub/')
        page.wait_for_load_state('networkidle')
        # Template renders "X/Y questions"
        expect(page.get_by_text('0/5 questions', exact=False).first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_subjects_shown_without_class_enrollment(
        self, page: Page, live_server, dual_student,
        local_subject_alpha, local_subject_beta,
        global_questions, local_questions_alpha, local_questions_beta,
    ):
        """Both local subjects are visible even though dual_student has no ClassStudent rows.

        CPP-151 requirement: subjects appear in school cards regardless of class enrollment.
        """
        from .conftest import do_login
        do_login(page, live_server.url, dual_student)
        page.goto(f'{live_server.url}/hub/')
        page.wait_for_load_state('networkidle')
        expect(page.get_by_text(local_subject_alpha.name, exact=False).first).to_be_visible()
        expect(page.get_by_text(local_subject_beta.name, exact=False).first).to_be_visible()


class TestHubSharedGlobalProgress:
    """Verify that global question answers appear in both schools' progress."""

    @pytest.mark.django_db(transaction=True)
    def test_global_answer_reflected_in_alpha_progress(
        self, page: Page, live_server, dual_student,
        global_questions, local_questions_alpha, local_questions_beta,
    ):
        """After answering 1 global question, school_alpha card shows '1/5 questions'."""
        from .conftest import do_login

        # Pre-seed: student answered global_questions[0] correctly
        _create_answer(dual_student, global_questions[0], is_correct=True)

        do_login(page, live_server.url, dual_student)
        page.goto(f'{live_server.url}/hub/')
        page.wait_for_load_state('networkidle')

        # Template renders "1/5 questions" on the school_alpha card
        expect(page.get_by_text('1/5 questions', exact=False).first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_global_answer_reflected_in_beta_progress(
        self, page: Page, live_server, dual_student,
        global_questions, local_questions_alpha, local_questions_beta,
    ):
        """After answering 1 global question, school_beta card also shows '1/5 questions'.

        This is the core CPP-151 shared-progress guarantee: the same answer
        counts for both local subjects.
        """
        from .conftest import do_login

        _create_answer(dual_student, global_questions[0], is_correct=True)

        do_login(page, live_server.url, dual_student)
        page.goto(f'{live_server.url}/hub/')
        page.wait_for_load_state('networkidle')

        # Both school cards show "1/5 questions"
        all_count_labels = page.get_by_text('1/5 questions', exact=False)
        assert all_count_labels.count() >= 2, (
            f"Expected '1/5 questions' on at least 2 cards (alpha & beta), "
            f"found {all_count_labels.count()}"
        )

    @pytest.mark.django_db(transaction=True)
    def test_global_answer_not_doubled_pct(
        self, page: Page, live_server, dual_student,
        global_questions, local_questions_alpha, local_questions_beta,
    ):
        """Answering 1 global question shows 20% (1/5), not 40% (doubled).

        CPP-151 invariant: a global answer is stored once, reflected in both
        schools, but the student's actual completion score is not inflated.
        """
        from .conftest import do_login

        _create_answer(dual_student, global_questions[0], is_correct=True)

        do_login(page, live_server.url, dual_student)
        page.goto(f'{live_server.url}/hub/')
        page.wait_for_load_state('networkidle')

        # 20% should appear; 40% should NOT appear
        expect(page.get_by_text('20%', exact=False).first).to_be_visible()
        expect(page.get_by_text('40%')).to_have_count(0)


class TestHubScopedLocalProgress:
    """Verify that local question answers are scoped to their own school."""

    @pytest.mark.django_db(transaction=True)
    def test_local_alpha_answer_shown_in_alpha_card(
        self, page: Page, live_server, dual_student,
        local_subject_alpha,
        global_questions, local_questions_alpha, local_questions_beta,
    ):
        """Answering a local-alpha question bumps school_alpha card to '1/5 questions'."""
        from .conftest import do_login

        _create_answer(dual_student, local_questions_alpha[0], is_correct=True)

        do_login(page, live_server.url, dual_student)
        page.goto(f'{live_server.url}/hub/')
        page.wait_for_load_state('networkidle')

        # school_alpha card: 1/5 questions completed
        expect(page.get_by_text('1/5 questions', exact=False).first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_local_alpha_answer_not_shown_in_beta_card(
        self, page: Page, live_server, dual_student,
        local_subject_beta,
        global_questions, local_questions_alpha, local_questions_beta,
    ):
        """Answering a local-alpha question does NOT change school_beta progress.

        school_beta card should still show '0/5 questions'.
        CPP-151 invariant: local questions are scoped to one school only.
        """
        from .conftest import do_login

        _create_answer(dual_student, local_questions_alpha[0], is_correct=True)

        do_login(page, live_server.url, dual_student)
        page.goto(f'{live_server.url}/hub/')
        page.wait_for_load_state('networkidle')

        # school_beta card must still say "0/5"
        expect(page.get_by_text('0/5 questions', exact=False).first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_all_local_alpha_answered_shows_correct_pct(
        self, page: Page, live_server, dual_student,
        global_questions, local_questions_alpha, local_questions_beta,
    ):
        """Answering all 2 local-alpha questions → school_alpha card shows 40% (2/5)."""
        from .conftest import do_login

        for q in local_questions_alpha:
            _create_answer(dual_student, q, is_correct=True)

        do_login(page, live_server.url, dual_student)
        page.goto(f'{live_server.url}/hub/')
        page.wait_for_load_state('networkidle')

        # 2/5 = 40%
        expect(page.get_by_text('2/5 questions', exact=False).first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_full_alpha_completion_100_pct(
        self, page: Page, live_server, dual_student,
        global_questions, local_questions_alpha, local_questions_beta,
    ):
        """Answering all 5 questions (3 global + 2 local-alpha) → alpha card 100%."""
        from .conftest import do_login

        for q in global_questions + local_questions_alpha:
            _create_answer(dual_student, q, is_correct=True)

        do_login(page, live_server.url, dual_student)
        page.goto(f'{live_server.url}/hub/')
        page.wait_for_load_state('networkidle')

        expect(page.get_by_text('100%', exact=False).first).to_be_visible()
        expect(page.get_by_text('5/5 questions', exact=False).first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_local_beta_answer_not_shown_in_alpha_card(
        self, page: Page, live_server, dual_student,
        global_questions, local_questions_alpha, local_questions_beta,
    ):
        """Answering a local-beta question does NOT change school_alpha progress."""
        from .conftest import do_login

        _create_answer(dual_student, local_questions_beta[0], is_correct=True)

        do_login(page, live_server.url, dual_student)
        page.goto(f'{live_server.url}/hub/')
        page.wait_for_load_state('networkidle')

        # school_alpha card: 0/5 (local_beta answer is invisible to school_alpha)
        # school_beta card: 1/5
        # At least one card must show "0/5 questions"
        expect(page.get_by_text('0/5 questions', exact=False).first).to_be_visible()
