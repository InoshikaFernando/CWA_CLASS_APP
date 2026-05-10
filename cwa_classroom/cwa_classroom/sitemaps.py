from django.contrib.sitemaps import Sitemap
from django.urls import reverse


class StaticViewSitemap(Sitemap):
    """Public pages — no authentication required."""

    # (url_name, kwargs, priority, changefreq)
    _pages = [
        # ── Core public pages ────────────────────────────────────────────
        ("public_home",                 {}, 1.0, "weekly"),
        ("contact",                     {}, 0.7, "monthly"),
        ("join_class",                  {}, 0.8, "monthly"),
        ("privacy_policy",              {}, 0.5, "monthly"),
        ("terms_conditions",            {}, 0.5, "monthly"),

        # ── Authentication ───────────────────────────────────────────────
        ("login",                       {}, 0.8, "monthly"),
        ("password_reset",              {}, 0.6, "monthly"),

        # ── Registration / sign-up ───────────────────────────────────────
        ("register_teacher_center",     {}, 0.9, "monthly"),
        ("register_individual_student", {}, 0.9, "monthly"),
        ("register_school_student",     {}, 0.8, "monthly"),
        ("register_parent_join",        {}, 0.7, "monthly"),

        # ── Subject landing pages (coming-soon stubs) ────────────────────
        ("music:coming_soon",           {}, 0.6, "monthly"),
        ("science:coming_soon",         {}, 0.6, "monthly"),
    ]

    def items(self):
        return self._pages

    def location(self, item):
        name, kwargs, *_ = item
        return reverse(name, kwargs=kwargs)

    def priority(self, item):
        return item[2]

    def changefreq(self, item):
        return item[3]


class AuthenticatedViewSitemap(Sitemap):
    """
    Authenticated pages — require a logged-in student account.
    Search engines that follow these will be redirected to /accounts/login/,
    but the URLs are included for completeness and internal link-checking.
    """

    _pages = [
        # ── Student hub / dashboard ──────────────────────────────────────
        ("subjects_hub",       {}, 0.9, "weekly"),
        ("subjects_list",      {}, 0.8, "weekly"),
        ("home",               {}, 0.9, "weekly"),
        ("student_dashboard",  {}, 0.8, "weekly"),

        # ── Maths ────────────────────────────────────────────────────────
        ("maths:dashboard",    {}, 0.9, "weekly"),

        # ── Quiz / practice ──────────────────────────────────────────────
        ("basic_facts_home",   {}, 0.8, "weekly"),
        ("times_tables_home",  {}, 0.8, "weekly"),
        ("number_puzzles_home", {}, 0.8, "weekly"),

        # ── Account ──────────────────────────────────────────────────────
        ("profile",            {}, 0.6, "monthly"),
    ]

    def items(self):
        return self._pages

    def location(self, item):
        name, kwargs, *_ = item
        return reverse(name, kwargs=kwargs)

    def priority(self, item):
        return item[2]

    def changefreq(self, item):
        return item[3]
