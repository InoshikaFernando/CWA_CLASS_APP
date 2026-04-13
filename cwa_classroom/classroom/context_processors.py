from .models import Subject, SubjectApp


def subject_apps(request):
    """
    Inject subject apps into every template context.
    Used by the public nav dropdown to show available subjects.
    Only queries the database for authenticated users (the dropdown
    is only shown post-login).
    """
    if not request.user.is_authenticated:
        return {}
    return {
        'subject_apps': SubjectApp.objects.exclude(
            is_active=False, is_coming_soon=False
        ).order_by('order'),
    }


# ── Path prefixes that belong to the Maths subject ──────────────────
_MATHS_PREFIXES = (
    '/maths/',          # maths app + quiz app (basic-facts, times-tables, topic quiz)
    '/number-puzzles/',
)


def subject_sidebar_context(request):
    """
    Set ``subject_sidebar`` so base.html picks the correct sidebar
    partial for students inside a subject.

    Values: ``'maths'`` | ``<subject-slug>`` | ``None``
    """
    path = request.path

    # ── Maths (including quiz URLs at root level) ──
    if any(path.startswith(p) for p in _MATHS_PREFIXES):
        maths_subject_id = None
        has_quizzes = False
        try:
            from maths.models import Question as MathsQuestion
            maths_subject_id = Subject.objects.filter(
                slug='mathematics', school__isnull=True,
            ).values_list('id', flat=True).first()
            has_quizzes = MathsQuestion.objects.exists()
        except Exception:
            pass
        return {
            'subject_sidebar': 'maths',
            'subject_has_quizzes': has_quizzes,
            'current_subject_slug': 'mathematics',
            'current_subject_id': maths_subject_id,
        }

    # ── Other subjects (coding, music, science, custom) ──
    for prefix in ('/coding/', '/music/', '/science/'):
        if path.startswith(prefix):
            slug = prefix.strip('/')
            subject_id = None
            has_quizzes = False
            try:
                from maths.models import Question
                subj = Subject.objects.filter(
                    slug=slug, school__isnull=True,
                ).first()
                if subj:
                    subject_id = subj.id
                    has_quizzes = Question.objects.filter(
                        topic__subject=subj,
                    ).exists()
            except Exception:
                pass
            return {
                'subject_sidebar': slug,
                'subject_has_quizzes': has_quizzes,
                'current_subject_slug': slug,
                'current_subject_id': subject_id,
            }

    return {}


# ── Breadcrumb mapping ──────────────────────────────────────────────
_BREADCRUMB_MAP = [
    # (path_prefix, [(label, url), ...])  — last item has no url (current page)
    # Maths (quiz URLs now under /maths/)
    ('/maths/basic-facts/',     [('Hub', '/hub/'), ('Maths', '/maths/'), ('Basic Facts', None)]),
    ('/maths/times-tables/',    [('Hub', '/hub/'), ('Maths', '/maths/'), ('Times Tables', None)]),
    ('/maths/level/',           [('Hub', '/hub/'), ('Maths', '/maths/'), ('Quiz', None)]),
    ('/maths/dashboard/',       [('Hub', '/hub/'), ('Maths', '/maths/'), ('Topics', None)]),
    ('/maths/',                 [('Hub', '/hub/'), ('Maths', None)]),
    # Coding
    ('/coding/api/',            []),   # no breadcrumbs for API endpoints
    ('/coding/python/problems/',   [('Hub', '/hub/'), ('Coding', '/coding/'), ('Python', '/coding/python/'), ('Challenges', None)]),
    ('/coding/javascript/problems/',[('Hub', '/hub/'), ('Coding', '/coding/'), ('JavaScript', '/coding/javascript/'), ('Challenges', None)]),
    ('/coding/html-css/problems/', [('Hub', '/hub/'), ('Coding', '/coding/'), ('HTML/CSS', '/coding/html-css/'), ('Challenges', None)]),
    ('/coding/python/',         [('Hub', '/hub/'), ('Coding', '/coding/'), ('Python', None)]),
    ('/coding/javascript/',     [('Hub', '/hub/'), ('Coding', '/coding/'), ('JavaScript', None)]),
    ('/coding/html-css/',       [('Hub', '/hub/'), ('Coding', '/coding/'), ('HTML / CSS', None)]),
    ('/coding/scratch/',        [('Hub', '/hub/'), ('Coding', '/coding/'), ('Scratch', None)]),
    ('/coding/',                [('Hub', '/hub/'), ('Coding', None)]),
    # Student pages
    ('/student/my-classes/',    [('Hub', '/hub/'), ('My Classes', None)]),
    ('/student/join/',          [('Hub', '/hub/'), ('Join Class', None)]),
    ('/student/attendance/',    [('Hub', '/hub/'), ('Attendance', None)]),
    ('/student/absence-tokens/',[('Hub', '/hub/'), ('Absence Tokens', None)]),
    ('/student/class/',         [('Hub', '/hub/'), ('My Classes', '/student/my-classes/'), ('Class', None)]),
    ('/student-dashboard/',     [('Hub', '/hub/'), ('My Progress', None)]),
    ('/billing/',               [('Hub', '/hub/'), ('Billing', None)]),
    ('/accounts/profile/',      [('Hub', '/hub/'), ('Profile', None)]),
]


def breadcrumbs_context(request):
    """
    Build breadcrumb trail from the current URL path.
    Returns ``{'breadcrumbs': [{'label': ..., 'url': ...}, ...]}``
    or empty dict for the hub (home) page.
    """
    path = request.path

    # No breadcrumbs on hub — it's home
    if path == '/hub/' or path == '/':
        return {}

    for prefix, crumbs in _BREADCRUMB_MAP:
        if path.startswith(prefix):
            return {
                'breadcrumbs': [
                    {'label': label, 'url': url}
                    for label, url in crumbs
                ],
            }

    return {}
