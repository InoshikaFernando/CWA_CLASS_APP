"""What each module owns, declared in one place.

Until now "which feature is paid for" was answered by whether somebody
remembered to write ``required_module`` on a view. That is opt-in, so it fails
open: a new view, a new app, or a capability rebuilt in a different module
ships free, and nothing anywhere reports it. Two real examples, both found by
reading the resolved URL table rather than the code:

* the CPP-388 progress-report rebuild, readable by any school on any plan;
* seven absence-token routes served out of ``attendance/`` — an app that is
  not in ``INSTALLED_APPS``, whose view modules ``classroom/urls.py`` imports
  directly, so it was invisible to every check that looked at settings.

This registry inverts that. It states, per module, the routes and API
basenames it owns, and states the base product explicitly. Anything that
matches neither is a build failure (``tests_module_registry.py``), so a new
route has to make an entitlement decision to merge at all.

Two rules keep this from becoming a second, drifting copy of the truth:

1. **The view marker wins.** ``required_module`` on a view class is read
   first, so the 48 views that already declare one are not re-listed here and
   cannot disagree with this file.
2. **Only what a marker cannot reach is declared here** — function-based
   views, DRF viewsets, and whole namespaces.

``enforcement`` records where a module can actually be enforced, which is not
a detail: two of them have no request to hang a gate off at all.
"""

from dataclasses import dataclass

# How a module is enforced. A module is not "route" just because it has pages.
ROUTE = 'route'      # a URL the middleware/mixin sees
API = 'api'          # a DRF viewset, gated by permission or queryset filter
SERVICE = 'service'  # no request exists — cron, signal or service call

# Who can buy it.
INSTITUTE = 'institute'
INDIVIDUAL = 'individual'
BOTH = 'both'


@dataclass(frozen=True)
class Module:
    slug: str
    name: str
    audience: str = INSTITUTE
    enforcement: tuple = (ROUTE,)
    #: URL namespaces owned outright (``brainbuzz:*``).
    namespaces: tuple = ()
    #: Exact url names, un-namespaced.
    route_names: tuple = ()
    #: Url-name prefixes, un-namespaced.
    route_prefixes: tuple = ()
    #: DRF router basenames, as registered in ``api/urls.py``.
    api_basenames: tuple = ()
    #: Free-text note for the module the sales page will need.
    note: str = ''


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------
# Slugs must match billing.ModuleSubscription.MODULE_CHOICES exactly; a test
# holds the two together, so a module you can buy but cannot enforce — or
# enforce but cannot buy — fails the build.

REGISTRY: dict[str, Module] = {}


def _add(module: Module) -> Module:
    REGISTRY[module.slug] = module
    return module


_add(Module(
    slug='students_attendance',
    name='Students Attendance',
    audience=INSTITUTE,
    enforcement=(ROUTE, API),
    route_prefixes=(
        'attendance_', 'class_attendance', 'session_attendance',
        'student_attendance_', 'student_mark_attendance', 'student_absence_',
        'student_available_makeup_sessions', 'student_redeem_absence_token',
        'student_request_absence_token', 'absence_token_',
        'start_session', 'create_session', 'complete_session',
        'cancel_session', 'delete_session',
        'parent_attendance', 'hod_attendance_report',
    ),
    api_basenames=('attendance', 'session'),
))

_add(Module(
    slug='teachers_attendance',
    name='Teachers Attendance',
    audience=INSTITUTE,
    route_names=('teacher_self_attendance',),
))

_add(Module(
    slug='student_progress_reports',
    name='Student Progress Reports',
    audience=INSTITUTE,
    enforcement=(ROUTE, API),
    namespaces=('progress',),
    route_prefixes=('student_report', 'period_report', 'report_preview',
                    'report_settings'),
    api_basenames=('report',),
))

_add(Module(
    slug='report_automation',
    name='Student Report Automation',
    audience=INSTITUTE,
    # No routes of its own: it is a *mode* on a setting the reports module
    # already sells, read by the nightly generate_progress_reports command.
    # Enforced in progress.report_settings.enabled_classrooms().
    enforcement=(SERVICE,),
    note='Scheduled, unattended sending. Manual sending stays in the base reports module.',
))

_add(Module(
    slug='question_automation',
    name='Question Automation',
    audience=INSTITUTE,
    # Pages AND cron: schedule_services.due_weeks() runs with no request.
    enforcement=(ROUTE, SERVICE),
    route_prefixes=('schedule_',),
    note='Teaching plan scheduled across a term or year, built unattended.',
))

for _slug, _label, _pages in (
    ('ai_import_starter', 'AI Question Import — Starter', 300),
    ('ai_import_professional', 'AI Question Import — Professional', None),
    ('ai_import_enterprise', 'AI Question Import — Enterprise', None),
):
    _add(Module(
        slug=_slug, name=_label, audience=INSTITUTE,
        # One namespace, three tiers: whichever tier is held opens the same
        # pages, and the tier decides the monthly page quota.
        namespaces=('ai_import',),
        note='Tiered by pages/month.',
    ))

for _slug, _label in (
    ('ai_grading_starter', 'AI Grading — Starter'),
    ('ai_grading_professional', 'AI Grading — Professional'),
    ('ai_grading_enterprise', 'AI Grading — Enterprise'),
):
    _add(Module(
        slug=_slug, name=_label, audience=INSTITUTE,
        # Enforced inside worksheets.grading_service, not on a URL: grading
        # happens on submission and in background jobs.
        enforcement=(SERVICE,),
        note='Tiered by AI-graded answers/month.',
    ))


