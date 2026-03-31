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
    '/maths/',
    '/basic-facts/',
    '/times-tables/',
    '/level/',          # topic quiz, mixed quiz, times-tables quiz
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
        # Look up the maths Subject id for the progress filter link
        maths_subject_id = None
        try:
            maths_subject_id = Subject.objects.filter(
                slug='mathematics', school__isnull=True,
            ).values_list('id', flat=True).first()
        except Exception:
            pass
        return {
            'subject_sidebar': 'maths',
            'current_subject_slug': 'mathematics',
            'current_subject_id': maths_subject_id,
        }

    # ── Future subjects ──
    # if path.startswith('/coding/'):
    #     return {'subject_sidebar': 'coding', ...}

    return {}


# ── Breadcrumb mapping ──────────────────────────────────────────────
_BREADCRUMB_MAP = [
    # (path_prefix, [(label, url), ...])  — last item has no url (current page)
    ('/maths/basic-facts/',     [('Hub', '/hub/'), ('Maths', '/maths/'), ('Basic Facts', None)]),
    ('/maths/times-tables/',    [('Hub', '/hub/'), ('Maths', '/maths/'), ('Times Tables', None)]),
    ('/maths/dashboard/',       [('Hub', '/hub/'), ('Maths', '/maths/'), ('Topics', None)]),
    ('/maths/',                 [('Hub', '/hub/'), ('Maths', None)]),
    ('/basic-facts/',           [('Hub', '/hub/'), ('Maths', '/maths/'), ('Basic Facts', None)]),
    ('/times-tables/',          [('Hub', '/hub/'), ('Maths', '/maths/'), ('Times Tables', None)]),
    ('/level/',                 [('Hub', '/hub/'), ('Maths', '/maths/'), ('Quiz', None)]),
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
