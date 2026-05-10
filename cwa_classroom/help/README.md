# help

In-product help centre. Admins author articles in Markdown, organised into categories. The same articles drive both the standalone help centre (`/help/`) and the contextual help panels rendered inline on specific pages — articles can be scoped by role group, by module, and by page identifier.

## Key models

- **HelpCategory** — top-level category (Getting Started, Troubleshooting, …).
- **HelpArticle** — Markdown article (title, slug, body_markdown, excerpt, category). Optional scoping by role group, module, and page-context key (e.g. `teacher_dashboard`).
- **HelpArticleRole** — M2M join controlling per-role visibility.

## URL prefix & key routes

Mounted at `/help/` (namespace `help`).

- `/help/` — help-centre home (category list)
- `/help/search/` — full-text search
- `/help/category/<slug>/` — articles in a category
- `/help/article/<slug>/` — single article
- `/help/context/` — AJAX endpoint that returns context-specific articles for inline help panels

## Integration

In `settings.py`:

```python
INSTALLED_APPS = [..., 'help', ...]

TEMPLATES[0]['OPTIONS']['context_processors'] += [
    'help.context_processors.help_context',
]
```

The context processor populates `help_articles` in every template, filtered by the current user's role and the page-context key — so any template can render an inline "Help" panel without view-side work.

In root `urls.py` — must come **before** the catch-all classroom include:

```python
path('help/', include('help.urls', namespace='help')),
```

## Dependencies

- **accounts** — role-group filtering uses `CustomUser` roles.

## External services

None.