# --- Modules that exist as features today but are not yet sold -------------
# Declared so the registry is a complete map of the product and so shadow mode
# can measure who would be affected. They are only *enforced* when
# MODULE_ENFORCEMENT is switched on — see billing.middleware.

_add(Module(
    slug='brainbuzz',
    name='BrainBuzz Live Quiz',
    audience=INSTITUTE,
    namespaces=('brainbuzz',),
    note='Live in-class quiz sessions with join codes and leaderboards.',
))

_add(Module(
    slug='worksheets',
    name='Worksheets',
    audience=INSTITUTE,
    enforcement=(ROUTE, API),
    namespaces=('worksheets',),
    api_basenames=('worksheet-assignment', 'worksheet-submission'),
    note='AI grading is sold separately on top of this.',
))

_add(Module(
    slug='rewards',
    name='Rewards & Leaderboard',
    audience=BOTH,
    # No pages at all — the rewards app has no urls.py. A route-only gate
    # would have silently covered nothing.
    enforcement=(API,),
    # 'points' is the router viewset; the other two are bare APIViews mounted
    # by hand, so they carry no -list/-detail basename to match on. Found by
    # the registry guard, which is the point of it.
    api_basenames=('points',),
    route_names=('points-total', 'leaderboard'),
    note='Cross-subject points and the global leaderboard.',
))

_add(Module(
    slug='whatsapp_notifications',
    name='WhatsApp Parent Notifications',
    audience=INSTITUTE,
    # Signals and RQ tasks; there is no request anywhere in the send path.
    enforcement=(SERVICE,),
    note='Enforced at the send path in whatsapp.services.',
))


# ---------------------------------------------------------------------------
# The base product
# ---------------------------------------------------------------------------
# Everything in every plan. Stated positively, so a new app is unclassified
# (a build failure) rather than silently free.

BASE_NAMESPACES = frozenset({
    'homework',      # question_automation carves its schedule_* routes out
    'help',
    'feedback',
    'taskqueue',
    'sprints',
    'maths',         # subject content — see SUBJECT_PACKS below
    'coding',
    'music',
    'science',
})

#: Top-level view-module packages whose routes are base unless a module rule
#: above claims them. Ordered as they appear in INSTALLED_APPS.
BASE_APPS = frozenset({
    'accounts',      # auth, registration, profile
    'classroom',     # classes, enrolment, subjects, timetable
    'billing',       # plans, checkout, invoices — you must be able to pay us
    'quiz',
    'progress',      # the un-namespaced student dashboard, not the reports
    'audit',
    'usage',
    'ops',
    'api',           # auth + schema endpoints
    'number_puzzles',
    'maths',
    'coding',
    'music',
    'science',
    'homework',
    'help',
    'feedback',
    'taskqueue',
    'sprints',
    'cwa_classroom',  # health check, sitemap, static pages
    'notifications',
})

#: Apps that are wholly a paid module. Deliberately absent from BASE_APPS: a
#: route here that no module rule claims must fail the build rather than fall
#: through to "base", which is how the attendance routes stayed free.
FULLY_MODULAR_APPS = frozenset({
    'attendance', 'brainbuzz', 'worksheets', 'ai_import', 'rewards',
})

#: Subject packs are a *future* split: maths and coding are base today. Listed
#: so the intent is on the record and the change is one line, not an audit.
SUBJECT_PACKS_NOT_YET_SOLD = ('maths', 'coding')


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

def module_for_view(view_class) -> str | None:
    """The module a view declares for itself, or None.

    Read before any rule in this file so the existing ``required_module``
    markers stay the single source of truth for the views that carry one.
    """
    return getattr(view_class, 'required_module', None) if view_class else None


def module_for_route(namespace: str | None, url_name: str | None) -> str | None:
    """The module owning this route by name, or None for the base product.

    Namespace ownership loses to an explicit name rule, so a module can carve
    routes out of a base namespace — ``question_automation`` owns
    ``homework:schedule_*`` while the rest of ``homework:`` stays base.
    """
    if not url_name:
        return None

    for module in REGISTRY.values():
        if url_name in module.route_names:
            return module.slug
        if any(url_name.startswith(p) for p in module.route_prefixes):
            return module.slug

    if namespace:
        for module in REGISTRY.values():
            if namespace in module.namespaces:
                return module.slug

    return None


def module_for_api_basename(basename: str | None) -> str | None:
    """The module owning a DRF router basename, or None."""
    if not basename:
        return None
    for module in REGISTRY.values():
        if basename in module.api_basenames:
            return module.slug
    return None


def is_base(view_module: str | None, namespace: str | None) -> bool:
    """Whether an unclaimed route belongs to the declared base product."""
    if namespace and namespace in BASE_NAMESPACES:
        return True
    if view_module:
        return view_module.split('.')[0] in BASE_APPS
    return False


def slugs() -> frozenset:
    return frozenset(REGISTRY)


def enforced_by(kind: str) -> tuple:
    """Modules enforceable in a given way — ROUTE, API or SERVICE."""
    return tuple(m.slug for m in REGISTRY.values() if kind in m.enforcement)
