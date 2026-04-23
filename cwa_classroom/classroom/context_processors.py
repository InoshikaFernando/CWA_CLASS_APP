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


# Legacy mapping: plugin slug → ``subject_sidebar`` template variable value.
# The sidebar templates still dispatch on the old ``'maths'`` / ``'coding'``
# string; plugins own the slug (``'mathematics'`` / ``'coding'``) but that
# doesn't match 1:1 — keep this tiny remap until the sidebar templates
# themselves are generalised.
_PLUGIN_SLUG_TO_SIDEBAR_KEY = {
    'mathematics': 'maths',
    'coding': 'coding',
}

# Subjects that have a global ``classroom.Subject`` row but don't yet ship a
# SubjectPlugin (music, science). We still expose ``subject_sidebar=<slug>``
# for them so the per-subject landing pages work — without needing each one
# to implement a full plugin first.
_LEGACY_NON_PLUGIN_PREFIXES = ('/music/', '/science/')


def subject_sidebar_context(request):
    """
    Set ``subject_sidebar`` so base.html picks the correct sidebar partial.

    Phase 3 drives this from the SubjectPlugin registry: each plugin
    declares its ``url_prefixes``, and this processor dispatches to the
    first plugin that matches ``request.path``. Legacy non-plugin subjects
    (music, science) fall through to a minimal lookup that keeps the old
    behaviour intact.
    """
    from .subject_registry import plugin_for_path

    path = request.path

    plugin = plugin_for_path(path)
    if plugin is not None:
        sidebar_key = _PLUGIN_SLUG_TO_SIDEBAR_KEY.get(plugin.slug, plugin.slug)
        try:
            has_content = plugin.has_content()
        except Exception:
            has_content = False
        return {
            'subject_sidebar': sidebar_key,
            'subject_has_quizzes': has_content,
            'current_subject_slug': plugin.slug,
            'current_subject_id': plugin.classroom_subject_id(),
        }

    # ── Legacy: music / science still use a global Subject row + maths
    # Question table for their questions but have no plugin yet. Kept here
    # rather than forcing a half-empty plugin per subject.
    for prefix in _LEGACY_NON_PLUGIN_PREFIXES:
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
    ('/coding/python/problems/',      [('Hub', '/hub/'), ('Coding', '/coding/'), ('Python', '/coding/python/'), ('Challenges', None)]),
    ('/coding/javascript/problems/',  [('Hub', '/hub/'), ('Coding', '/coding/'), ('JavaScript', '/coding/javascript/'), ('Challenges', None)]),
    ('/coding/html/problems/',        [('Hub', '/hub/'), ('Coding', '/coding/'), ('HTML', '/coding/html/'), ('Challenges', None)]),
    ('/coding/css/problems/',         [('Hub', '/hub/'), ('Coding', '/coding/'), ('CSS', '/coding/css/'), ('Challenges', None)]),
    ('/coding/python/',         [('Hub', '/hub/'), ('Coding', '/coding/'), ('Python', None)]),
    ('/coding/javascript/',     [('Hub', '/hub/'), ('Coding', '/coding/'), ('JavaScript', None)]),
    ('/coding/html/',           [('Hub', '/hub/'), ('Coding', '/coding/'), ('HTML', None)]),
    ('/coding/css/',            [('Hub', '/hub/'), ('Coding', '/coding/'), ('CSS', None)]),
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
