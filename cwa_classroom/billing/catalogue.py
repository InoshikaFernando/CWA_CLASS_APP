"""What each module costs — the price side of the module registry.

``billing/registry.py`` answers *what a module owns and where it is enforced*.
This answers *what it costs*, and the two are deliberately separate files: a
price is a commercial decision that changes without any code moving, while a
route map changes only when code does.

They are held together by :func:`billing.tests_module_catalogue`, which fails
the build if a module is enforceable but unsellable — the failure mode that
already happened once. Six modules shipped in ``MODULE_CHOICES`` with no
``ModuleProduct`` row at all, so they could be gated and audited but never
priced, never shown at checkout, and never synced to Stripe. Nothing errored;
they were simply absent from the catalogue.

This is the *seed* catalogue, not the live one. ``ModuleProduct`` rows are the
truth once they exist — every writer here uses ``get_or_create``, so a price
changed in the admin is never reverted by a deploy. Editing a number in this
file changes what a *new* environment starts with, nothing more.
"""

from decimal import Decimal


#: Seed values per module slug. Keys must match
#: ``ModuleSubscription.MODULE_CHOICES`` and ``registry.REGISTRY`` exactly.
#:
#: ``pages_per_month``     — AI import allowance. None = not applicable, 0 = unlimited.
#: ``questions_per_month`` — AI grading allowance. None = unlimited.
MODULE_CATALOGUE: dict[str, dict] = {
    # --- Originally seeded in migrations 0014 / 0019 / 0029 / 0031 -------
    # Repeated here so this file is a complete catalogue rather than a list
    # of leftovers. get_or_create means these never overwrite live prices.
    'teachers_attendance': {
        'name': 'Teachers Attendance', 'price': Decimal('10.00'),
    },
    'students_attendance': {
        'name': 'Students Attendance', 'price': Decimal('10.00'),
    },
    'student_progress_reports': {
        'name': 'Student Progress Reports', 'price': Decimal('10.00'),
    },
    'ai_import_starter': {
        'name': 'AI Question Import - Starter', 'price': Decimal('30.00'),
        'pages_per_month': 300,
    },
    'ai_import_professional': {
        'name': 'AI Question Import - Professional', 'price': Decimal('60.00'),
        'pages_per_month': 600,
    },
    'ai_import_enterprise': {
        'name': 'AI Question Import - Enterprise', 'price': Decimal('99.00'),
        'pages_per_month': 1000,
    },
    'ai_grading_starter': {
        'name': 'AI Grading - Starter', 'price': Decimal('15.00'),
        'questions_per_month': 1000,
    },
    'ai_grading_professional': {
        'name': 'AI Grading - Professional', 'price': Decimal('49.00'),
        'questions_per_month': 5000,
    },
    'ai_grading_enterprise': {
        'name': 'AI Grading - Enterprise', 'price': Decimal('149.00'),
        'questions_per_month': None,
    },

    # --- The five that had no ModuleProduct row at all -------------------
    # Priced at the $10 the other per-feature add-ons use. These are seed
    # defaults, not a pricing decision: change them here before a new
    # environment is built, or in the admin at any time after.
    'report_automation': {
        'name': 'Student Report Automation', 'price': Decimal('10.00'),
    },
    # Tiered on schedules running at once. 15 covers a Basic plan's 5 classes
    # across three subjects; 75 covers Silver's 15 classes across five, or Gold
    # at one or two. A schedule is per (class, subject), so a school's true
    # count is classes x subjects, not classes.
    'question_automation_starter': {
        'name': 'Question Automation - Starter', 'price': Decimal('10.00'),
        'schedules_limit': 15,
    },
    'question_automation_professional': {
        'name': 'Question Automation - Professional', 'price': Decimal('25.00'),
        'schedules_limit': 75,
    },
    'question_automation_unlimited': {
        'name': 'Question Automation - Unlimited', 'price': Decimal('60.00'),
        'schedules_limit': None,
    },
    'brainbuzz': {
        'name': 'BrainBuzz Live Quiz', 'price': Decimal('10.00'),
    },
    'worksheets': {
        'name': 'Worksheets', 'price': Decimal('10.00'),
    },
    'whatsapp_notifications': {
        'name': 'WhatsApp Parent Notifications', 'price': Decimal('10.00'),
    },
    'invoicing': {
        'name': 'Student Invoicing', 'price': Decimal('10.00'),
    },
}


def defaults_for(slug: str) -> dict | None:
    """Seed values for *slug*, or None if it is not in the catalogue."""
    entry = MODULE_CATALOGUE.get(slug)
    return dict(entry) if entry else None


def slugs() -> frozenset:
    return frozenset(MODULE_CATALOGUE)
